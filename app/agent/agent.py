"""The support agent: a bounded tool-use loop with deterministic guardrails around the model.

The model decides *what* to do (which tool, which arguments). Code decides *whether it may*:
argument validation, user scoping, confirmation for money-moving actions, round limits, and
error containment all live here, not in the prompt.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from app.agent.llm.base import (
    LLMProvider,
    ModelTurn,
    ToolCall,
    ToolOutcome,
    ToolResults,
    ToolSpec,
    TranscriptItem,
    Usage,
    UserText,
)
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools.base import ToolContext, ToolRegistry
from app.core.errors import AppError, LLMUnavailableError
from app.models.enums import Route, ToolCategory, ToolInvocationStatus

log = logging.getLogger(__name__)

_CITATION = re.compile(r"\[KB-(\d+)\]")
FALLBACK_TEXT = "Sorry, I couldn't complete that request. Would you like me to open a ticket with our support team?"


class ActionGate(Protocol):
    """Stores a proposed side-effecting action until the user confirms it."""

    def propose(self, ctx: ToolContext, tool_name: str, arguments: dict[str, Any], summary: str) -> int: ...


@dataclass
class ToolRecord:
    name: str
    arguments: dict[str, Any]
    status: ToolInvocationStatus
    result: dict[str, Any] | None
    duration_ms: int


@dataclass
class AgentReply:
    text: str
    route: Route
    citations: list[int]
    provider: str
    model: str
    usage: Usage
    model_calls: int = 0
    degraded: bool = False
    fallback_reason: str | None = None
    tool_records: list[ToolRecord] = field(default_factory=list)
    pending_action_ids: list[int] = field(default_factory=list)


class SupportAgent:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        gate: ActionGate,
        *,
        fallback: LLMProvider | None = None,
        max_tool_rounds: int = 5,
        system_prompt: str = SYSTEM_PROMPT,
        checkpoint: Callable[[], None] | None = None,
    ):
        self.provider = provider
        self.fallback = fallback
        self.registry = registry
        self.gate = gate
        self.max_tool_rounds = max_tool_rounds
        self.system_prompt = system_prompt
        # Called after every tool round so side effects are committed and no DB write lock is
        # held while waiting on the model.
        self.checkpoint = checkpoint or (lambda: None)
        self.tool_specs = [ToolSpec(t.name, t.description, t.input_schema()) for t in registry.all()]
        self.tool_names = [t.name for t in registry.all()]

    def run(self, ctx: ToolContext, history: list[TranscriptItem], user_text: str) -> AgentReply:
        """Bounded loop: at most `max_tool_rounds` tool rounds, so at most rounds + 1 model calls."""
        transcript: list[TranscriptItem] = [*history, UserText(user_text)]
        usage = Usage()
        outcomes: list[ToolOutcome] = []
        records: list[ToolRecord] = []
        provider, model, calls = self.provider, "", 0
        degraded, reason = False, None
        final: ModelTurn | None = None

        for round_no in range(self.max_tool_rounds + 1):
            try:
                turn = provider.complete(self.system_prompt, transcript, self.tool_specs)
            except LLMUnavailableError as e:
                if self.fallback is None or degraded:
                    raise
                # Degrade *within* the turn: the fallback sees the same transcript, including any
                # tool results already produced, so completed actions are reported, never repeated.
                log.warning("Provider %s failed (%s); continuing with %s", provider.name, e.message, self.fallback.name)
                provider, degraded, reason = self.fallback, True, e.details.get("reason", "unavailable")
                turn = provider.complete(self.system_prompt, transcript, self.tool_specs)
            calls += 1
            usage.add(turn.usage)
            model = turn.model
            transcript.append(turn)
            if not turn.tool_calls:
                final = turn
                break
            if round_no == self.max_tool_rounds:
                log.warning("Agent hit the tool-round limit (%s)", self.max_tool_rounds)
                break
            round_outcomes = [self._execute(call, ctx, records, outcomes) for call in turn.tool_calls]
            outcomes.extend(round_outcomes)
            transcript.append(ToolResults(round_outcomes))
            self.checkpoint()

        text = final.text if final and final.text else FALLBACK_TEXT
        retrieved = {cid for o in outcomes if o.result for cid in o.result.citations}
        citations = list(dict.fromkeys(int(m) for m in _CITATION.findall(text) if int(m) in retrieved))
        clean_text = re.sub(r"\s*\[KB-\d+\]", "", text)
        # Models occasionally cite a tool like "[list_invoices]"; internal names never reach users.
        clean_text = re.sub(rf"\s*\[(?:{'|'.join(map(re.escape, self.tool_names))})\]", "", clean_text).strip()

        return AgentReply(
            text=clean_text,
            route=self._derive_route(outcomes),
            citations=citations,
            provider=provider.name,
            model=model,
            usage=usage,
            model_calls=calls,
            degraded=degraded,
            fallback_reason=reason,
            tool_records=records,
            pending_action_ids=list(dict.fromkeys(o.pending_action_id for o in outcomes if o.pending_action_id is not None)),
        )

    # ---- tool execution ----

    def _execute(
        self, call: ToolCall, ctx: ToolContext, records: list[ToolRecord], earlier: list[ToolOutcome]
    ) -> ToolOutcome:
        started = time.perf_counter()
        outcome = self._reuse_read(call, earlier) or self._execute_inner(call, ctx)
        if outcome.error is not None:
            status, result = ToolInvocationStatus.ERROR, {"error": outcome.error}
        elif outcome.pending_action_id is not None:
            status = ToolInvocationStatus.PENDING_CONFIRMATION
            result = {"pending_action_id": outcome.pending_action_id, "summary": outcome.pending_summary}
        else:
            status, result = ToolInvocationStatus.SUCCESS, outcome.to_model_payload()
        records.append(ToolRecord(call.name, call.arguments, status, result, int((time.perf_counter() - started) * 1000)))
        return outcome

    def _reuse_read(self, call: ToolCall, earlier: list[ToolOutcome]) -> ToolOutcome | None:
        """Identical read-only calls within one turn reuse the first result (saves tokens, no extra I/O)."""
        tool = self.registry.get(call.name)
        if tool is None or tool.category not in (ToolCategory.READ, ToolCategory.KNOWLEDGE):
            return None
        for o in earlier:
            if o.result is not None and o.call.name == call.name and o.call.arguments == call.arguments:
                return ToolOutcome(call, result=o.result)
        return None

    def _execute_inner(self, call: ToolCall, ctx: ToolContext) -> ToolOutcome:
        tool = self.registry.get(call.name)
        if tool is None:
            return ToolOutcome(call, error=f"Unknown tool '{call.name}'.")
        try:
            args = tool.parse_args(call.arguments)
        except ValidationError as e:
            return ToolOutcome(call, error=f"Invalid arguments: {e.errors(include_url=False)[0]['msg']}")

        try:
            if tool.requires_confirmation:
                summary = tool.describe(args, ctx)
                action_id = self.gate.propose(ctx, tool.name, args.model_dump(), summary)
                return ToolOutcome(call, pending_action_id=action_id, pending_summary=summary)
            return ToolOutcome(call, result=tool.run(args, ctx))
        except AppError as e:  # expected business errors are reported to the model, not raised
            return ToolOutcome(call, error=e.message)
        except Exception:  # never let one tool crash the conversation
            log.exception("Tool %s failed", call.name)
            return ToolOutcome(call, error="Internal error while running this tool.")

    # ---- routing label ----

    def _derive_route(self, outcomes: list[ToolOutcome]) -> Route:
        if any(o.pending_action_id is not None for o in outcomes):
            return Route.PENDING_CONFIRMATION
        ok = [o for o in outcomes if o.result is not None]
        categories = {self.registry.get(o.call.name).category for o in ok}
        for category, route in (
            (ToolCategory.ESCALATION, Route.ESCALATION),
            (ToolCategory.ACTION, Route.BACKEND_ACTION),
            (ToolCategory.READ, Route.BACKEND_READ),
            (ToolCategory.KNOWLEDGE, Route.KNOWLEDGE_BASE),
        ):
            if category in categories:
                return route
        return Route.ERROR if outcomes else Route.DIRECT
