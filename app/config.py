"""Application configuration loaded from environment variables and .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application settings
    APP_NAME: str = "KRAMA Onshape Engineering Connector"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Database settings (SQLite by default for local development & testing, PostgreSQL in production)
    DATABASE_URL: str = "sqlite:///./krama_connector.db"

    # Onshape API configuration
    ONSHAPE_BASE_URL: str = "https://cad.onshape.com"
    ONSHAPE_API_VERSION: str = "v10"
    ONSHAPE_ACCESS_KEY: str | None = None
    ONSHAPE_SECRET_KEY: str | None = None
    ONSHAPE_OAUTH_CLIENT_ID: str | None = None
    ONSHAPE_OAUTH_CLIENT_SECRET: str | None = None
    ONSHAPE_OAUTH_TOKEN: str | None = None

    # HTTP client settings
    HTTP_TIMEOUT_SECONDS: float = 30.0
    HTTP_MAX_RETRIES: int = 3
    HTTP_BACKOFF_FACTOR: float = 1.5

    # Change detection and sync settings
    POLL_INTERVAL_SECONDS: int = 300
    SYNC_BATCH_SIZE: int = 50

    # Test & Mock settings
    USE_MOCK_ONSHAPE: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
