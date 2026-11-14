from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_", env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str = Field(min_length=32)
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    invite_ttl_hours: int = 72


@lru_cache
def get_settings() -> Settings:
    return Settings()
