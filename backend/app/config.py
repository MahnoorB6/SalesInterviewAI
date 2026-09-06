from pydantic_settings import BaseSettings, SettingsConfigDict


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


    # ============================================================
    # CONFIGURATION
    # ============================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()