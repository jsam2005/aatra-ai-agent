"""Tool abstraction.

Design rules enforced here rather than in the prompt:
  * Tools never accept a user id. They act on `ToolContext.user_id`, which comes from the
    authenticated request, so no prompt can make the agent read or change another account.
  * Arguments are validated with a Pydantic model before the tool runs.
  * Tools with `requires_confirmation = True` are never executed by the model; the agent turns
    the call into a PendingAction that only the user can confirm (see app/agent/agent.py).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from app.agent.retriever import Retriever
from app.backend.interfaces import AccountService, BillingService, TicketService
from app.models.enums import ToolCategory


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class ToolContext:
    user_id: int
    conversation_id: int | None
    account: AccountService
    billing: BillingService
    tickets: TicketService
    retriever: Retriever


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any]
    summary: str  # one human-readable line; used by logs and the offline provider
    citations: list[int] = field(default_factory=list)  # KB article ids surfaced by this call

    def to_model_payload(self) -> dict[str, Any]:
        return {"ok": self.ok, **self.data}


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic JSON schema minus noise ('title' keys) the model does not need."""
    if isinstance(schema, dict):
        return {k: _clean_schema(v) for k, v in schema.items() if k != "title" or not isinstance(v, str)}
    if isinstance(schema, list):
        return [_clean_schema(v) for v in schema]
    return schema


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    category: ClassVar[ToolCategory]
    Args: ClassVar[type[BaseModel]] = NoArgs
    requires_confirmation: ClassVar[bool] = False

    def input_schema(self) -> dict[str, Any]:
        schema = _clean_schema(self.Args.model_json_schema())
        schema.setdefault("properties", {})
        schema["additionalProperties"] = False
        schema["required"] = list(schema["properties"].keys())
        return schema

    def parse_args(self, raw: dict[str, Any]) -> BaseModel:
        return self.Args.model_validate(raw or {})

    @abstractmethod
    def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...

    def describe(self, args: BaseModel, ctx: ToolContext) -> str:
        """Plain-language summary shown on the confirmation button (confirmation tools only)."""
        return f"Run {self.name}"


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())
