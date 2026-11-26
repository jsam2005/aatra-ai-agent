from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import Conversation, Feedback, Message, PendingAction, ToolInvocation
from app.models.enums import FeedbackRating, PendingActionStatus, Route


class ConversationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: int, title: str | None = None) -> Conversation:
        conv = Conversation(user_id=user_id, title=title)
        self.session.add(conv)
        self.session.flush()
        return conv

    def get_for_user(self, conversation_id: int, user_id: int) -> Conversation | None:
        """Ownership is part of the lookup, so another user's id behaves exactly like a missing one."""
        return self.session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .options(
                selectinload(Conversation.messages).selectinload(Message.tool_invocations),
                selectinload(Conversation.messages).selectinload(Message.feedback),
                selectinload(Conversation.messages).selectinload(Message.actions),
            )
        )

    def list_for_user(self, user_id: int, *, limit: int, offset: int) -> tuple[list[Conversation], int]:
        base = select(Conversation).where(Conversation.user_id == user_id)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.scalars(
            base.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit).offset(offset)
        ).all()
        return list(rows), total

    def delete(self, conversation: Conversation) -> None:
        self.session.delete(conversation)
        self.session.flush()

    def recent_messages(self, conversation_id: int, limit: int) -> list[Message]:
        rows = self.session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(limit)
        ).all()
        return list(reversed(rows))

    def add_message(self, message: Message) -> Message:
        self.session.add(message)
        self.session.flush()
        return message

    def add_tool_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        self.session.add(invocation)
        self.session.flush()
        return invocation


class PendingActionRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, action: PendingAction) -> PendingAction:
        self.session.add(action)
        self.session.flush()
        return action

    def get_for_user(self, action_id: int, user_id: int) -> PendingAction | None:
        return self.session.scalar(
            select(PendingAction).where(PendingAction.id == action_id, PendingAction.user_id == user_id)
        )

    def claim(self, action_id: int, user_id: int, now: datetime) -> bool:
        """Atomically move a live pending action to CONFIRMED. Exactly one concurrent caller wins:
        the conditional UPDATE runs under SQLite's write lock, so a second request sees the new
        status and matches zero rows."""
        result = self.session.execute(
            update(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.user_id == user_id,
                PendingAction.status == PendingActionStatus.PENDING,
                PendingAction.expires_at > now,
            )
            .values(status=PendingActionStatus.CONFIRMED, resolved_at=now)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def open_for_conversation(self, conversation_id: int) -> list[PendingAction]:
        return list(
            self.session.scalars(
                select(PendingAction).where(
                    PendingAction.conversation_id == conversation_id,
                    PendingAction.status == PendingActionStatus.PENDING,
                )
            ).all()
        )


class FeedbackRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_message(self, message_id: int) -> Feedback | None:
        return self.session.scalar(select(Feedback).where(Feedback.message_id == message_id))

    def add(self, feedback: Feedback) -> Feedback:
        self.session.add(feedback)
        self.session.flush()
        return feedback

    def get_message_for_user(self, message_id: int, user_id: int) -> Message | None:
        return self.session.scalar(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id, Conversation.user_id == user_id)
        )

    def find(
        self, *, rating: FeedbackRating | None, route: Route | None, limit: int, offset: int
    ) -> tuple[list[Feedback], int]:
        stmt = select(Feedback).join(Message, Message.id == Feedback.message_id)
        if rating:
            stmt = stmt.where(Feedback.rating == rating)
        if route:
            stmt = stmt.where(Message.route == route)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.options(selectinload(Feedback.message))
            .order_by(Feedback.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(rows), total

    def counts_by_tool(self) -> list[tuple[str, FeedbackRating, int]]:
        rows = self.session.execute(
            select(ToolInvocation.tool_name, Feedback.rating, func.count(func.distinct(Feedback.id)))
            .join(ToolInvocation, ToolInvocation.message_id == Feedback.message_id)
            .group_by(ToolInvocation.tool_name, Feedback.rating)
        ).all()
        return [(r[0], r[1], r[2]) for r in rows]

    def counts_by_route(self) -> list[tuple[Route | None, FeedbackRating, int]]:
        rows = self.session.execute(
            select(Message.route, Feedback.rating, func.count())
            .join(Message, Message.id == Feedback.message_id)
            .group_by(Message.route, Feedback.rating)
        ).all()
        return [(r[0], r[1], r[2]) for r in rows]
