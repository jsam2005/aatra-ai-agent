from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ContainerDep, SessionDep, UserDep
from app.api.presenters import conversation_detail, message_out
from app.schemas.api import (
    ActionResolution,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationOut,
    Page,
    PendingActionOut,
    SendMessageRequest,
)
from app.services.chat import ChatResult

router = APIRouter(tags=["Chat"])


def _chat_response(session, result: ChatResult) -> ChatResponse:
    return ChatResponse(
        conversation_id=result.conversation.id,
        user_message=message_out(session, result.user_message),
        reply=message_out(session, result.reply),
        pending_actions=[PendingActionOut.model_validate(a) for a in result.pending_actions],
    )


@router.post("/chat", response_model=ChatResponse, summary="Send a message (creates a conversation if needed)")
def chat(body: ChatRequest, user: UserDep, session: SessionDep, c: ContainerDep):
    result = c.chat_service(session).send_message(user.id, body.message, body.conversation_id)
    return _chat_response(session, result)


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED, summary="Start a conversation")
def create_conversation(user: UserDep, session: SessionDep, c: ContainerDep):
    return ConversationOut.model_validate(c.chat_service(session).create_conversation(user.id))


@router.get("/conversations", response_model=Page[ConversationOut], summary="List my conversations")
def list_conversations(
    user: UserDep,
    session: SessionDep,
    c: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = c.chat_service(session).list_conversations(user.id, limit, offset)
    return Page(items=[ConversationOut.model_validate(i) for i in items], total=total, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail, summary="Conversation history")
def get_conversation(conversation_id: int, user: UserDep, session: SessionDep, c: ContainerDep):
    svc = c.chat_service(session)
    conv = svc.get_conversation(conversation_id, user.id)
    return conversation_detail(session, conv, svc.open_actions(conv.id))


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a conversation")
def delete_conversation(conversation_id: int, user: UserDep, session: SessionDep, c: ContainerDep):
    c.chat_service(session).delete_conversation(conversation_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatResponse,
    summary="Send a message in an existing conversation",
)
def send_message(conversation_id: int, body: SendMessageRequest, user: UserDep, session: SessionDep, c: ContainerDep):
    result = c.chat_service(session).send_message(user.id, body.message, conversation_id)
    return _chat_response(session, result)


# ---- pending actions (human-in-the-loop) ----


@router.get("/actions/{action_id}", response_model=PendingActionOut, tags=["Actions"], summary="Get a proposed action")
def get_action(action_id: int, user: UserDep, session: SessionDep, c: ContainerDep):
    return PendingActionOut.model_validate(c.action_service(session).get(action_id, user.id))


@router.post("/actions/{action_id}/confirm", response_model=ActionResolution, tags=["Actions"], summary="Confirm and execute")
def confirm_action(action_id: int, user: UserDep, session: SessionDep, c: ContainerDep):
    action, message = c.action_service(session).confirm(action_id, user.id)
    return ActionResolution(action=PendingActionOut.model_validate(action), message=message_out(session, message))


@router.post("/actions/{action_id}/cancel", response_model=ActionResolution, tags=["Actions"], summary="Cancel")
def cancel_action(action_id: int, user: UserDep, session: SessionDep, c: ContainerDep):
    action, message = c.action_service(session).cancel(action_id, user.id)
    return ActionResolution(action=PendingActionOut.model_validate(action), message=message_out(session, message))
