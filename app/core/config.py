from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, Field, field_validator

# Resolve .env path relative to config.py location
ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

class Settings(BaseSettings):
    APP_NAME: str = "Devops Log Analyzer"   
    ENVIRONMENT: str = "dev"
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 20

    # ARIP settings
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""          # empty = no auth (local dev)
    LLAMA_CLOUD_API_KEY: str = ""
    # OPENAI_API_KEY: str = ""
    # LANGFUSE_SECRET_KEY: str = ""
    # LANGFUSE_PUBLIC_KEY: str = ""
    # COHERE_API_KEY: str = ""
    # ARIP_MAX_RETRIES: int = 5
    # ARIP_FAITHFULNESS_THRESHOLD: float = 0.7


    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def must_be_async_driver(cls, v: str) -> str:
        """Catch the most common junior mistake: using a sync driver URL."""
        if not v.startswith("postgresql+asyncpg"):
            raise ValueError(
                "DATABASE_URL must use the asyncpg driver. "
                "Change 'postgresql://' to 'postgresql+asyncpg://'"
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()