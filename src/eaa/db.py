import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from .models import Task, TaskStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    priority REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    notion_page_id TEXT,
    calendar_event_id TEXT,
    done_reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS seen_hashes (
    content_hash TEXT PRIMARY KEY,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# Colunas acrescentadas depois da primeira versão do schema (ver Database._migrate)
ADDED_COLUMNS = ("notion_page_id", "calendar_event_id", "done_reason")


class Database:
    def __init__(self, path: str):
        self.path = path
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Bancos criados antes de uma coluna existir ganham a coluna, sem perder dados."""
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        for column in ADDED_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} TEXT")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def enqueue(self, message_id: str, priority: float, payload: str,
                content_hash: Optional[str] = None) -> bool:
        """Enfileira a tarefa. Se `content_hash` vier, ele é gravado na mesma
        transação: o e-mail só vira "visto" se a tarefa foi de fato criada."""
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO tasks (message_id, priority, payload) VALUES (?,?,?)",
                (message_id, priority, payload))
            if content_hash:
                conn.execute("INSERT OR IGNORE INTO seen_hashes (content_hash) VALUES (?)",
                             (content_hash,))
            return cur.rowcount > 0

    def enqueue_failed(self, message_id: str, payload: str, content_hash: str) -> bool:
        """Registra o e-mail já como `failed` (sem processamento futuro), junto com o
        hash do dedup, na mesma transação. Usado quando reprocessar não ajudaria."""
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO tasks (message_id, priority, status, payload) "
                "VALUES (?,?,?,?)", (message_id, 0, TaskStatus.FAILED.value, payload))
            conn.execute("INSERT OR IGNORE INTO seen_hashes (content_hash) VALUES (?)",
                         (content_hash,))
            return cur.rowcount > 0

    def next_task(self) -> Optional[Task]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE status='pending' "
                "ORDER BY priority DESC, id ASC LIMIT 1").fetchone()
            if not row:
                return None
            conn.execute("UPDATE tasks SET status='processing', "
                         "updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
            return Task(row["id"], row["message_id"], row["priority"],
                        TaskStatus.PROCESSING, row["attempts"], row["payload"],
                        row["notion_page_id"], row["calendar_event_id"])

    def set_notion_page(self, task_id: int, page_id: str) -> None:
        self._set_column(task_id, "notion_page_id", page_id)

    def set_calendar_event(self, task_id: int, event_id: str) -> None:
        self._set_column(task_id, "calendar_event_id", event_id)

    def _set_column(self, task_id: int, column: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(f"UPDATE tasks SET {column}=?, updated_at=CURRENT_TIMESTAMP "
                         "WHERE id=?", (value, task_id))

    def mark_done(self, task_id: int, reason: Optional[str] = None) -> None:
        """Conclui a tarefa. `reason` registra por que ela terminou sem o fluxo
        completo (ex.: skipped_category); fica NULL no caminho normal."""
        if reason:
            self._set_column(task_id, "done_reason", reason)
        self._set_status(task_id, TaskStatus.DONE)

    def mark_failed(self, task_id: int, requeue: bool) -> None:
        status = TaskStatus.PENDING if requeue else TaskStatus.FAILED
        with self.connect() as conn:
            conn.execute("UPDATE tasks SET status=?, attempts=attempts+1, "
                         "updated_at=CURRENT_TIMESTAMP WHERE id=?", (status.value, task_id))

    def _set_status(self, task_id: int, status: TaskStatus) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP "
                         "WHERE id=?", (status.value, task_id))

    def counts(self) -> dict:
        with self.connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) c FROM tasks GROUP BY status").fetchall()
            return {r["status"]: r["c"] for r in rows}

    def has_hash(self, content_hash: str) -> bool:
        with self.connect() as conn:
            return conn.execute("SELECT 1 FROM seen_hashes WHERE content_hash=?",
                                (content_hash,)).fetchone() is not None

    def purge_expired(self, done_days: int = 30, failed_days: int = 90,
                      now: Optional[datetime] = None) -> dict:
        """Remove tarefas antigas. Concluídas expiram em `done_days`; as que
        esgotaram as tentativas (status failed) ficam mais, `failed_days`, por
        serem as que pedem revisão manual. Pendentes e em processamento nunca
        expiram."""
        now = now or datetime.now(timezone.utc)
        fmt = "%Y-%m-%d %H:%M:%S"  # mesmo formato do CURRENT_TIMESTAMP do SQLite
        done_cutoff = (now - timedelta(days=done_days)).strftime(fmt)
        failed_cutoff = (now - timedelta(days=failed_days)).strftime(fmt)
        with self.connect() as conn:
            done = conn.execute("DELETE FROM tasks WHERE status=? AND updated_at < ?",
                                (TaskStatus.DONE.value, done_cutoff))
            failed = conn.execute("DELETE FROM tasks WHERE status=? AND updated_at < ?",
                                  (TaskStatus.FAILED.value, failed_cutoff))
            return {"done_removed": done.rowcount, "failed_removed": failed.rowcount}

    def reopen_stuck(self, minutes: int = 30, now: Optional[datetime] = None) -> int:
        """Devolve para `pending` tarefas em `processing` há mais de `minutes`:
        sinal de que a execução anterior morreu no meio. Não conta tentativa."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status=?, updated_at=? WHERE status=? AND updated_at < ?",
                (TaskStatus.PENDING.value, now.strftime("%Y-%m-%d %H:%M:%S"),
                 TaskStatus.PROCESSING.value, cutoff))
            return cur.rowcount
