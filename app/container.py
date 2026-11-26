"""Composition root: builds long-lived objects once and per-request services on demand."""

import logging
from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.agent.llm.base import LLMProvider
from app.agent.llm.offline_provider import OfflineProvider
from app.agent.retriever import FTSRetriever
from app.agent.tools.base import ToolContext, ToolRegistry
from app.agent.tools.support_tools import default_registry
from app.backend.mock import MockAccountService, MockBillingService, MockTicketService
from app.core.config import Settings
from app.repositories.conversations import ConversationRepository, FeedbackRepository, PendingActionRepository
from app.repositories.kb import KBRepository
from app.services.actions import ActionService, DBActionGate
from app.services.chat import ChatService
from app.services.feedback import FeedbackService
from app.services.knowledge_base import KnowledgeBaseService

log = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Invalid startup configuration. Raised early so the app never starts half-configured."""


def build_providers(settings: Settings) -> tuple[LLMProvider, LLMProvider | None]:
    """Return (primary, fallback). Gemini is used when a key is configured, unless forced offline."""
    has_key = bool(settings.gemini_api_key and settings.gemini_api_key.get_secret_value())
    if settings.ai_provider == "gemini" and not has_key:
        raise ConfigurationError(
            "AI_PROVIDER=gemini but GEMINI_API_KEY is not set. "
            "Add it to .env (see .env.example), or use AI_PROVIDER=offline."
        )
    if settings.ai_provider == "offline" or not has_key:
        log.info("AI provider: offline rule-based (set GEMINI_API_KEY to use Gemini)")
        return OfflineProvider(), None

    from app.agent.llm.gemini_provider import GeminiProvider

    log.info("AI provider: gemini (%s)", settings.gemini_model)
    fallback = OfflineProvider() if settings.ai_degrade_to_offline else None
    return GeminiProvider(settings), fallback


@dataclass
class Container:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    primary: LLMProvider
    fallback: LLMProvider | None
    registry: ToolRegistry

    @classmethod
    def build(cls, settings: Settings, engine: Engine, session_factory: sessionmaker[Session], primary=None, fallback=None):
        if primary is None:
            primary, fallback = build_providers(settings)
        return cls(settings, engine, session_factory, primary, fallback, default_registry())

    # ---- per-request factories ----

    def tool_context(self, session: Session, user_id: int, conversation_id: int | None) -> ToolContext:
        s = self.settings
        return ToolContext(
            user_id=user_id,
            conversation_id=conversation_id,
            account=MockAccountService(session, s.password_reset_cooldown_minutes),
            billing=MockBillingService(session, s.max_payment_retries),
            tickets=MockTicketService(session),
            retriever=FTSRetriever(KBRepository(session), s.kb_min_relevance),
        )

    def chat_service(self, session: Session) -> ChatService:
        actions = PendingActionRepository(session)
        return ChatService(
            ConversationRepository(session),
            actions,
            self.registry,
            DBActionGate(actions, self.settings.pending_action_ttl_minutes),
            lambda uid, cid: self.tool_context(session, uid, cid),
            self.primary,
            self.fallback,
            max_tool_rounds=self.settings.agent_max_tool_rounds,
            history_messages=self.settings.agent_history_messages,
            commit=session.commit,
        )

    def action_service(self, session: Session) -> ActionService:
        return ActionService(
            PendingActionRepository(session),
            ConversationRepository(session),
            self.registry,
            lambda uid, cid: self.tool_context(session, uid, cid),
        )

    def kb_service(self, session: Session) -> KnowledgeBaseService:
        return KnowledgeBaseService(session)

    def feedback_service(self, session: Session) -> FeedbackService:
        return FeedbackService(FeedbackRepository(session))
