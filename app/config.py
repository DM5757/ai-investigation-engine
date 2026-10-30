"""Central configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.url import normalize_database_url


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

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_database_url(value)
        return value
    qdrant_url: str | None = Field(default=None, alias="QDRANT_URL")
    qdrant_api_key: SecretStr | None = Field(default=None, alias="QDRANT_API_KEY")

    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
    groq_alt_model: str = Field(default="qwen/qwen3.8-27b", alias="GROQ_ALT_MODEL")
    gemini_model: str = Field(default="gemini-3.5-flash-lite", alias="GEMINI_MODEL")
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        alias="GROQ_BASE_URL",
    )
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        alias="GEMINI_BASE_URL",
    )

    # LLM / investigation (Phase 4)
    llm_timeout_s: float = Field(default=45.0, alias="LLM_TIMEOUT_S")
    # Bounded retries: honour Retry-After up to max_delay, then failover.
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    llm_retry_base_s: float = Field(default=0.5, alias="LLM_RETRY_BASE_S")
    llm_retry_max_s: float = Field(default=4.0, alias="LLM_RETRY_MAX_S")
    llm_budget_max_calls: int = Field(default=16, alias="LLM_BUDGET_MAX_CALLS")
    llm_budget_max_tokens: int = Field(default=50_000, alias="LLM_BUDGET_MAX_TOKENS")
    # Render Free cold start + embedding load + multi-step tools often exceeds 2 minutes.
    # Cap below typical client/proxy ~330s so we return llm_unavailable instead of hanging.
    llm_budget_wall_clock_s: float = Field(default=240.0, alias="LLM_BUDGET_WALL_CLOCK_S")
    max_tool_rounds: int = Field(default=4, alias="MAX_TOOL_ROUNDS")
    max_sub_questions: int = Field(default=4, alias="MAX_SUB_QUESTIONS")
    max_question_chars: int = Field(default=2000, alias="MAX_QUESTION_CHARS")
    tau_retrieval: float = Field(default=0.0, alias="TAU_RETRIEVAL")
    tau_relative: float = Field(
        default=0.35,
        alias="TAU_RELATIVE",
        description="Keep hits with score >= tau_relative * max_score in the retrieved pool.",
    )
    claim_min_support: float = Field(
        default=0.55,
        alias="CLAIM_MIN_SUPPORT",
        description="Minimum question-focus support for a claim to count as evidence.",
    )
    retrieval_top_k: int = Field(default=8, alias="RETRIEVAL_TOP_K")
    injection_downweight: float = Field(default=0.05, alias="INJECTION_DOWNWEIGHT")
    git_commit: str | None = Field(default=None, alias="GIT_COMMIT")

    admin_token: SecretStr | None = Field(default=None, alias="ADMIN_TOKEN")

    # API rate limits (Phase 5)
    query_rate_per_min: float = Field(default=30.0, alias="QUERY_RATE_PER_MIN")
    query_burst: float = Field(default=10.0, alias="QUERY_BURST")
    llm_daily_cap: int = Field(default=0, alias="LLM_DAILY_CAP")  # 0 = disabled

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
    chunk_strategy: str = Field(default="structure_aware", alias="CHUNK_STRATEGY")
    simhash_threshold: int = Field(default=3, alias="SIMHASH_THRESHOLD")
    near_duplicate_policy: str = Field(default="flag", alias="NEAR_DUPLICATE_POLICY")
    upload_max_bytes: int = Field(default=10_485_760, alias="UPLOAD_MAX_BYTES")
    qdrant_path: str | None = Field(default=None, alias="QDRANT_PATH")
    dense_vector_size: int = Field(default=384, alias="DENSE_VECTOR_SIZE")
    embedding_model_short: str = Field(default="bge-small", alias="EMBEDDING_MODEL_SHORT")

    # Retrieval / hybrid search (Phase 3)
    n_dense: int = Field(default=50, alias="N_DENSE")
    n_sparse: int = Field(default=50, alias="N_SPARSE")
    rrf_k: int = Field(default=60, alias="RRF_K")
    fusion_alpha: float = Field(default=0.5, alias="FUSION_ALPHA")
    bm25_k1: float = Field(default=1.2, alias="BM25_K1")
    bm25_b: float = Field(default=0.75, alias="BM25_B")
    bm25_avgdl: float = Field(default=100.0, alias="BM25_AVGDL")
    per_doc_cap: int = Field(default=3, alias="PER_DOC_CAP")
    rerank_w_fused: float = Field(default=0.40, alias="RERANK_W_FUSED")
    rerank_w_coverage: float = Field(default=0.20, alias="RERANK_W_COVERAGE")
    rerank_w_title: float = Field(default=0.15, alias="RERANK_W_TITLE")
    rerank_w_entity: float = Field(default=0.15, alias="RERANK_W_ENTITY")
    rerank_w_proximity: float = Field(default=0.10, alias="RERANK_W_PROXIMITY")
    rerank_mmr_lambda: float = Field(default=0.7, alias="RERANK_MMR_LAMBDA")


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()
