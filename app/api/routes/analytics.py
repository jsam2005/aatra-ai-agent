from fastapi import APIRouter

from app.api.deps import AdminDep, SessionDep
from app.db import utcnow
from app.repositories.analytics import AnalyticsRepository
from app.schemas.api import AnalyticsOverview, DayFeedback, RouteCount, ToolStats

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/overview", response_model=AnalyticsOverview, summary="Usage, tool operations and feedback trend (admin)", dependencies=[AdminDep])
def overview(session: SessionDep):
    repo = AnalyticsRepository(session)
    totals = repo.totals()
    avg = totals["avg_latency_ms"]
    return AnalyticsOverview(
        conversations=totals["conversations"],
        responses=totals["responses"],
        degraded_responses=totals["degraded_responses"],
        avg_latency_ms=round(avg) if avg is not None else None,
        responses_by_route=[RouteCount(route=r, count=c) for r, c in repo.responses_by_route()],
        tools=[ToolStats(**t) for t in repo.tool_stats()],
        feedback_by_day=[DayFeedback(**d) for d in repo.feedback_by_day(14, utcnow().date())],
    )
