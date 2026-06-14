"""
Central configuration – loaded once at startup.
All settings are read from environment variables (or .env file).
"""
from functools import lru_cache
from typing import Literal

from pydantic import AnyUrl, Field, PostgresDsn, RedisDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = "change-me"
    log_level: str = "INFO"
    debug: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://opsgraph:opsgraph_dev@localhost:5432/opsgraph"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_url: str = "redis://localhost:6379/1"

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_dev"
    use_neo4j: bool = False  # Falls back to postgres graph if False

    # ── LLM ──────────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    default_llm_provider: Literal["openai", "anthropic"] = "anthropic"
    default_model: str = "claude-sonnet-4-20250514"
    agent_temperature: float = 0.2
    agent_max_tokens: int = 4096

    # ── Security ─────────────────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # ── Slack ─────────────────────────────────────────────────────────────────
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_signing_secret: str = ""
    # Comma-separated channel IDs to scan for decision-worthy messages
    slack_decision_channel_ids: str = ""

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: str = ""
    github_org: str = ""

    # ── Jira ──────────────────────────────────────────────────────────────────
    jira_server: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    # Comma-separated project keys to scope JQL search; empty = all accessible projects
    jira_project_keys: str = ""

    # ── Google ────────────────────────────────────────────────────────────────
    google_service_account_json: str = ""
    google_drive_shared_drive_id: str = ""

    # ── Ingestion ─────────────────────────────────────────────────────────────
    ingestion_batch_size: int = 50
    ingestion_poll_interval_seconds: int = 60
    ingestion_workers: int = 4

    # ── Vector Store ──────────────────────────────────────────────────────────
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vector_similarity_threshold: float = 0.75
    vector_top_k: int = 10

    @property
    def slack_decision_channel_id_list(self) -> list[str]:
        return [c.strip() for c in self.slack_decision_channel_ids.split(",") if c.strip()]

    @property
    def jira_project_key_list(self) -> list[str]:
        return [k.strip() for k in self.jira_project_keys.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()


settings = get_settings()