import logging
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Configuration from init arguments, environment variables, then .env.

    Each field is read from the environment variable named in its alias.
    """

    model_config = SettingsConfigDict(
        env_file=".env",  # relative to the current working directory
        extra="ignore",  # .env may hold variables this tool does not use
        frozen=True,
        validate_by_name=True,  # allows Settings(host=...) in code and tests
        # Without this, the field name "user" also matches the shell's USER
        # variable, and "port" or "host" could match unrelated variables.
        case_sensitive=True,
    )

    host: str = Field(default="postgres", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, ge=1, le=65535, validation_alias="POSTGRES_PORT")
    dbname: str = Field(default="postgres", validation_alias="POSTGRES_DB")
    user: str = Field(default="postgres", validation_alias="POSTGRES_USER")
    password: SecretStr = Field(
        default=SecretStr("postgres"), validation_alias="POSTGRES_PASSWORD"
    )
    interval_seconds: int = Field(
        default=3600, ge=1, validation_alias="DATABASE_MANAGEMENT_INTERVAL_SECONDS"
    )
    targets: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(), validation_alias="DATABASE_MANAGEMENT_TARGETS"
    )
    staging_dir: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "postgres-backup",
        validation_alias="DATABASE_MANAGEMENT_STAGING_DIR",
    )
    # newest backups kept per database, per target
    keep: int = Field(default=7, ge=1, validation_alias="DATABASE_MANAGEMENT_KEEP")

    @field_validator("targets", mode="before")
    @classmethod
    def _split_targets(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(t for t in re.split(r"[\s,]+", value) if t)
        if isinstance(value, Iterable):
            return tuple(value)
        return value

    def log_summary(self, exclude: frozenset[str] = frozenset()) -> None:
        """Log every setting, one per line. Secrets print as asterisks."""
        logger.info("Configuration:")
        for name, value in self.model_dump().items():
            if name in exclude:
                continue
            if isinstance(value, tuple):
                value = ", ".join(value) if value else "(none)"
            logger.info(f"  {name:<16}  {value}")


def load_settings(**overrides: Any) -> Settings:
    """Build settings from env and .env (call from the directory holding .env).
    Keyword overrides, such as CLI flags, take precedence over both."""
    return Settings(**overrides)
