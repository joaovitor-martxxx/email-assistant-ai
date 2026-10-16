from googleapiclient.discovery import build
from .models import Email, Extraction
from .rate_limiter import RateLimiter
from .retry import retry_google

class CalendarWriter:
    def __init__(self, creds, limiter: RateLimiter | None = None):
        self.service = build("calendar", "v3", credentials=creds)
        self.limiter = limiter

    @retry_google
    def create_deadline_event(self, email: Email, extraction: Extraction) -> str | None:
        if not extraction.deadline:
            return None
        if self.limiter:
            self.limiter.acquire()
        event = {
            "summary": f"Prazo: {email.subject[:100]}",
            "description": extraction.summary,
            "start": {"dateTime": extraction.deadline},
            "end": {"dateTime": extraction.deadline},
        }
        return self.service.events().insert(calendarId="primary", body=event).execute()["id"]
