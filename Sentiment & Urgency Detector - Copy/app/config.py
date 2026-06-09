import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = "llama3-70b-8192"         
    GROQ_MODEL_FALLBACK: str = "llama3-8b-8192" 
    DB_PATH: str = "ticketsense.db"
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

    class Config:
        env_file = ".env"

settings = Settings()