"""Human-in-the-loop for side-effecting agent actions.

The model can only *propose* a confirmation-gated action. Executing it requires an explicit
POST /actions/{id}/confirm from the owning user, and runs the tool directly — no LLM involved —
so a confirmed retry always does exactly what the confirmation button said.
"""

from datetime import timedelta
from typing import Any

from app.agent.tools.base import ToolContext, ToolRegistry
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db import utcnow
from app.models import Message, PendingAction
from app.models.enums import MessageRole, PendingActionStatus, Route
from app.repositories.conversations import ConversationRepository, PendingActionRepository


class DBActionGate:
    """ActionGate backed by the pending_actions table. Re-proposing the same action reuses it."""

    def __init__(self, repo: PendingActionRepository, ttl_minutes: int):
        self.repo = repo
        self.ttl = timedelta(minutes=ttl_minutes)

    def propose(self, ctx: ToolContext, tool_name: str, arguments: dict[str, Any], summary: str) -> int:
        for existing in self.repo.open_for_conversation(ctx.conversation_id):
            if existing.tool_name == tool_name and existing.arguments == arguments and existing.expires_at > utcnow():
                return existing.id
        action = self.repo.add(
            PendingAction(
                user_id=ctx.user_id,
                conversation_id=ctx.conversation_id,
                tool_name=tool_name,
                arguments=arguments,
                summary=summary,
                expires_at=utcnow() + self.ttl,
            )
        )
        return action.id


class ActionService:
    def __init__(
        self,
        actions: PendingActionRepository,
        conversations: ConversationRepository,
        registry: ToolRegistry,
        ctx_factory,
    ):
        self.actions = actions
        self.conversations = conversations
        self.registry = registry
        self.ctx_factory = ctx_factory  # (user_id, conversation_id) -> ToolContext

    def get(self, action_id: int, user_id: int) -> PendingAction:
        action = self.actions.get_for_user(action_id, user_id)
        if action is None:
            raise NotFoundError(f"Action {action_id} not found")
        if action.status == PendingActionStatus.PENDING and action.expires_at <= utcnow():
            action.status = PendingActionStatus.EXPIRED
            action.resolved_at = utcnow()
        return action

    def _require_pending(self, action: PendingAction) -> None:
        if action.status != PendingActionStatus.PENDING:
            raise ConflictError(f"Action is already {action.status.value}", details={"status": action.status.value})

    def confirm(self, action_id: int, user_id: int) -> tuple[PendingAction, Message]:
        if not self.actions.claim(action_id, user_id, utcnow()):
            action = self.get(action_id, user_id)  # 404 if missing or not owned; marks expiry
            self._require_pending(action)  # not pending -> 409 with its status
            raise ConflictError("Action could not be claimed", details={"status": action.status.value})
        action = self.get(action_id, user_id)
        self.actions.session.refresh(action)
        tool = self.registry.get(action.tool_name)
        ctx = self.ctx_factory(user_id, action.conversation_id)
        try:
            result = tool.run(tool.parse_args(action.arguments), ctx)
            ok, payload, text = result.ok, result.to_model_payload(), result.summary
        except AppError as e:
            ok, payload, text = False, {"ok": False, "error": e.message}, f"I couldn't complete that: {e.message}"
        action.status = PendingActionStatus.CONFIRMED if ok else PendingActionStatus.FAILED
        action.result = payload
        action.resolved_at = utcnow()
        return action, self._post(action, text, Route.BACKEND_ACTION)

    def cancel(self, action_id: int, user_id: int) -> tuple[PendingAction, Message]:
        action = self.get(action_id, user_id)
        self._require_pending(action)
        action.status = PendingActionStatus.CANCELLED
        action.resolved_at = utcnow()
        return action, self._post(action, "No problem, I've cancelled that. Nothing was charged.", Route.DIRECT)

    def _post(self, action: PendingAction, text: str, route: Route) -> Message:
        """Record the outcome in the conversation so history (and the model) sees it next turn."""
        return self.conversations.add_message(
            Message(
                conversation_id=action.conversation_id,
                role=MessageRole.ASSISTANT,
                content=text,
                route=route,
                provider="system",
            )
        )
