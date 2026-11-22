from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_", env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str = Field(min_length=32)
    # "production" hides the interactive API docs, keeps message contents out of the log, and
    # sends HSTS (set https=true only when the API is reached over HTTPS, as through Caddy below).
    env: Literal["development", "production"] = "development"
    https: bool = False
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    invite_ttl_hours: int = 72
    reset_code_ttl_minutes: int = 15

    # Outgoing email. Without a host, messages are written to the server log (development only).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "FreightFlow <no-reply@freightflow.local>"

    # Optional language model for the chatbot. Without a key, the built-in rules answer.
    llm_api_key: str | None = None
    llm_model: str = "claude-haiku-5-5"

    @model_validator(mode="after")
    def _no_placeholder_secrets(self) -> "Settings":
        """Refuse to start in production with the example secret from .env.example."""
        if self.env == "production" and "change-me" in self.jwt_secret:
            raise ValueError("FF_JWT_SECRET is still the example value. Generate a real one (see .env.example).")
        return self

    @field_validator("smtp_host", "smtp_user", "smtp_password", "llm_api_key", mode="before")
    @classmethod
    def _blank_means_unset(cls, value: str | None) -> str | None:
        """Docker Compose passes an unset variable as an empty string."""
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
