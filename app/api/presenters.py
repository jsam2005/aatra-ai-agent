"""Map ORM objects to API response models."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, KBArticle, Message, PendingAction
from app.models.enums import ToolInvocationStatus
from app.schemas.api import (
    CitationOut,
    ConversationDetail,
    FeedbackOut,
    MessageOut,
    PendingActionOut,
    ResponseCard,
    ToolCallOut,
)


# tool name -> (card type, key in the stored result, whitelisted fields or None for the whole value)
_CARD_SPECS: dict[str, tuple[str, str | None, tuple[str, ...] | None]] = {
    "get_subscription": ("subscription", "subscription", ("plan", "price", "interval", "seats", "status", "current_period_end", "cancel_at_period_end")),
    "list_invoices": ("invoices", "invoices", ("number", "amount", "status", "issued_on")),
    "get_payment_issue": ("payment_issue", "issue", ("invoice_number", "amount", "failed_attempts", "last_decline_code", "retries_remaining", "payment_method", "recommended_action")),
    "send_password_reset": ("password_reset", None, ("sent_to", "link_valid_for", "already_sent_recently", "simulated")),
    "escalate_to_human": ("ticket", None, ("ticket_reference", "priority", "status", "already_open")),
}


def _pick(value: dict, fields: tuple[str, ...]) -> dict:
    return {k: value[k] for k in fields if k in value}


def response_cards(m: Message) -> list[ResponseCard]:
    cards: list[ResponseCard] = []
    seen: set[str] = set()
    for t in m.tool_invocations:
        spec = _CARD_SPECS.get(t.tool_name)
        if spec is None or t.status != ToolInvocationStatus.SUCCESS or not t.result or t.tool_name in seen:
            continue
        card_type, key, fields = spec
        value = t.result.get(key) if key else t.result
        if card_type == "invoices":
            data = {"invoices": [_pick(i, fields) for i in (value or [])[:5]]}
        elif card_type == "payment_issue" and value is None:
            data = {"none": True}  # verified: nothing unpaid
        elif isinstance(value, dict):
            data = _pick(value, fields)
        else:
            continue
        seen.add(t.tool_name)
        cards.append(ResponseCard(type=card_type, data=data))
    return cards


def _titles(session: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict(session.execute(select(KBArticle.id, KBArticle.title).where(KBArticle.id.in_(ids))).all())


def message_out(session: Session, m: Message, titles: dict[int, str] | None = None) -> MessageOut:
    ids = m.citations or []
    titles = titles if titles is not None else _titles(session, set(ids))
    return MessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        created_at=m.created_at,
        route=m.route,
        # An article deleted after the answer was given simply drops out of the citation list.
        citations=[CitationOut(id=i, title=titles[i]) for i in ids if i in titles],
        tool_calls=[ToolCallOut.model_validate(t) for t in m.tool_invocations],
        request_id=m.request_id,
        provider=m.provider,
        model=m.model,
        degraded=m.degraded,
        fallback_reason=m.fallback_reason,
        latency_ms=m.latency_ms,
        model_calls=m.model_calls,
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
        actions=[PendingActionOut.model_validate(a) for a in m.actions],
        cards=response_cards(m),
        feedback=FeedbackOut.model_validate(m.feedback) if m.feedback else None,
    )


def conversation_detail(session: Session, conv: Conversation, pending: list[PendingAction]) -> ConversationDetail:
    titles = _titles(session, {i for m in conv.messages for i in (m.citations or [])})
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[message_out(session, m, titles) for m in conv.messages],
        pending_actions=[PendingActionOut.model_validate(a) for a in pending],
    )
