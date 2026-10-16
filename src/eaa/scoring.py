from datetime import datetime, timezone
from typing import Optional
from .models import Email, Extraction

URGENT_WORDS = ("urgente", "prazo", "hoje", "amanhã", "asap", "vencimento")
VIP_SENDERS = ("chefe@", "diretoria@", "cliente@")

def priority_score(email: Email, extraction: Extraction,
                   now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    score = 0.0
    if extraction.action_required:
        score += 40
    text = f"{email.subject} {email.body}".lower()
    score += 10 * sum(1 for w in URGENT_WORDS if w in text)
    if any(email.sender.lower().startswith(v) for v in VIP_SENDERS):
        score += 20
    if extraction.deadline:
        try:
            dl = datetime.fromisoformat(extraction.deadline)
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=timezone.utc)
            days = (dl - now).total_seconds() / 86400
            if days <= 1:
                score += 30
            elif days <= 3:
                score += 15
        except ValueError:
            pass
    return min(score, 100.0)
