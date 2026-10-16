from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"

@dataclass
class Email:
    message_id: str
    sender: str
    subject: str
    body: str
    received_at: str

@dataclass
class Extraction:
    summary: str
    action_required: bool
    deadline: Optional[str] = None
    category: str = "geral"
    keywords: list[str] = field(default_factory=list)

@dataclass
class Task:
    id: int
    message_id: str
    priority: float
    status: TaskStatus
    attempts: int
    payload: str
    notion_page_id: Optional[str] = None
    calendar_event_id: Optional[str] = None
