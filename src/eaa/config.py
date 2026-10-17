import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    notion_token: str = os.getenv("NOTION_TOKEN", "")
    notion_database_id: str = os.getenv("NOTION_DATABASE_ID", "")
    google_credentials_file: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    google_token_file: str = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    db_path: str = os.getenv("DB_PATH", "eaa.db")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    alert_failure_threshold: int = int(os.getenv("ALERT_FAILURE_THRESHOLD", "3"))
    anthropic_rps: float = float(os.getenv("ANTHROPIC_RPS", "0.8"))  # tier 1 = 50 req/min
    notion_rps: float = float(os.getenv("NOTION_RPS", "2.5"))  # limite oficial ~3 req/s
    gmail_rps: float = float(os.getenv("GMAIL_RPS", "5"))
    calendar_rps: float = float(os.getenv("CALENDAR_RPS", "5"))
    stuck_task_minutes: int = int(os.getenv("STUCK_TASK_MINUTES", "30"))
    task_ttl_done_days: int = int(os.getenv("TASK_TTL_DONE_DAYS", "30"))
    task_ttl_failed_days: int = int(os.getenv("TASK_TTL_FAILED_DAYS", "90"))

def get_settings() -> Settings:
    return Settings()
