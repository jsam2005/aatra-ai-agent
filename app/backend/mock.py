"""Database-backed mock implementations of the backend services.

Behaviour is deliberately deterministic so demos, tests and evals are reproducible:
  * a payment retry fails only if the default card is expired (or there is no card);
  * dunning allows `max_payment_retries` failed attempts before a human must step in;
  * password reset emails are rate limited per user (repeat requests reuse the last one).
"""

from datetime import date, timedelta

from sqlalchemy import insert, literal, select
from sqlalchemy.orm import Session

from app.backend.interfaces import (
    AccountService,
    BillingService,
    InvoiceInfo,
    PasswordResetResult,
    PaymentIssue,
    PaymentMethodInfo,
    PaymentRetryResult,
    RetryNotAllowedError,
    SubscriptionInfo,
    TicketInfo,
    TicketService,
    UserProfile,
)
from app.core.errors import NotFoundError
from app.db import utcnow
from app.models import (
    Invoice,
    PasswordResetRequest,
    PaymentAttempt,
    PaymentMethod,
    Subscription,
    SupportTicket,
    User,
)
from app.models.enums import (
    DeclineCode,
    InvoiceStatus,
    PaymentAttemptStatus,
    SubscriptionStatus,
    TicketPriority,
    TicketStatus,
)


def format_money(cents: int, currency: str) -> str:
    return f"{cents / 100:,.2f} {currency}"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[0]}{'*' * max(len(local) - 1, 1)}@{domain}"


def _is_expired(pm: PaymentMethod, today: date) -> bool:
    return (pm.exp_year, pm.exp_month) < (today.year, today.month)


_DECLINE_EXPLANATIONS = {
    DeclineCode.CARD_EXPIRED: "The card on file has expired.",
    DeclineCode.INSUFFICIENT_FUNDS: "The bank declined the charge for insufficient funds.",
    DeclineCode.CARD_DECLINED: "The card issuer declined the charge without giving a reason.",
    DeclineCode.PROCESSING_ERROR: "The payment gateway had a temporary processing error.",
}


class MockAccountService(AccountService):
    def __init__(self, session: Session, reset_cooldown_minutes: int = 10):
        self.session = session
        self.reset_cooldown = timedelta(minutes=reset_cooldown_minutes)

    def get_profile(self, user_id: int) -> UserProfile | None:
        user = self.session.get(User, user_id)
        return UserProfile(user.id, user.name, user.email) if user else None

    def send_password_reset(self, user_id: int) -> PasswordResetResult:
        user = self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("User not found")
        now = utcnow()
        expires = now + timedelta(hours=1)
        recent = (
            select(PasswordResetRequest.id)
            .where(PasswordResetRequest.user_id == user_id, PasswordResetRequest.created_at >= now - self.reset_cooldown)
            .exists()
        )
        # Single INSERT ... SELECT ... WHERE NOT EXISTS: the cooldown check and the insert are one
        # atomic statement, so two concurrent requests cannot both send an email.
        inserted = self.session.execute(
            insert(PasswordResetRequest).from_select(
                ["user_id", "sent_to", "created_at", "expires_at"],
                select(literal(user_id), literal(user.email), literal(now), literal(expires)).where(~recent),
            )
        ).rowcount
        if inserted:
            return PasswordResetResult(mask_email(user.email), expires, False)
        last = self.session.scalar(
            select(PasswordResetRequest).where(PasswordResetRequest.user_id == user_id).order_by(PasswordResetRequest.id.desc())
        )
        return PasswordResetResult(mask_email(last.sent_to), last.expires_at, True)


