from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_", env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str = Field(min_length=32)
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

    @field_validator("smtp_host", "smtp_user", "smtp_password", "llm_api_key", mode="before")
    @classmethod
    def _blank_means_unset(cls, value: str | None) -> str | None:
        """Docker Compose passes an unset variable as an empty string."""
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
