import re
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import KBArticle

_STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from how i if in is it me my of on or our "
    "please so that the this to was what when where which who why will with you your yours "
    "hi hello hey there thanks thank up set get got have has need want any about".split()
)


@dataclass(frozen=True)
class ScoredArticle:
    article: KBArticle
    score: float  # higher is more relevant


def build_fts_query(raw: str) -> str | None:
    """Turn free text into a safe FTS5 MATCH expression (OR of quoted terms).

    Quoting every term means user input can never inject FTS operators or cause syntax errors.
    """
    terms = [t for t in re.findall(r"[a-z0-9]+", raw.lower()) if t not in _STOPWORDS and len(t) > 1]
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))


class KBRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, article: KBArticle) -> KBArticle:
        self.session.add(article)
        self.session.flush()
        return article

    def get(self, article_id: int) -> KBArticle | None:
        return self.session.get(KBArticle, article_id)

    def find(
        self,
        *,
        category: str | None = None,
        published: bool | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KBArticle], int]:
        stmt = select(KBArticle)
        if category:
            stmt = stmt.where(KBArticle.category == category)
        if published is not None:
            stmt = stmt.where(KBArticle.is_published == published)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(KBArticle.title.ilike(like) | KBArticle.content.ilike(like))
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(stmt.order_by(KBArticle.id).limit(limit).offset(offset)).all()
        return list(rows), total

    def delete(self, article: KBArticle) -> None:
        self.session.delete(article)
        self.session.flush()

    def search(self, raw_query: str, *, limit: int = 3) -> list[ScoredArticle]:
        """BM25 full-text search over published articles. Title matches weigh most."""
        match = build_fts_query(raw_query)
        if match is None:
            return []
        rows = self.session.execute(
            text(
                """
                SELECT rowid, -bm25(kb_articles_fts, 5.0, 1.0, 2.0) AS score
                FROM kb_articles_fts
                WHERE kb_articles_fts MATCH :match
                ORDER BY score DESC
                LIMIT :limit
                """
            ),
            {"match": match, "limit": limit * 3},  # over-fetch, unpublished ones are filtered below
        ).all()
        results: list[ScoredArticle] = []
        for rowid, score in rows:
            article = self.session.get(KBArticle, rowid)
            if article is not None and article.is_published:
                results.append(ScoredArticle(article, float(score)))
            if len(results) == limit:
                break
        return results
