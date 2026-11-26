"""Deterministic, rule-based stand-in for the LLM.

Used when no API key is configured (so reviewers can run everything offline), as the degraded
mode when the LLM API is down, and as a fast, free baseline in tests and evals. It implements the
same `LLMProvider` contract, so it drives exactly the same agent loop, tools and guardrails.
It is intentionally simple: keyword intent rules plus templated answers built from tool results.
"""

import itertools
import re

from app.agent.llm.base import (
    LLMProvider,
    ModelTurn,
    ToolCall,
    ToolOutcome,
    ToolResults,
    ToolSpec,
    TranscriptItem,
    UserText,
)

_INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("escalate", re.compile(r"\b(human|real person|agent|representative|speak to|talk to|manager|complain|complaint)\b")),
    ("password", re.compile(r"\b(password|reset my|locked out|can'?t log ?in|cannot log ?in|unable to log ?in|login issue)\b")),
    ("payment_issue", re.compile(r"\b(payment|charge|card)\b.*\b(fail|failed|declin|bounced|didn'?t go|not go|problem|issue|error)|\b(fail|failed|declined)\b.*\b(payment|charge|card)\b")),
    ("subscription", re.compile(r"\bsubscription\b|\b(my|current|which) plan\b|\bplan am i\b|\b(renew|renews|renewal|next billing|billing date)\b")),
    ("invoices", re.compile(r"\b(invoice|invoices|receipt|receipts|billing history|charged me|my bill)\b")),
]
_GREETING = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening))\b[\s!.]*$", re.I)
_TOOL_FOR_INTENT = {
    "escalate": "escalate_to_human",
    "password": "send_password_reset",
    "payment_issue": "get_payment_issue",
    "subscription": "get_subscription",
    "invoices": "list_invoices",
}


def classify(text: str) -> str:
    lowered = text.lower()
    if _GREETING.match(lowered):
        return "greeting"
    for intent, pattern in _INTENTS:
        if pattern.search(lowered):
            return intent
    return "knowledge"


def _first_sentences(text: str, limit: int = 380) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out = ""
    for s in sentences:
        if len(out) + len(s) > limit and out:
            break
        out = f"{out} {s}".strip()
    return out


class OfflineProvider(LLMProvider):
    name = "offline"
    model = "rule-based-v1"

    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def _call(self, name: str, **arguments) -> ToolCall:
        return ToolCall(f"offline_{next(self._ids)}", name, arguments)

    def _turn(self, text: str = "", calls: list[ToolCall] | None = None) -> ModelTurn:
        calls = calls or []
        return ModelTurn(text, calls, "tool_use" if calls else "end_turn", self.model)

    def complete(self, system: str, transcript: list[TranscriptItem], tools: list[ToolSpec]) -> ModelTurn:
        last_user = max(i for i, item in enumerate(transcript) if isinstance(item, UserText))
        user_text: str = transcript[last_user].text  # type: ignore[union-attr]
        outcomes = [o for item in transcript[last_user + 1 :] if isinstance(item, ToolResults) for o in item.outcomes]

        if not outcomes:
            return self._first_step(user_text)
        follow_up = self._follow_up(outcomes)
        if follow_up:
            return self._turn(calls=[follow_up])
        return self._turn(self._compose(outcomes))

    def _first_step(self, user_text: str) -> ModelTurn:
        intent = classify(user_text)
        if intent == "greeting":
            return self._turn("Hi! I can help with billing, your subscription, account access and questions about Nimbus. What do you need?")
        if intent == "knowledge":
            return self._turn(calls=[self._call("search_knowledge_base", query=user_text[:300])])
        if intent == "escalate":
            return self._turn(
                calls=[self._call("escalate_to_human", subject="Customer asked for a human agent", summary=user_text[:2000], priority="normal")]
            )
        return self._turn(calls=[self._call(_TOOL_FOR_INTENT[intent])])

    def _follow_up(self, outcomes: list[ToolOutcome]) -> ToolCall | None:
        """Apply get_payment_issue's recommended_action, once."""
        names = {o.call.name for o in outcomes}
        last = outcomes[-1]
        if last.call.name != "get_payment_issue" or last.result is None:
            return None
        issue = last.result.data.get("issue")
        if not issue:
            return None
        action = issue["recommended_action"]
        if action == "retry_payment" and "retry_payment" not in names:
            return self._call("retry_payment", invoice_number=issue["invoice_number"])
        if action == "escalate_to_human" and "escalate_to_human" not in names:
            return self._call(
                "escalate_to_human",
                subject=f"Payment failing for {issue['invoice_number']}",
                summary=f"Automatic retries exhausted. {issue['explanation']}",
                priority="high",
            )
        if action == "update_payment_method" and "search_knowledge_base" not in names:
            return self._call("search_knowledge_base", query="update payment method card")
        return None

    def _compose(self, outcomes: list[ToolOutcome]) -> str:
        parts: list[str] = []
        for o in outcomes:
            if o.error:
                parts.append(f"Sorry, I couldn't complete that step ({o.error}).")
            elif o.pending_action_id is not None:
                parts.append(f"I can retry the charge now: {o.pending_summary}. Press Confirm to go ahead.")
            elif o.call.name == "search_knowledge_base":
                articles = o.result.data.get("articles", [])
                if articles:
                    a = articles[0]
                    parts.append(f"{_first_sentences(a['content'])} [KB-{a['id']}]")
                else:
                    parts.append("I couldn't find anything about that in our help center. I can open a ticket with our support team if you'd like.")
            else:
                parts.append(o.result.summary)
        return " ".join(parts)
