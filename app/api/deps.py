import secrets
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.container import Container
from app.core.errors import ForbiddenError, UnauthorizedError
from app.models import User


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_session(container: Annotated[Container, Depends(get_container)]) -> Iterator[Session]:
    """One transaction per request: committed on success, rolled back on any error."""
    session = container.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(
    session: Annotated[Session, Depends(get_session)],
    x_user_id: Annotated[int | None, Header(description="Mock authentication: the signed-in user's id.")] = None,
) -> User:
    """Mock auth. In production this would verify a session/JWT; the rest of the code only
    relies on getting a trusted user id from here, never from the request body or the model."""
    if x_user_id is None:
        raise UnauthorizedError("Missing X-User-Id header")
    user = session.get(User, x_user_id)
    if user is None:
        raise UnauthorizedError("Unknown user")
    return user


def is_admin(container: Container, x_admin_key: str | None) -> bool:
    expected = container.settings.admin_api_key.get_secret_value()
    return bool(x_admin_key) and secrets.compare_digest(x_admin_key.encode(), expected.encode())


def optional_admin(
    container: Annotated[Container, Depends(get_container)],
    x_admin_key: Annotated[str | None, Header(description="Demo admin key (knowledge-base writes, analytics).")] = None,
) -> bool:
    if x_admin_key is not None and not is_admin(container, x_admin_key):
        raise ForbiddenError("Invalid admin key")
    return x_admin_key is not None


def require_admin(is_admin_user: Annotated[bool, Depends(optional_admin)]) -> None:
    """Mock admin auth: a shared key stands in for an admin role in a real identity provider."""
    if not is_admin_user:
        raise UnauthorizedError("Missing X-Admin-Key header")


SessionDep = Annotated[Session, Depends(get_session)]
AdminDep = Depends(require_admin)
IsAdminDep = Annotated[bool, Depends(optional_admin)]
ContainerDep = Annotated[Container, Depends(get_container)]
UserDep = Annotated[User, Depends(get_current_user)]
