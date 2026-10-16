import hashlib
import re
from .db import Database
from .models import Email

def content_hash(email: Email) -> str:
    text = f"{email.sender.lower()}|{email.subject.lower()}|{email.body}"
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def is_new(db: Database, email: Email) -> bool:
    """Só consulta. O hash é gravado por `Database.enqueue(content_hash=...)`,
    junto com a tarefa, para que uma falha no meio não marque o e-mail como visto."""
    return not db.has_hash(content_hash(email))
