import json
import anthropic
from .models import Email, Extraction
from .rate_limiter import RateLimiter
from .retry import retry_anthropic

SYSTEM = (
    "Você analisa e-mails e responde SOMENTE com JSON válido, com as chaves: "
    "summary (str), action_required (bool), deadline (ISO 8601 ou null), "
    "category (str), keywords (lista de str)."
)

class ClaudeClient:
    def __init__(self, api_key: str, model: str, limiter: RateLimiter | None = None):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.limiter = limiter

    @retry_anthropic
    def analyze(self, email: Email) -> Extraction:
        if self.limiter:
            self.limiter.acquire()
        msg = self.client.messages.create(
            model=self.model, max_tokens=500, system=SYSTEM,
            messages=[{"role": "user",
                       "content": f"De: {email.sender}\nAssunto: {email.subject}\n\n{email.body[:4000]}"}])
        data = json.loads(msg.content[0].text)
        return Extraction(
            summary=data.get("summary", ""),
            action_required=bool(data.get("action_required", False)),
            deadline=data.get("deadline"),
            category=data.get("category", "geral"),
            keywords=list(data.get("keywords", [])))
