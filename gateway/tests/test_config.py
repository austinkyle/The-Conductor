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
    assert settings.semantic_similarity_threshold == 0.92  # default applied
