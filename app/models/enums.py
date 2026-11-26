from enum import StrEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Route(StrEnum):
    """How the agent answered a turn. Derived deterministically from the tools it used."""

    KNOWLEDGE_BASE = "knowledge_base"  # answered from KB articles
    BACKEND_READ = "backend_read"  # looked up account/billing data
    BACKEND_ACTION = "backend_action"  # performed a side-effecting operation
    PENDING_CONFIRMATION = "pending_confirmation"  # proposed an action that needs the user's OK
    ESCALATION = "escalation"  # handed off to a human
    DIRECT = "direct"  # no tools: greeting, clarification, out-of-scope
    ERROR = "error"  # the turn failed


class ToolCategory(StrEnum):
    KNOWLEDGE = "knowledge"
    READ = "read"
    ACTION = "action"
    ESCALATION = "escalation"


class ToolInvocationStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    PENDING_CONFIRMATION = "pending_confirmation"


class PendingActionStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"  # executed successfully
    FAILED = "failed"  # executed, but the backend operation failed
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class FeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"


# --- mock billing domain ---


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"  # a renewal payment failed and is being retried (dunning)
    CANCELLED = "cancelled"


class InvoiceStatus(StrEnum):
    PAID = "paid"
    PAYMENT_DUE = "payment_due"  # at least one failed attempt, still collectable
    VOID = "void"


class PaymentAttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DeclineCode(StrEnum):
    CARD_EXPIRED = "card_expired"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    CARD_DECLINED = "card_declined"  # generic issuer decline
    PROCESSING_ERROR = "processing_error"  # transient gateway error


class TicketStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
