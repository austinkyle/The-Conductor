"""Typed application config, loaded from the environment.

Secrets (provider keys, datastore URLs) are required with no defaults so the app
fails loudly at startup rather than silently running misconfigured.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Secrets / connections — required, no defaults.
    openai_api_key: str
    anthropic_api_key: str
    database_url: str
    redis_url: str

    # Semantic cache — non-secret, overridable defaults. The embedding model is a
    # default, not a hardcoded contract; routing model strings live in the DB.
    embedding_model: str = "text-embedding-3-small"
    semantic_similarity_threshold: float = 0.92
    semantic_temperature_bypass: float = 0.3

    # App
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from env, not args
