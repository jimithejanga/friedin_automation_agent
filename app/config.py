from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core Application
    APP_NAME: str = "CMR-Specialist-Automation"
    ENVIRONMENT: Literal["development", "staging", "production", "testing"] = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Security & Auth
    SECRET_KEY: str = "dev-secret-key-replace-in-production-change-me-32-chars-min"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day (1440 mins)
    ALGORITHM: str = "HS256"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/friedin_cmr"
    TEST_DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"
    DB_ECHO: bool = False
    EMBEDDING_DIM: int = 1536

    # Redis & Cache
    REDIS_URL: str = "redis://localhost:6379/0"

    # Storage (Local / S3)
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_DIR: str = "./data/storage"
    S3_BUCKET: str = "cmr-documents"
    S3_ENDPOINT_URL: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_REGION: str = "us-east-1"

    # AI / LLM Provider Configuration
    LLM_PROVIDER: Literal["mock", "openai", "gemini", "anthropic"] = "mock"
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    DEFAULT_LLM_MODEL: str = "gpt-4o-mini"
    DEFAULT_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Rate Limiting & Quotas
    RATE_LIMIT_PER_MINUTE: int = 60
    MAX_PROMPT_TOKENS: int = 4096
    MAX_RESPONSE_TOKENS: int = 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
