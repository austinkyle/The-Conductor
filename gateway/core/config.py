"""Typed application config, loaded from the environment.

Secrets (provider keys, datastore URLs) are required with no defaults so the app
fails loudly at startup rather than silently running misconfigured.
"""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
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

    # Exact cache — TTL for Redis entries (seconds).
    exact_cache_ttl_seconds: int = 3600

    # Semantic cache — non-secret, overridable defaults. The embedding model is a
    # default, not a hardcoded contract; routing model strings live in the DB.
    embedding_model: str = "text-embedding-3-small"
    embedding_api_base: str = "https://api.openai.com/v1"
    # Measured via bench/cache_bench.py --mode=similarity; see
    # bench/reports/bench-20260713-similarity-threshold.md. 0.95 is the safest
    # single-threshold setting found, not a threshold that meets the <=1%
    # false-positive target — see that report's Root Cause section.
    semantic_similarity_threshold: float = 0.95
    semantic_temperature_bypass: float = 0.3
    # Minimum characters in embed_text output to bother calling the embedding API.
    semantic_cache_min_chars: int = 1

    # Failover backoff — non-secret, overridable defaults.
    fallback_backoff_base_ms: int = 500
    fallback_backoff_factor: float = 1.8
    fallback_backoff_max_ms: int = 30_000

    # App
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000

    # Deployment mode. Gates whether dashboard_auth_token is required.
    environment: Literal["development", "production"] = "development"
    # Static bearer token required on /v1/observability/* reads. Required in
    # production (see validator below); optional in development, where an
    # unset token just logs a startup warning instead of failing.
    dashboard_auth_token: str | None = None

    @model_validator(mode="after")
    def _require_dashboard_token_in_production(self) -> "Settings":
        if self.environment == "production" and self.dashboard_auth_token is None:
            raise ValueError(
                "DASHBOARD_AUTH_TOKEN is required when ENVIRONMENT=production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from env, not args
