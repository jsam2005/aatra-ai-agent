"""Contracts for the SaaS backend the agent operates on.

The agent's tools depend only on these interfaces and DTOs, never on ORM models, so the mock
implementations in app/backend/mock.py could be swapped for real Chargebee/Stripe/Auth0/Zendesk
clients without touching the agent.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

from app.core.errors import AppError


class RetryNotAllowedError(AppError):
    status_code = 409
    code = "retry_not_allowed"


# ---------- DTOs ----------


@dataclass(frozen=True)
class UserProfile:
    id: int
    name: str
    email: str


@dataclass(frozen=True)
class SubscriptionInfo:
    plan_code: str
    plan_name: str
    price: str  # formatted, e.g. "49.00 USD"
    interval: str
    seats: int
    status: str
    current_period_start: date
    current_period_end: date
    cancel_at_period_end: bool


@dataclass(frozen=True)
class InvoiceInfo:
    number: str
    amount: str
    status: str
    issued_on: date
    paid_at: datetime | None


@dataclass(frozen=True)
class PaymentMethodInfo:
    brand: str
    last4: str
    expires: str  # MM/YYYY
    is_expired: bool


@dataclass(frozen=True)
class PaymentIssue:
    """Deterministic diagnosis of the user's latest unpaid invoice."""

    invoice_number: str
    amount: str
    failed_attempts: int
    last_decline_code: str | None
    last_attempt_at: datetime | None
    retries_remaining: int
    payment_method: PaymentMethodInfo | None
    recommended_action: str  # update_payment_method | retry_payment | escalate_to_human
    explanation: str


@dataclass(frozen=True)
class PaymentRetryResult:
    invoice_number: str
    succeeded: bool
    decline_code: str | None
    amount: str
    message: str


@dataclass(frozen=True)
class PasswordResetResult:
    sent_to: str  # masked email
    expires_at: datetime
    already_sent_recently: bool


@dataclass(frozen=True)
class TicketInfo:
    id: int
    reference: str
    subject: str
    priority: str
    status: str
    already_open: bool = False  # an open ticket for this conversation already existed


# ---------- service interfaces ----------


class AccountService(ABC):
    @abstractmethod
    def get_profile(self, user_id: int) -> UserProfile | None: ...

    @abstractmethod
    def send_password_reset(self, user_id: int) -> PasswordResetResult: ...


class BillingService(ABC):
    @abstractmethod
    def get_subscription(self, user_id: int) -> SubscriptionInfo | None: ...

    @abstractmethod
    def list_invoices(self, user_id: int, limit: int = 5) -> list[InvoiceInfo]: ...

    @abstractmethod
    def get_payment_issue(self, user_id: int) -> PaymentIssue | None:
        """Return a diagnosis of the latest unpaid invoice, or None if nothing is outstanding."""

    @abstractmethod
    def retry_payment(self, user_id: int, invoice_number: str) -> PaymentRetryResult: ...


class TicketService(ABC):
    @abstractmethod
    def create_ticket(
        self, user_id: int, conversation_id: int | None, subject: str, summary: str, priority: str
    ) -> TicketInfo: ...
