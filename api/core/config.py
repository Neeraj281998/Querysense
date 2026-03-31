from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-haiku-4-5"

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Rate limiting
    rate_limit_per_day: int = 5
    rate_limit_enabled: bool = True

    # App
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()