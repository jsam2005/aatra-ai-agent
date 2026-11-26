import pytest
from fastapi.testclient import TestClient

from app.agent.llm.base import LLMProvider, ModelTurn, ToolCall, TranscriptItem
from app.container import Container
from app.core.config import Settings
from app.db import init_db, make_engine, make_session_factory
from app.main import create_app
from scripts.seed import seed


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        ai_provider="offline",
        seed_on_startup=True,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def session_factory(settings):
    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory.begin() as s:
        seed(s)
    return factory


@pytest.fixture
def session(session_factory):
    s = session_factory()
    yield s
    s.rollback()
    s.close()


ADMIN = {"X-Admin-Key": "nimbus-admin-demo"}


def as_user(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


class ScriptedProvider(LLMProvider):
    """Returns pre-scripted turns, recording what it was shown. Lets tests drive the agent loop
    through situations a real model produces rarely (bad args, unknown tools, endless loops)."""

    name = "scripted"

    def __init__(self, turns: list[ModelTurn] | None = None, error: Exception | None = None):
        self.turns = list(turns or [])
        self.error = error
        self.calls: list[list[TranscriptItem]] = []

    def complete(self, system, transcript, tools) -> ModelTurn:
        self.calls.append(list(transcript))
        if self.error:
            raise self.error
        return self.turns.pop(0)


def tool_turn(*calls: tuple[str, dict]) -> ModelTurn:
    return ModelTurn("", [ToolCall(f"call_{i}", n, a) for i, (n, a) in enumerate(calls)], "tool_use", "scripted")


def text_turn(text: str) -> ModelTurn:
    return ModelTurn(text, [], "end_turn", "scripted")


@pytest.fixture
def make_container(settings, session_factory):
    def _make(primary: LLMProvider, fallback: LLMProvider | None = None) -> Container:
        engine = session_factory.kw["bind"]
        return Container.build(settings, engine, session_factory, primary=primary, fallback=fallback)

    return _make
