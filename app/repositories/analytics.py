from datetime import date, timedelta

from sqlalchemy import String, case, func, select
from sqlalchemy.orm import Session

from app.models import Conversation, Feedback, Message, ToolInvocation
from app.models.enums import FeedbackRating, MessageRole, ToolInvocationStatus


class AnalyticsRepository:
    """Read-only aggregate queries over conversations, messages, tool calls and feedback."""

    def __init__(self, session: Session):
        self.session = session

    def totals(self) -> dict:
        answers = select(Message).where(Message.role == MessageRole.ASSISTANT, Message.provider != "system").subquery()
        return {
            "conversations": self.session.scalar(select(func.count()).select_from(Conversation)) or 0,
            "responses": self.session.scalar(select(func.count()).select_from(answers)) or 0,
            "degraded_responses": self.session.scalar(select(func.count()).select_from(answers).where(answers.c.degraded.is_(True))) or 0,
            "avg_latency_ms": self.session.scalar(select(func.avg(answers.c.latency_ms))),
        }

    def responses_by_route(self) -> list[tuple[str | None, int]]:
        rows = self.session.execute(
            select(Message.route, func.count())
            .where(Message.role == MessageRole.ASSISTANT, Message.provider != "system")
            .group_by(Message.route)
            .order_by(func.count().desc())
        ).all()
        return [(r[0].value if r[0] else None, r[1]) for r in rows]

    def tool_stats(self) -> list[dict]:
        rows = self.session.execute(
            select(
                ToolInvocation.tool_name,
                func.count(),
                func.sum(case((ToolInvocation.status == ToolInvocationStatus.SUCCESS, 1), else_=0)),
                func.sum(case((ToolInvocation.status == ToolInvocationStatus.ERROR, 1), else_=0)),
                func.sum(case((ToolInvocation.status == ToolInvocationStatus.PENDING_CONFIRMATION, 1), else_=0)),
                func.avg(ToolInvocation.duration_ms),
            )
            .group_by(ToolInvocation.tool_name)
            .order_by(func.count().desc())
        ).all()
        return [
            {"tool_name": r[0], "calls": r[1], "succeeded": r[2] or 0, "errors": r[3] or 0, "awaiting_confirmation": r[4] or 0,
             "avg_duration_ms": round(r[5], 1) if r[5] is not None else None}
            for r in rows
        ]

    def feedback_by_day(self, days: int, today: date) -> list[dict]:
        start = today - timedelta(days=days - 1)
        day = func.date(Feedback.created_at, type_=String)  # 'YYYY-MM-DD' (SQLite and Postgres)
        rows = self.session.execute(
            select(
                day,
                func.sum(case((Feedback.rating == FeedbackRating.UP, 1), else_=0)),
                func.sum(case((Feedback.rating == FeedbackRating.DOWN, 1), else_=0)),
            )
            .where(Feedback.created_at >= start)
            .group_by(day)
        ).all()
        by_day = {str(r[0]): (r[1] or 0, r[2] or 0) for r in rows}
        return [
            {"date": (start + timedelta(days=i)).isoformat(), "up": by_day.get((start + timedelta(days=i)).isoformat(), (0, 0))[0],
             "down": by_day.get((start + timedelta(days=i)).isoformat(), (0, 0))[1]}
            for i in range(days)
        ]
