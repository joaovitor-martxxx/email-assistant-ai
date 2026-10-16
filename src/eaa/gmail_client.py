import base64
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from .models import Email
from .rate_limiter import RateLimiter
from .retry import retry_google

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/calendar.events"]

def load_credentials(credentials_file: str, token_file: str) -> Credentials:
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    except (FileNotFoundError, ValueError):
        pass
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return creds

class GmailClient:
    def __init__(self, creds: Credentials, limiter: RateLimiter | None = None):
        self.service = build("gmail", "v1", credentials=creds)
        self.limiter = limiter

    @retry_google
    def fetch_unread(self, max_results: int = 20) -> list[Email]:
        if self.limiter:
            self.limiter.acquire()
        resp = self.service.users().messages().list(
            userId="me", q="is:unread", maxResults=max_results).execute()
        return [self._get(m["id"]) for m in resp.get("messages", [])]

    def _get(self, message_id: str) -> Email:
        if self.limiter:
            self.limiter.acquire()
        msg = self.service.users().messages().get(
            userId="me", id=message_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        return Email(message_id=message_id,
                     sender=headers.get("from", ""),
                     subject=headers.get("subject", ""),
                     body=self._extract_body(msg["payload"]),
                     received_at=headers.get("date", ""))

    def _extract_body(self, payload: dict) -> str:
        if payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text
        return ""
