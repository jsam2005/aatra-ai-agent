"""Database engine, session factory and schema bootstrap."""

from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone type; everything is stored as UTC)."""
    return datetime.now(UTC).replace(tzinfo=None)


def make_engine(url: str) -> Engine:
    # timeout: wait up to 15s for SQLite's single write lock instead of failing immediately.
    connect_args = {"check_same_thread": False, "timeout": 15} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# Full-text index over the knowledge base. External-content FTS5 table kept in sync by triggers,
# so writes go through the normal ORM and search stays consistent without application code.
_FTS_DDL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS kb_articles_fts USING fts5(
        title, content, tags,
        content='kb_articles', content_rowid='id',
        tokenize='porter unicode61'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS kb_articles_ai AFTER INSERT ON kb_articles BEGIN
        INSERT INTO kb_articles_fts(rowid, title, content, tags)
        VALUES (new.id, new.title, new.content, new.tags);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS kb_articles_ad AFTER DELETE ON kb_articles BEGIN
        INSERT INTO kb_articles_fts(kb_articles_fts, rowid, title, content, tags)
        VALUES ('delete', old.id, old.title, old.content, old.tags);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS kb_articles_au AFTER UPDATE ON kb_articles BEGIN
        INSERT INTO kb_articles_fts(kb_articles_fts, rowid, title, content, tags)
        VALUES ('delete', old.id, old.title, old.content, old.tags);
        INSERT INTO kb_articles_fts(rowid, title, content, tags)
        VALUES (new.id, new.title, new.content, new.tags);
    END
    """,
]


def init_db(engine: Engine) -> None:
    """Create tables (idempotent). A real deployment would use Alembic migrations instead."""
    from app import models  # noqa: F401  - registers ORM models on Base.metadata

    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            for ddl in _FTS_DDL:
                conn.execute(text(ddl))


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
