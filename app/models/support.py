"""Support-side data: knowledge base, conversations, agent audit trail, feedback."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow
from app.models.enums import (
    FeedbackRating,
    MessageRole,
    PendingActionStatus,
    Route,
    ToolInvocationStatus,
)


def _enum(cls):
    # Store enums as plain strings: portable across SQLite/Postgres and readable in the DB.
    return Enum(cls, native_enum=False, values_callable=lambda e: [m.value for m in e], length=32)


class KBArticle(Base):
    __tablename__ = "kb_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), index=True)
    tags: Mapped[str] = mapped_column(String(300), default="")  # space-separated, indexed by FTS
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.id", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(_enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(32), index=True)  # ties a user turn to its reply

    # Assistant-only metadata: why and how this answer was produced.
    route: Mapped[Route | None] = mapped_column(_enum(Route), index=True)
    citations: Mapped[list[int] | None] = mapped_column(JSON)  # KB article ids
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)  # finished by the fallback provider
    fallback_reason: Mapped[str | None] = mapped_column(String(32))  # rate_limited | unreachable | ...
    model_calls: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)  # NULL = provider reported nothing
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    tool_invocations: Mapped[list["ToolInvocation"]] = relationship(
        back_populates="message", order_by="ToolInvocation.id", cascade="all, delete-orphan"
    )
    feedback: Mapped["Feedback | None"] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    actions: Mapped[list["PendingAction"]] = relationship(viewonly=True, order_by="PendingAction.id")


class ToolInvocation(Base):
    """Audit trail: every tool the agent called, with arguments and result."""

    __tablename__ = "tool_invocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[ToolInvocationStatus] = mapped_column(_enum(ToolInvocationStatus))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    message: Mapped[Message] = relationship(back_populates="tool_invocations")


class PendingAction(Base):
    """A side-effecting operation the agent proposed; runs only after the user confirms it."""

    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    tool_name: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(String(500))  # shown to the user on the confirm button
    status: Mapped[PendingActionStatus] = mapped_column(
        _enum(PendingActionStatus), default=PendingActionStatus.PENDING, index=True
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("message_id", name="uq_feedback_message"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[FeedbackRating] = mapped_column(_enum(FeedbackRating), index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    message: Mapped[Message] = relationship(back_populates="feedback")
