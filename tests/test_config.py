"""Tests for environment-based application configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from marketpulse.config import Environment, Settings


def write_env_file(path: Path, *, password: str = "dotenv-test-password") -> None:
    """Create a temporary dotenv file used only by an isolated test."""
    path.write_text(
        "\n".join(
            (
                "MARKETPULSE_ENVIRONMENT=test",
                "MARKETPULSE_LOG_LEVEL=WARNING",
                "MARKETPULSE_POSTGRES_HOST=postgres",
                "MARKETPULSE_POSTGRES_PORT=5544",
                f"MARKETPULSE_POSTGRES_PASSWORD={password}",
            )
        ),
        encoding="utf-8",
    )


def test_settings_load_and_validate_dotenv_values(tmp_path: Path) -> None:
    """A local dotenv file should populate strongly typed settings."""
    env_file = tmp_path / ".env"
    write_env_file(env_file)

    settings = Settings(_env_file=env_file)

    assert settings.environment is Environment.TEST
    assert settings.log_level == "WARNING"
    assert settings.postgres_host == "postgres"
    assert settings.postgres_port == 5544
    assert settings.postgres_password.get_secret_value() == "dotenv-test-password"


def test_environment_variable_overrides_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A runtime environment variable should take priority over the dotenv file."""
    env_file = tmp_path / ".env"
    write_env_file(env_file)
    monkeypatch.setenv("MARKETPULSE_POSTGRES_PORT", "6432")

    settings = Settings(_env_file=env_file)

    assert settings.postgres_port == 6432


def test_password_is_required_and_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuration must fail closed and never print the database password."""
    monkeypatch.delenv("MARKETPULSE_POSTGRES_PASSWORD", raising=False)

    with pytest.raises(ValidationError, match="postgres_password"):
        Settings(_env_file=None)

    password = "a-very-private-test-password"
    settings = Settings(_env_file=None, postgres_password=password)

    assert password not in repr(settings)
    assert password not in str(settings.public_summary())
    assert settings.public_summary()["postgres_password"] == "**********"


def test_local_example_password_is_rejected_in_production() -> None:
    """The documented local password must never be accepted as production-ready."""
    with pytest.raises(ValidationError, match="local-only PostgreSQL password"):
        Settings(
            _env_file=None,
            environment="production",
            postgres_password="change-this-local-password",
        )


@pytest.mark.parametrize("port", [0, 65536, "not-a-number"])
def test_invalid_postgres_port_is_rejected(port: int | str) -> None:
    """Invalid ports should fail during startup instead of later at connection time."""
    with pytest.raises(ValidationError, match="postgres_port"):
        Settings(_env_file=None, postgres_password="valid-test-password", postgres_port=port)
