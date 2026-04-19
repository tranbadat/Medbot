from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    TELEGRAM_TOKEN: str
    WEBHOOK_BASE_URL: str = ""

    # AI Engine: "anthropic" | "openai"
    AI_ENGINE: str = "anthropic"

    # Anthropic / Claude
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    DATABASE_URL: str = "postgresql+asyncpg://medbot:medbot123@postgres:5432/medbot"
    REDIS_URL: str = "redis://redis:6379/0"
    CHROMA_HOST: str = "chromadb"
    CHROMA_PORT: int = 8000
    JWT_SECRET: str = "change_this_secret"
    JWT_EXPIRE_HOURS: int = 24
    APP_ENV: str = "production"
    LOG_LEVEL: str = "INFO"

    # Clinic info (shown in Telegram menu)
    CLINIC_NAME: str = "Phòng khám Đa khoa MedBot"
    CLINIC_ADDRESS: str = "123 Đường ABC, Quận 1, TP.HCM"
    CLINIC_PHONE: str = "0901234567"
    CLINIC_HOURS: str = "Thứ 2 - Thứ 7: 8:00 - 17:00"
    CLINIC_EMAIL: str = "info@medbot.vn"

    # Admin
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # Session auto-close after inactivity (minutes); 0 = disabled
    SESSION_TIMEOUT_MINUTES: int = 30

    # Zalo OA (optional — leave empty to disable)
    ZALO_APP_ID: str = ""
    ZALO_APP_SECRET: str = ""
    ZALO_OA_ACCESS_TOKEN: str = ""
    ZALO_OA_REFRESH_TOKEN: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
