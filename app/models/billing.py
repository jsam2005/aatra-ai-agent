"""Mock SaaS backend data: users, plans, subscriptions, invoices, payments, tickets.

In production this would live in other systems (identity provider, billing platform such as
Chargebee/Stripe, helpdesk). It shares the SQLite file here only for convenience; the agent never
touches these tables directly, only through the service interfaces in app/backend/.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow
from app.models.enums import (
    DeclineCode,
    InvoiceStatus,
    PaymentAttemptStatus,
    SubscriptionStatus,
    TicketPriority,
    TicketStatus,
)
from app.models.support import _enum


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    interval: Mapped[str] = mapped_column(String(10), default="month")  # month | year
    seats: Mapped[int] = mapped_column(Integer, default=1)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[SubscriptionStatus] = mapped_column(_enum(SubscriptionStatus))
    current_period_start: Mapped[date]
    current_period_end: Mapped[date]
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    plan: Mapped[Plan] = relationship()


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    brand: Mapped[str] = mapped_column(String(20))
    last4: Mapped[str] = mapped_column(String(4))
    exp_month: Mapped[int]
    exp_year: Mapped[int]
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    amount_cents: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[InvoiceStatus] = mapped_column(_enum(InvoiceStatus))
    issued_on: Mapped[date]
    paid_at: Mapped[datetime | None]

    attempts: Mapped[list["PaymentAttempt"]] = relationship(
        back_populates="invoice", order_by="PaymentAttempt.id"
    )


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"))
    status: Mapped[PaymentAttemptStatus] = mapped_column(_enum(PaymentAttemptStatus))
    decline_code: Mapped[DeclineCode | None] = mapped_column(_enum(DeclineCode))
    attempted_at: Mapped[datetime] = mapped_column(default=utcnow)

    invoice: Mapped[Invoice] = relationship(back_populates="attempts")


class PasswordResetRequest(Base):
    """Stands in for 'an email with a reset link was sent'."""

    __tablename__ = "password_reset_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sent_to: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    subject: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    priority: Mapped[TicketPriority] = mapped_column(_enum(TicketPriority))
    status: Mapped[TicketStatus] = mapped_column(_enum(TicketStatus), default=TicketStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
