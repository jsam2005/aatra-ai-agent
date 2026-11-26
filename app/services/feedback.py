from app.core.errors import NotFoundError, ValidationFailed
from app.models import Feedback
from app.models.enums import FeedbackRating, MessageRole, Route
from app.repositories.conversations import FeedbackRepository
from app.schemas.api import FeedbackIn, FeedbackSummary, RouteFeedbackStats, ToolFeedbackStats


def _ratio(up: int, down: int) -> float | None:
    return round(up / (up + down), 3) if up + down else None


class FeedbackService:
    def __init__(self, repo: FeedbackRepository):
        self.repo = repo

    def submit(self, user_id: int, message_id: int, data: FeedbackIn) -> tuple[Feedback, bool]:
        """Create or replace the user's rating of an assistant message. Returns (feedback, created)."""
        message = self.repo.get_message_for_user(message_id, user_id)
        if message is None:
            raise NotFoundError(f"Message {message_id} not found")
        if message.role != MessageRole.ASSISTANT:
            raise ValidationFailed("Feedback can only be given on assistant messages")

        existing = self.repo.get_by_message(message_id)
        if existing:
            existing.rating = data.rating
            existing.comment = data.comment
            return existing, False
        return self.repo.add(Feedback(message_id=message_id, user_id=user_id, rating=data.rating, comment=data.comment)), True

    def get(self, user_id: int, message_id: int) -> Feedback:
        if self.repo.get_message_for_user(message_id, user_id) is None:
            raise NotFoundError(f"Message {message_id} not found")
        fb = self.repo.get_by_message(message_id)
        if fb is None:
            raise NotFoundError("No feedback for this message")
        return fb

    def find(self, *, rating: FeedbackRating | None, route: Route | None, limit: int, offset: int):
        return self.repo.find(rating=rating, route=route, limit=limit, offset=offset)

    def summary(self) -> FeedbackSummary:
        per_route: dict[Route | None, dict[str, int]] = {}
        for route, rating, count in self.repo.counts_by_route():
            per_route.setdefault(route, {"up": 0, "down": 0})[rating.value] += count
        by_route = [
            RouteFeedbackStats(route=r, up=c["up"], down=c["down"], satisfaction=_ratio(c["up"], c["down"]))
            for r, c in sorted(per_route.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))
        ]
        per_tool: dict[str, dict[str, int]] = {}
        for tool, rating, count in self.repo.counts_by_tool():
            per_tool.setdefault(tool, {"up": 0, "down": 0})[rating.value] += count
        by_tool = [
            ToolFeedbackStats(tool_name=t, up=c["up"], down=c["down"], satisfaction=_ratio(c["up"], c["down"]))
            for t, c in sorted(per_tool.items())
        ]
        up = sum(s.up for s in by_route)
        down = sum(s.down for s in by_route)
        return FeedbackSummary(
            total=up + down, up=up, down=down, satisfaction=_ratio(up, down), by_route=by_route, by_tool=by_tool
        )
