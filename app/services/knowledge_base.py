from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import KBArticle
from app.repositories.kb import KBRepository
from app.schemas.api import KBArticleCreate, KBArticleUpdate, KBSearchHit


def _tags_to_str(tags: list[str]) -> str:
    return " ".join(dict.fromkeys(t.strip().lower().replace(" ", "-") for t in tags if t.strip()))


class KnowledgeBaseService:
    def __init__(self, session: Session):
        self.repo = KBRepository(session)

    def create(self, data: KBArticleCreate) -> KBArticle:
        return self.repo.add(
            KBArticle(
                title=data.title.strip(),
                content=data.content.strip(),
                category=data.category.strip().lower(),
                tags=_tags_to_str(data.tags),
                is_published=data.is_published,
            )
        )

    def get(self, article_id: int) -> KBArticle:
        article = self.repo.get(article_id)
        if article is None:
            raise NotFoundError(f"Article {article_id} not found")
        return article

    def find(self, **filters) -> tuple[list[KBArticle], int]:
        return self.repo.find(**filters)

    def update(self, article_id: int, data: KBArticleUpdate) -> KBArticle:
        article = self.get(article_id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        if "tags" in changes:
            changes["tags"] = _tags_to_str(changes["tags"])
        if "category" in changes:
            changes["category"] = changes["category"].strip().lower()
        for key, value in changes.items():
            setattr(article, key, value)
        self.repo.session.flush()  # FTS index is updated by the AFTER UPDATE trigger
        return article

    def delete(self, article_id: int) -> None:
        self.repo.delete(self.get(article_id))

    def search(self, query: str, limit: int = 5) -> list[KBSearchHit]:
        return [
            KBSearchHit(
                id=h.article.id,
                title=h.article.title,
                category=h.article.category,
                score=round(h.score, 3),
                snippet=h.article.content[:200],
            )
            for h in self.repo.search(query, limit=limit)
        ]
