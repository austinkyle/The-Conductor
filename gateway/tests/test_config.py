import pytest
from pydantic import ValidationError

from core.config import Settings

_REQUIRED = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL", "REDIS_URL"]


def test_missing_required_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _REQUIRED:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_loads_with_required_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-y")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.openai_api_key == "sk-x"
    assert settings.semantic_similarity_threshold == 0.95  # default applied


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-y")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


def test_production_without_dashboard_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("DASHBOARD_AUTH_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_production_with_dashboard_token_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "secret-token")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.dashboard_auth_token == "secret-token"


def test_development_without_dashboard_token_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("DASHBOARD_AUTH_TOKEN", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.environment == "development"
    assert settings.dashboard_auth_token is None
