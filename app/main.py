import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.routes import analytics, chat, feedback, knowledge_base
from app.container import Container
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db import init_db, make_engine, make_session_factory

log = logging.getLogger("app")
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

API_DESCRIPTION = """
Aatra AI Agent: an AI customer-support agent, demonstrated for a fictional SaaS client
("Nimbus"). It answers from a knowledge base, reads account data, performs backend operations
(with confirmation for anything that moves money), keeps conversation history and collects feedback.

**Demo auth (not production-grade):** customer endpoints take `X-User-Id: <id>` (seeded users
1-4). Knowledge-base writes and analytics take `X-Admin-Key` (default `nimbus-admin-demo`, set
`ADMIN_API_KEY`).
"""


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}}})


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """App factory. Run with: uvicorn app.main:create_app --factory"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or get_settings()
    if container is None:
        engine = make_engine(settings.database_url)
        container = Container.build(settings, engine, make_session_factory(engine))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(container.engine)
        if settings.seed_on_startup:
            from scripts.seed import seed_if_empty

            with container.session_factory.begin() as session:
                if seed_if_empty(session):
                    log.info("Seeded demo data")
        log.info("Agent provider: %s (fallback: %s)", container.primary.name, container.fallback.name if container.fallback else "none")
        yield

    app = FastAPI(title=settings.app_name, version="1.0.0", description=API_DESCRIPTION, lifespan=lifespan)
    app.state.container = container

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_failed", "Request validation failed", {"errors": errors})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return _error(500, "internal_error", "Something went wrong on our side.")

    @app.get("/health", tags=["Health"], summary="Liveness and configuration")
    def health():
        with container.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "llm_provider": container.primary.name,
            "llm_model": getattr(container.primary, "model", None),
            "fallback_provider": container.fallback.name if container.fallback else None,
        }

    for router in (knowledge_base.router, chat.router, feedback.router, analytics.router):
        app.include_router(router, prefix="/api/v1")

    # Serve the built React app from the same origin (no CORS needed). Without a build,
    # "/" points to the API docs instead of returning 404.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:

        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse("/docs")

    return app


