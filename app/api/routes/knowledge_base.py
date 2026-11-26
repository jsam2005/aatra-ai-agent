from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AdminDep, ContainerDep, IsAdminDep, SessionDep
from app.core.errors import NotFoundError
from app.models import KBArticle
from app.schemas.api import KBArticleCreate, KBArticleOut, KBArticleUpdate, KBSearchHit, Page

router = APIRouter(prefix="/kb/articles", tags=["Knowledge base"])


def _out(a: KBArticle) -> KBArticleOut:
    return KBArticleOut(
        id=a.id,
        title=a.title,
        content=a.content,
        category=a.category,
        tags=a.tags.split() if a.tags else [],
        is_published=a.is_published,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@router.post("", response_model=KBArticleOut, status_code=status.HTTP_201_CREATED, summary="Create an article (admin)", dependencies=[AdminDep])
def create_article(body: KBArticleCreate, session: SessionDep, c: ContainerDep):
    return _out(c.kb_service(session).create(body))


@router.get("", response_model=Page[KBArticleOut], summary="List articles (drafts only with admin key)")
def list_articles(
    session: SessionDep,
    c: ContainerDep,
    admin: IsAdminDep,
    category: str | None = None,
    published: bool | None = None,
    q: Annotated[str | None, Query(description="Substring filter on title/content (admin listing).")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if not admin:
        published = True  # unpublished drafts are visible to admins only
    items, total = c.kb_service(session).find(category=category, published=published, query=q, limit=limit, offset=offset)
    return Page(items=[_out(a) for a in items], total=total, limit=limit, offset=offset)


@router.get("/search", response_model=list[KBSearchHit], summary="Relevance search (what the agent sees)")
def search_articles(
    session: SessionDep,
    c: ContainerDep,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
):
    return c.kb_service(session).search(q, limit)


@router.get("/{article_id}", response_model=KBArticleOut, summary="Get an article")
def get_article(article_id: int, session: SessionDep, c: ContainerDep, admin: IsAdminDep):
    article = c.kb_service(session).get(article_id)
    if not article.is_published and not admin:
        raise NotFoundError(f"Article {article_id} not found")
    return _out(article)


@router.patch("/{article_id}", response_model=KBArticleOut, summary="Update an article, partial (admin)", dependencies=[AdminDep])
def update_article(article_id: int, body: KBArticleUpdate, session: SessionDep, c: ContainerDep):
    return _out(c.kb_service(session).update(article_id, body))


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an article (admin)", dependencies=[AdminDep])
def delete_article(article_id: int, session: SessionDep, c: ContainerDep):
    c.kb_service(session).delete(article_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
