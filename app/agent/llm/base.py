"""Provider-neutral types for one agent turn.

The agent loop speaks only these types; each provider translates them to its own wire format.
That keeps the loop testable with a fake provider and lets the offline provider stand in for
Gemini when no API key is configured or the API is down.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.agent.tools.base import ToolResult


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str  # always set; generated locally when the provider supplies none
    name: str
    arguments: dict[str, Any]
    provider_call_id: str | None = None  # the provider's own id, echoed back with the result


@dataclass
class Usage:
    """Provider-reported token counts. None means "not reported", which is different from 0."""

    input_tokens: int | None = None
    output_tokens: int | None = None

    def add(self, other: "Usage") -> None:
        if other.input_tokens is not None:
            self.input_tokens = (self.input_tokens or 0) + other.input_tokens
        if other.output_tokens is not None:
            self.output_tokens = (self.output_tokens or 0) + other.output_tokens


# ---- transcript items ----


@dataclass(frozen=True)
class UserText:
    text: str


@dataclass(frozen=True)
class AssistantText:
    """A previous assistant answer replayed from conversation history."""

    text: str


@dataclass
class ModelTurn:
    """One response from the model inside the current turn."""

    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    model: str
    usage: Usage = field(default_factory=Usage)
    raw: Any = None  # provider-native content, replayed verbatim (keeps thinking blocks intact)


@dataclass
class ToolOutcome:
    call: ToolCall
    result: ToolResult | None = None
    error: str | None = None
    pending_action_id: int | None = None
    pending_summary: str | None = None

    def to_model_payload(self) -> dict[str, Any]:
        if self.error is not None:
            return {"ok": False, "error": self.error}
        if self.pending_action_id is not None:
            return {
                "ok": True,
                "status": "awaiting_customer_confirmation",
                "action": self.pending_summary,
                "instruction": (
                    "Nothing has been executed yet. Tell the customer exactly what will happen and that "
                    "they must press the Confirm button to proceed. Do not claim it is done."
                ),
            }
        assert self.result is not None
        return self.result.to_model_payload()

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class ToolResults:
    outcomes: list[ToolOutcome]


TranscriptItem = UserText | AssistantText | ModelTurn | ToolResults


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(self, system: str, transcript: list[TranscriptItem], tools: list[ToolSpec]) -> ModelTurn:
        """Produce the next model turn. Raise LLMUnavailableError if the model cannot be reached."""