class MockBillingService(BillingService):
    def __init__(self, session: Session, max_retries: int = 3):
        self.session = session
        self.max_retries = max_retries

    # ---- reads ----

    def _current_subscription(self, user_id: int) -> Subscription | None:
        return self.session.scalar(
            select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id.desc())
        )

    def _default_card(self, user_id: int) -> PaymentMethod | None:
        return self.session.scalar(
            select(PaymentMethod).where(PaymentMethod.user_id == user_id, PaymentMethod.is_default.is_(True))
        )

    def get_subscription(self, user_id: int) -> SubscriptionInfo | None:
        sub = self._current_subscription(user_id)
        if sub is None:
            return None
        return SubscriptionInfo(
            plan_code=sub.plan.code,
            plan_name=sub.plan.name,
            price=format_money(sub.plan.price_cents, sub.plan.currency),
            interval=sub.plan.interval,
            seats=sub.plan.seats,
            status=sub.status.value,
            current_period_start=sub.current_period_start,
            current_period_end=sub.current_period_end,
            cancel_at_period_end=sub.cancel_at_period_end,
        )

    def list_invoices(self, user_id: int, limit: int = 5) -> list[InvoiceInfo]:
        rows = self.session.scalars(
            select(Invoice).where(Invoice.user_id == user_id).order_by(Invoice.issued_on.desc()).limit(limit)
        ).all()
        return [
            InvoiceInfo(i.number, format_money(i.amount_cents, i.currency), i.status.value, i.issued_on, i.paid_at)
            for i in rows
        ]

    def _latest_unpaid_invoice(self, user_id: int) -> Invoice | None:
        return self.session.scalar(
            select(Invoice)
            .where(Invoice.user_id == user_id, Invoice.status == InvoiceStatus.PAYMENT_DUE)
            .order_by(Invoice.issued_on.desc())
        )

    def get_payment_issue(self, user_id: int) -> PaymentIssue | None:
        invoice = self._latest_unpaid_invoice(user_id)
        if invoice is None:
            return None
        failed = [a for a in invoice.attempts if a.status == PaymentAttemptStatus.FAILED]
        last = failed[-1] if failed else None
        card = self._default_card(user_id)
        today = utcnow().date()
        card_info = (
            PaymentMethodInfo(card.brand, card.last4, f"{card.exp_month:02d}/{card.exp_year}", _is_expired(card, today))
            if card
            else None
        )
        retries_remaining = max(self.max_retries - len(failed), 0)

        # Rules, not judgement: the same facts always produce the same recommendation.
        if card is None or card_info.is_expired:
            action = "update_payment_method"
            why = "There is no valid card on file, so retrying now would fail again; a new card needs to be added first."
        elif retries_remaining == 0:
            action = "escalate_to_human"
            why = "All automatic retries have been used, so a billing specialist needs to review the account."
        else:
            action = "retry_payment"
            why = "The card on file is still valid, so the charge can be retried now once you confirm."
        if last and last.decline_code:
            why = f"{_DECLINE_EXPLANATIONS[last.decline_code]} {why}"

        return PaymentIssue(
            invoice_number=invoice.number,
            amount=format_money(invoice.amount_cents, invoice.currency),
            failed_attempts=len(failed),
            last_decline_code=last.decline_code.value if last and last.decline_code else None,
            last_attempt_at=last.attempted_at if last else None,
            retries_remaining=retries_remaining,
            payment_method=card_info,
            recommended_action=action,
            explanation=why,
        )

    # ---- writes ----

    def retry_payment(self, user_id: int, invoice_number: str) -> PaymentRetryResult:
        invoice = self.session.scalar(
            select(Invoice).where(Invoice.user_id == user_id, Invoice.number == invoice_number)
        )
        if invoice is None:
            raise NotFoundError(f"Invoice {invoice_number} not found")
        amount = format_money(invoice.amount_cents, invoice.currency)
        if invoice.status == InvoiceStatus.PAID:  # idempotent: never charge twice
            return PaymentRetryResult(invoice.number, True, None, amount, "Invoice was already paid.")
        if invoice.status != InvoiceStatus.PAYMENT_DUE:
            raise RetryNotAllowedError(f"Invoice {invoice_number} is {invoice.status.value}")

        failed = sum(1 for a in invoice.attempts if a.status == PaymentAttemptStatus.FAILED)
        if failed >= self.max_retries:
            raise RetryNotAllowedError("Retry limit reached for this invoice; a specialist must review it.")

        card = self._default_card(user_id)
        now = utcnow()
        if card is None or _is_expired(card, now.date()):
            self.session.add(
                PaymentAttempt(
                    invoice_id=invoice.id,
                    payment_method_id=card.id if card else None,
                    status=PaymentAttemptStatus.FAILED,
                    decline_code=DeclineCode.CARD_EXPIRED,
                    attempted_at=now,
                )
            )
            self.session.flush()
            return PaymentRetryResult(
                invoice.number, False, DeclineCode.CARD_EXPIRED.value, amount, "Charge failed: card expired."
            )

        self.session.add(
            PaymentAttempt(
                invoice_id=invoice.id, payment_method_id=card.id, status=PaymentAttemptStatus.SUCCEEDED, attempted_at=now
            )
        )
        invoice.status = InvoiceStatus.PAID
        invoice.paid_at = now
        sub = self.session.get(Subscription, invoice.subscription_id)
        if sub and sub.status == SubscriptionStatus.PAST_DUE:
            sub.status = SubscriptionStatus.ACTIVE
        self.session.flush()
        return PaymentRetryResult(
            invoice.number, True, None, amount, f"Charged {amount} to {card.brand} ending {card.last4}."
        )


class MockTicketService(TicketService):
    def __init__(self, session: Session):
        self.session = session

    def create_ticket(
        self, user_id: int, conversation_id: int | None, subject: str, summary: str, priority: str
    ) -> TicketInfo:
        if conversation_id is not None:  # one open ticket per conversation is enough
            existing = self.session.scalar(
                select(SupportTicket).where(
                    SupportTicket.user_id == user_id,
                    SupportTicket.conversation_id == conversation_id,
                    SupportTicket.status == TicketStatus.OPEN,
                )
            )
            if existing:
                return self._info(existing, already_open=True)
        ticket = SupportTicket(
            user_id=user_id,
            conversation_id=conversation_id,
            subject=subject[:200],
            summary=summary,
            priority=TicketPriority(priority),
        )
        self.session.add(ticket)
        self.session.flush()
        return self._info(ticket)

    @staticmethod
    def _info(t: SupportTicket, already_open: bool = False) -> TicketInfo:
        return TicketInfo(t.id, f"SUP-{t.id:05d}", t.subject, t.priority.value, t.status.value, already_open)
