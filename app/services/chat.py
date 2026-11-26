import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.agent.agent import SupportAgent
from app.agent.llm.base import AssistantText, LLMProvider, TranscriptItem, UserText
from app.agent.tools.base import ToolRegistry
from app.core.errors import NotFoundError
from app.db import utcnow
from app.models import Conversation, Message, PendingAction, ToolInvocation
from app.models.enums import MessageRole
from app.repositories.conversations import ConversationRepository, PendingActionRepository
from app.services.actions import DBActionGate

log = logging.getLogger(__name__)


@dataclass
class ChatResult:
    conversation: Conversation
    user_message: Message
    reply: Message
    pending_actions: list[PendingAction]


class ChatService:
    def __init__(
        self,
        conversations: ConversationRepository,
        actions: PendingActionRepository,
        registry: ToolRegistry,
        gate: DBActionGate,
        ctx_factory,
        primary: LLMProvider,
        fallback: LLMProvider | None,
        *,
        max_tool_rounds: int,
        history_messages: int,
        commit: Callable[[], None] = lambda: None,
    ):
        self.conversations = conversations
        self.actions = actions
        self.registry = registry
        self.gate = gate
        self.ctx_factory = ctx_factory
        self.primary = primary
        self.fallback = fallback
        self.max_tool_rounds = max_tool_rounds
        self.history_messages = history_messages
        self.commit = commit

    # ---- conversations ----

    def get_conversation(self, conversation_id: int, user_id: int) -> Conversation:
        conv = self.conversations.get_for_user(conversation_id, user_id)
        if conv is None:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        return conv

    def create_conversation(self, user_id: int, title: str | None = None) -> Conversation:
        return self.conversations.create(user_id, title)

    def list_conversations(self, user_id: int, limit: int, offset: int):
        return self.conversations.list_for_user(user_id, limit=limit, offset=offset)

    def delete_conversation(self, conversation_id: int, user_id: int) -> None:
        self.conversations.delete(self.get_conversation(conversation_id, user_id))

    def open_actions(self, conversation_id: int) -> list[PendingAction]:
        return self.actions.open_for_conversation(conversation_id)

    # ---- chat ----

    def send_message(self, user_id: int, text: str, conversation_id: int | None = None) -> ChatResult:
        conv = (
            self.get_conversation(conversation_id, user_id)
            if conversation_id is not None
            else self.conversations.create(user_id)
        )
        if not conv.title:
            conv.title = text.strip()[:80]

        history = self._history(conv.id)
        request_id = uuid.uuid4().hex
        user_msg = self.conversations.add_message(
            Message(conversation_id=conv.id, role=MessageRole.USER, content=text, request_id=request_id)
        )
        # Commit before calling the model: SQLite allows one writer, and a model call can take
        # seconds. The agent commits again after each tool round (checkpoint) for the same reason.
        self.commit()
        ctx = self.ctx_factory(user_id, conv.id)

        started = time.perf_counter()
        agent = SupportAgent(
            self.primary,
            self.registry,
            self.gate,
            fallback=self.fallback,
            max_tool_rounds=self.max_tool_rounds,
            checkpoint=self.commit,
        )
        reply = agent.run(ctx, history, text)
        latency_ms = int((time.perf_counter() - started) * 1000)

        assistant = self.conversations.add_message(
            Message(
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT,
                content=reply.text,
                request_id=request_id,
                route=reply.route,
                citations=reply.citations,
                provider=reply.provider,
                model=reply.model,
                degraded=reply.degraded,
                fallback_reason=reply.fallback_reason,
                model_calls=reply.model_calls,
                latency_ms=latency_ms,
                input_tokens=reply.usage.input_tokens,
                output_tokens=reply.usage.output_tokens,
            )
        )
        for rec in reply.tool_records:
            self.conversations.add_tool_invocation(
                ToolInvocation(
                    message_id=assistant.id,
                    tool_name=rec.name,
                    arguments=rec.arguments,
                    result=rec.result,
                    status=rec.status,
                    duration_ms=rec.duration_ms,
                )
            )
        pending = [a for a in self.actions.open_for_conversation(conv.id) if a.id in reply.pending_action_ids]
        for action in pending:
            action.message_id = action.message_id or assistant.id
        conv.updated_at = utcnow()
        self.conversations.session.flush()  # so the reply's `actions` relationship sees the link
        return ChatResult(conv, user_msg, assistant, pending)

    def _history(self, conversation_id: int) -> list[TranscriptItem]:
        items: list[TranscriptItem] = []
        for m in self.conversations.recent_messages(conversation_id, self.history_messages):
            items.append(UserText(m.content) if m.role == MessageRole.USER else AssistantText(m.content))
        return items
