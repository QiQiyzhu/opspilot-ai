from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="OPSPILOT_", extra="ignore")
    database_url: str = "postgresql+psycopg://opspilot:opspilot@127.0.0.1:5433/opspilot"
    redis_url: str = "redis://127.0.0.1:6379/0"
    auth_tokens: str = ""
    model_cache: str = "model-cache"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    provider: str = "fake"
    provider_url: str = ""
    provider_key: str = ""
    provider_model: str = ""
    provider_timeout: float = 15.0
    retrieval_timeout: float = 15.0
    mcp_url: str = "http://127.0.0.1:8003/mcp"
    mcp_token: str = ""
    allow_faults: bool = False
    seed_on_start: bool = True
    cors_origins: str = "http://127.0.0.1:5176,http://localhost:5176"


@lru_cache
def settings():
    return Settings()
