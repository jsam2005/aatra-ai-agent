"""Request/response models for the REST API (kept separate from ORM models)."""

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FeedbackRating, MessageRole, PendingActionStatus, Route, ToolInvocationStatus

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------- knowledge base ----------


class KBArticleBase(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=10, max_length=20_000)
    category: str = Field(min_length=2, max_length=50, examples=["billing"])
    tags: list[str] = Field(default_factory=list, max_length=20)
    is_published: bool = True


class KBArticleCreate(KBArticleBase):
    pass


class KBArticleUpdate(BaseModel):
    """Partial update: only provided fields change."""

    title: str | None = Field(None, min_length=3, max_length=200)
    content: str | None = Field(None, min_length=10, max_length=20_000)
    category: str | None = Field(None, min_length=2, max_length=50)
    tags: list[str] | None = None
    is_published: bool | None = None


class KBArticleOut(KBArticleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class KBSearchHit(BaseModel):
    id: int
    title: str
    category: str
    score: float
    snippet: str


# ---------- chat ----------


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000, examples=["My payment failed"])
    conversation_id: int | None = Field(None, description="Omit to start a new conversation.")


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class CitationOut(BaseModel):
    id: int
    title: str


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tool_name: str
    status: ToolInvocationStatus
    arguments: dict
    duration_ms: int | None


class PendingActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tool_name: str
    summary: str
    status: PendingActionStatus
    expires_at: datetime
    result: dict | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message_id: int
    rating: FeedbackRating
    comment: str | None
    created_at: datetime
    updated_at: datetime


class ResponseCard(BaseModel):
    """Structured, UI-ready view of a successful tool result. Only whitelisted fields are copied,
    so internal or raw payload data never reaches the client."""

    type: Literal["subscription", "invoices", "payment_issue", "password_reset", "ticket"]
    data: dict


class MessageOut(BaseModel):
    id: int
    role: MessageRole
    content: str
    created_at: datetime
    route: Route | None = None
    citations: list[CitationOut] = []
    tool_calls: list[ToolCallOut] = []
    request_id: str | None = None
    provider: str | None = None
    model: str | None = None
    degraded: bool = False
    fallback_reason: str | None = None
    latency_ms: int | None = None
    model_calls: int | None = None
    input_tokens: int | None = None  # null = not reported by the provider (offline mode)
    output_tokens: int | None = None
    actions: list[PendingActionOut] = []  # actions this answer proposed, with their current status
    cards: list[ResponseCard] = []  # structured views of what the tools returned
    feedback: FeedbackOut | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
    pending_actions: list[PendingActionOut] = []


class ChatResponse(BaseModel):
    conversation_id: int
    user_message: MessageOut
    reply: MessageOut
    pending_actions: list[PendingActionOut] = []


class ActionResolution(BaseModel):
    action: PendingActionOut
    message: MessageOut


# ---------- feedback ----------


class FeedbackIn(BaseModel):
    rating: FeedbackRating
    comment: str | None = Field(None, max_length=2000)


class FeedbackWithContext(FeedbackOut):
    route: Route | None
    message_excerpt: str


class RouteFeedbackStats(BaseModel):
    route: Route | None
    up: int
    down: int
    satisfaction: float | None  # up / (up + down)


class ToolFeedbackStats(BaseModel):
    tool_name: str
    up: int
    down: int
    satisfaction: float | None


class FeedbackSummary(BaseModel):
    total: int
    up: int
    down: int
    satisfaction: float | None
    by_route: list[RouteFeedbackStats]
    by_tool: list[ToolFeedbackStats]  # answers that used each tool (one answer may count for several)


# ---------- analytics ----------


class RouteCount(BaseModel):
    route: Route | None
    count: int


class ToolStats(BaseModel):
    tool_name: str
    calls: int
    succeeded: int
    errors: int
    awaiting_confirmation: int
    avg_duration_ms: float | None


class DayFeedback(BaseModel):
    date: str
    up: int
    down: int


class AnalyticsOverview(BaseModel):
    conversations: int
    responses: int  # assistant answers (excludes system messages from confirmations)
    degraded_responses: int
    avg_latency_ms: float | None
    responses_by_route: list[RouteCount]
    tools: list[ToolStats]
    feedback_by_day: list[DayFeedback]  # last 14 days, zero-filled
