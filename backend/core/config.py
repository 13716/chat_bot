import os
from dotenv import load_dotenv

# Load trước khi làm gì khác
load_dotenv(dotenv_path=r"D:\python\VSF\backend\.env", override=True)

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    APP_NAME: str = "AI Chatbot API"
    DEBUG: bool = False

    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    LLM_FALLBACK_ORDER: list[str] = ["groq", "gemini", "openai", "anthropic"]

    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")


def get_settings() -> Settings:
    return Settings()