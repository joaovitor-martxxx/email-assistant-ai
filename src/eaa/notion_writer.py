from notion_client import Client
from .models import Email, Extraction
from .rate_limiter import RateLimiter
from .retry import retry_notion

class NotionWriter:
    def __init__(self, token: str, database_id: str, limiter: RateLimiter | None = None):
        self.client = Client(auth=token)
        self.database_id = database_id
        self.limiter = limiter

    @retry_notion
    def create_task(self, email: Email, extraction: Extraction, priority: float) -> str:
        if self.limiter:
            self.limiter.acquire()
        page = self.client.pages.create(
            parent={"database_id": self.database_id},
            properties={
                "Name": {"title": [{"text": {"content": email.subject[:200] or "(sem assunto)"}}]},
                "Resumo": {"rich_text": [{"text": {"content": extraction.summary[:1900]}}]},
                "Prioridade": {"number": priority},
                "Categoria": {"select": {"name": extraction.category}},
            })
        return page["id"]
