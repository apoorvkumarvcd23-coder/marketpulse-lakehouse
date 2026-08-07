"""Validated application settings loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ONLY_PASSWORDS = frozenset(
    {
        "change-this-local-password",
        "marketpulse_local_only",
    }
)


class Environment(StrEnum):
    """Named environments with different safety expectations."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Load and validate MarketPulse configuration without exposing secrets."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MARKETPULSE_",
        extra="ignore",
        validate_default=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    data_dir: Path = Path("data")

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = Field(default="marketpulse", min_length=1)
    postgres_user: str = Field(default="marketpulse", min_length=1)
    postgres_password: SecretStr = Field(min_length=12)

    @model_validator(mode="after")
    def reject_local_password_in_production(self) -> "Settings":
        """Stop a documented local-only password from reaching production."""
        password = self.postgres_password.get_secret_value()
        if self.environment is Environment.PRODUCTION and password in LOCAL_ONLY_PASSWORDS:
            raise ValueError("replace the local-only PostgreSQL password before production")
        return self

    def public_summary(self) -> dict[str, str | int]:
        """Return settings that are safe to print in logs or setup diagnostics."""
        return {
            "environment": self.environment.value,
            "log_level": self.log_level,
            "data_dir": str(self.data_dir),
            "postgres_host": self.postgres_host,
            "postgres_port": self.postgres_port,
            "postgres_db": self.postgres_db,
            "postgres_user": self.postgres_user,
            "postgres_password": str(self.postgres_password),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once so every pipeline component sees the same values."""
    return Settings()


__all__ = ["Environment", "Settings", "get_settings"]
