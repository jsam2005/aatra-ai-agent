"""Application settings, loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Aatra AI Agent"
    database_url: str = "sqlite:///./support_agent.db"
    seed_on_startup: bool = True  # load demo data into an empty database on startup

    # --- AI provider ---
    # "auto": Gemini when GEMINI_API_KEY is set, otherwise the offline rule-based provider.
    ai_provider: Literal["auto", "gemini", "offline"] = "auto"
    gemini_api_key: SecretStr | None = None  # read from env/.env only; never logged or returned
    # Verified with this project's free-tier key: 3.8-flash and 3.6-flash returned 503 "high demand",
    # 3.7-flash allows 20 requests/day. Override with GEMINI_MODEL.
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_max_output_tokens: int = 1024
    gemini_timeout_seconds: float = 30.0
    gemini_max_retries: int = 2  # SDK-level retries for 429/5xx, with exponential backoff
    # Optional Gemini 3 thinking level ("minimal" | "low" | "medium" | "high"); unset = model default.
    gemini_thinking_level: str | None = None
    # If Gemini fails mid-turn, finish the turn with the offline provider instead of returning 503.
    ai_degrade_to_offline: bool = True

    # --- Demo auth ---
    # Knowledge-base writes and feedback analytics require X-Admin-Key. Demo value; change it in .env.
    admin_api_key: SecretStr = SecretStr("nimbus-admin-demo")

    # --- Agent behaviour ---
    agent_max_tool_rounds: int = 5
    agent_history_messages: int = 20  # prior messages replayed to the model each turn
    kb_min_relevance: float = 1.0  # BM25 hits scoring at or below this are treated as noise
    pending_action_ttl_minutes: int = 15
    password_reset_cooldown_minutes: int = 10
    max_payment_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
