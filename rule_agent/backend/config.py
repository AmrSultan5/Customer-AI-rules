"""
Central application configuration.

Consolidates the environment variables currently read ad-hoc across main.py,
explanation_engine.py, analytics.py, openai_client.py, and db.py, plus the new
multi-KB settings. THIS MODULE IS NOT YET WIRED IN — existing call sites keep
reading os.environ directly until a later phase migrates them. Importing this
module has no side effects (no directory creation, no client construction).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False
    )

    # Anthropic (explanation_engine.py)
    anthropic_api_key: str = ""
    anthropic_model_fast: str = "claude-haiku-4-5"
    anthropic_model_standard: str = "claude-sonnet-4-6"
    anthropic_model_deep: str = "claude-opus-4-8"

    # OpenAI (openai_client.py)
    openai_api_key: str = ""
    openai_title_model: str = "gpt-4o-mini"

    # Database (db.py)
    database_url: str = (
        f"sqlite+aiosqlite:///{(_BACKEND_DIR / 'data' / 'rule_agent.db').as_posix()}"
    )
    database_url_sync: str | None = None  # derived from database_url below if unset

    # Auth / admin (main.py)
    rule_agent_api_token: str = ""
    rule_agent_env: str = "production"
    rule_agent_admin_token: str | None = None  # falls back to rule_agent_api_token
    rule_agent_admin_user: str = "admin"
    rule_agent_admin_password: str = ""

    # CORS / message limits / rate limit (main.py)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_message_length: int = 2000
    max_persona_message_length: int = 12000
    chat_rate_limit: str = "30"

    # Cost estimation (analytics.py)
    rule_agent_prompt_cost_per_1m: float | None = None
    rule_agent_completion_cost_per_1m: float | None = None

    # Multi-KB engine (new)
    kb_dir: Path = _BACKEND_DIR / "kb"
    active_kb: str = "customer_sap"
    enable_kb_switcher: bool = True
    embeddings_model: str = "text-embedding-3-small"

    @model_validator(mode="after")
    def _derive_dependent_defaults(self) -> "Settings":
        if self.database_url_sync is None:
            self.database_url_sync = self.database_url.replace(
                "+asyncpg", "+psycopg"
            ).replace("+aiosqlite", "")
        if self.rule_agent_admin_token is None:
            self.rule_agent_admin_token = self.rule_agent_api_token
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
