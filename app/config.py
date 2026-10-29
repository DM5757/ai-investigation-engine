"""Central configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings. Only this module reads the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Investigation Engine"
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    database_url: str = Field(
        default="sqlite+pysqlite:///:memory:",
        alias="DATABASE_URL",
    )
    qdrant_url: str | None = Field(default=None, alias="QDRANT_URL")
    qdrant_api_key: SecretStr | None = Field(default=None, alias="QDRANT_API_KEY")

    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
    gemini_model: str = Field(default="gemini-3.5-flash-lite", alias="GEMINI_MODEL")

    admin_token: SecretStr | None = Field(default=None, alias="ADMIN_TOKEN")

    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        alias="EMBEDDING_MODEL",
    )
    # Candidate only until Phase 1 RSS benchmarks pass under Render 512 MB.
    embedding_enabled_at_startup: bool = Field(
        default=False,
        alias="EMBEDDING_ENABLED_AT_STARTUP",
    )
    enable_bench_endpoints: bool = Field(
        default=False,
        alias="ENABLE_BENCH_ENDPOINTS",
    )

    chunk_tokens: int = Field(default=200, alias="CHUNK_TOKENS")
    overlap_tokens: int = Field(default=40, alias="OVERLAP_TOKENS")


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()
