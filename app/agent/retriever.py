"""Knowledge-base retrieval behind an interface, so BM25 can later be swapped for embeddings."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.repositories.kb import KBRepository


@dataclass(frozen=True)
class RetrievedDoc:
    id: int
    title: str
    category: str
    content: str
    score: float


class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, k: int = 3) -> list[RetrievedDoc]: ...


class FTSRetriever(Retriever):
    """SQLite FTS5 + BM25. Lexical, explainable, zero extra infrastructure."""

    MAX_CHARS = 1500  # keep tool results small; KB articles are short by design

    def __init__(self, repo: KBRepository, min_score: float = 0.0):
        self.repo = repo
        self.min_score = min_score

    def search(self, query: str, k: int = 3) -> list[RetrievedDoc]:
        return [
            RetrievedDoc(
                id=hit.article.id,
                title=hit.article.title,
                category=hit.article.category,
                content=hit.article.content[: self.MAX_CHARS],
                score=round(hit.score, 3),
            )
            for hit in self.repo.search(query, limit=k)
            if hit.score > self.min_score
        ]
