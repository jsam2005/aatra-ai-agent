from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AdminDep, ContainerDep, SessionDep, UserDep
from app.models.enums import FeedbackRating, Route
from app.schemas.api import FeedbackIn, FeedbackOut, FeedbackSummary, FeedbackWithContext, Page

router = APIRouter(tags=["Feedback"])


@router.put(
    "/messages/{message_id}/feedback",
    response_model=FeedbackOut,
    summary="Rate an assistant message (create or replace)",
    responses={201: {"description": "Created"}, 200: {"description": "Replaced"}},
)
def put_feedback(message_id: int, body: FeedbackIn, user: UserDep, session: SessionDep, c: ContainerDep, response: Response):
    fb, created = c.feedback_service(session).submit(user.id, message_id, body)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return FeedbackOut.model_validate(fb)


@router.get("/messages/{message_id}/feedback", response_model=FeedbackOut, summary="Get my rating of a message")
def get_feedback(message_id: int, user: UserDep, session: SessionDep, c: ContainerDep):
    return FeedbackOut.model_validate(c.feedback_service(session).get(user.id, message_id))


@router.get("/feedback", response_model=Page[FeedbackWithContext], summary="List feedback (admin)", dependencies=[AdminDep])
def list_feedback(
    session: SessionDep,
    c: ContainerDep,
    rating: FeedbackRating | None = None,
    route: Route | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = c.feedback_service(session).find(rating=rating, route=route, limit=limit, offset=offset)
    out = [
        FeedbackWithContext(
            **FeedbackOut.model_validate(f).model_dump(),
            route=f.message.route,
            message_excerpt=f.message.content[:200],
        )
        for f in items
    ]
    return Page(items=out, total=total, limit=limit, offset=offset)


@router.get("/feedback/summary", response_model=FeedbackSummary, summary="Satisfaction overall, per route and per tool (admin)", dependencies=[AdminDep])
def feedback_summary(session: SessionDep, c: ContainerDep):
    return c.feedback_service(session).summary()
