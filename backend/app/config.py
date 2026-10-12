from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):

    # ============================================================
    # DATABASE
    # ============================================================

    DATABASE_URL: str


    # ============================================================
    # ELEVENLABS
    # ============================================================

    ELEVENLABS_API_KEY: str
    ELEVENLABS_AGENT_ID: str


    # ============================================================
    # GOOGLE OAUTH
    # ============================================================

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    # Security and deployment URLs. JWT_SECRET_KEY is intentionally required.
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, gt=0, le=1440)
    FRONTEND_URL: str = "http://localhost:5173"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:5500,http://localhost:5500"
    COOKIE_SECURE: bool = True
    RECRUITER_EMAIL_ALLOWLIST: str = ""


    # ============================================================
    # CONFIGURATION
    # ============================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def recruiter_email_allowlist(self) -> set[str]:
        return {email.strip().lower() for email in self.RECRUITER_EMAIL_ALLOWLIST.split(",") if email.strip()}


settings = Settings()
