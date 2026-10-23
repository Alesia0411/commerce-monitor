"""Settings contain deployment choices, not domain rules."""
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv('DATABASE_URL', 'sqlite:///./demo.db')
    redis_url: str = os.getenv('REDIS_URL', '')
    model: str = os.getenv('MODEL_NAME', '')
    api_key: str = os.getenv('MODEL_API_KEY', '')
    base_url: str = os.getenv('MODEL_BASE_URL', 'https://api.openai.com/v1')
    scheduler_seconds: int = int(os.getenv('SCHEDULER_SECONDS', '0'))
    token_a: str = os.getenv('DEMO_TOKEN_A', 'local-demo-a')
    token_b: str = os.getenv('DEMO_TOKEN_B', 'local-demo-b')

settings = Settings()
