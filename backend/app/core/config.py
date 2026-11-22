import json
from typing import List, Union

from pydantic import Field, field_validator, model_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Job Sentry"
    ENVIRONMENT: str = Field(default="development")
    DEBUG: bool = True
    DOCS_ENABLED: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/job_sentry",
        description="Async PostgreSQL connection URL (asyncpg)",
    )
    REDIS_URL: str = "redis://localhost:6379/0"
    READY_REQUIRE_WORKER: bool = False
    GIT_COMMIT: str = "unknown"
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str | None = None

    # JWT Authentication
    JWT_SECRET: str = Field(
        default="replace-with-a-very-secure-random-secret-key-at-least-32-chars",
        description="Secret key for JWT token signing and verification",
    )

    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "job-sentry"
    JWT_AUDIENCE: str = "job-sentry-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Google OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # Optional import path in "package.module:factory" form for job requirement extraction.
    AI_REQUIREMENTS_PROVIDER: str = "app.ai_features.ai.requirements:build_provider"

    GOOGLE_API_KEY: SecretStr | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    OPENAI_API_KEY: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    # CORS
    ALLOWED_CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ]

    @model_validator(mode="after")
    def enforce_production_settings(self):
        if self.ENVIRONMENT.casefold() == "production":
            secret = self.JWT_SECRET.strip()
            if len(secret) < 32 or secret.casefold() in {
                "changeme",
                "change-me",
                "secret",
                "password",
                "replace-with-a-very-secure-random-secret-key-at-least-32-chars",
            }:
                raise ValueError(
                    "JWT_SECRET must be a non-placeholder value of at least 32 characters"
                )
            self.DEBUG = False
            self.DOCS_ENABLED = False
        return self

    @field_validator("ALLOWED_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Union[str, List[str]]) -> List[str]:
        if isinstance(value, str):
            # Support comma-separated string or JSON-like
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
