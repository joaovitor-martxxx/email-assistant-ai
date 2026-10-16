"""Cada passo grava o id que criou; a retentativa não repete um passo já feito."""
import json
import sqlite3
from dataclasses import asdict

from eaa.alerting import Alerter
from eaa.db import Database
from eaa.metrics import Metrics
from eaa.models import Email, Extraction
from eaa.pipeline import Pipeline

EMAIL = Email("m1", "ana@example.test", "Contrato", "Assinar até sexta.", "")
WITH_DEADLINE = Extraction("resumo", True, deadline="2026-10-20T12:00:00+00:00")
NO_DEADLINE = Extraction("resumo", True)


class FakeGmail:
    def fetch_unread(self):
        return []


class CountingNotion:
    def __init__(self):
        self.calls = 0

    def create_task(self, email, extraction, priority):
        self.calls += 1
        return f"page-{self.calls}"


class FlakyCalendar:
    def __init__(self, failures):
        self.failures, self.calls = failures, 0

    def create_deadline_event(self, email, extraction):
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise RuntimeError("Calendar fora do ar")
        return f"event-{self.calls}" if extraction.deadline else None


def setup(tmp_path, extraction, calendar, notion=None):
    db = Database(str(tmp_path / "t.db"))
    payload = json.dumps({"email": asdict(EMAIL), "extraction": asdict(extraction)})
    db.enqueue(EMAIL.message_id, 50, payload)
    notion = notion or CountingNotion()
    pipeline = Pipeline(db, FakeGmail(), None, notion, calendar, Alerter(99), Metrics())
    return pipeline, db, notion


def test_retry_after_calendar_failure_does_not_create_another_notion_page(tmp_path):
    calendar = FlakyCalendar(failures=1)
    pipeline, db, notion = setup(tmp_path, WITH_DEADLINE, calendar)

    assert pipeline.process_queue() == 1

    assert notion.calls == 1
    assert calendar.calls == 2
    assert db.counts() == {"done": 1}


def test_ids_are_saved_on_the_task(tmp_path):
    pipeline, db, _ = setup(tmp_path, WITH_DEADLINE, FlakyCalendar(failures=0))
    pipeline.process_queue()
    with db.connect() as conn:
        row = conn.execute("SELECT notion_page_id, calendar_event_id FROM tasks").fetchone()
    assert (row["notion_page_id"], row["calendar_event_id"]) == ("page-1", "event-1")


def test_notion_id_survives_a_failed_attempt(tmp_path):
    pipeline, db, _ = setup(tmp_path, WITH_DEADLINE, FlakyCalendar(failures=99))
    pipeline.process_queue()  # esgota as tentativas
    with db.connect() as conn:
        row = conn.execute("SELECT status, notion_page_id, calendar_event_id FROM tasks").fetchone()
    assert (row["status"], row["notion_page_id"], row["calendar_event_id"]) == ("failed", "page-1", None)


def test_task_without_deadline_finishes_without_calendar_id(tmp_path):
    pipeline, db, notion = setup(tmp_path, NO_DEADLINE, FlakyCalendar(failures=0))
    assert pipeline.process_queue() == 1
    with db.connect() as conn:
        row = conn.execute("SELECT calendar_event_id FROM tasks").fetchone()
    assert row["calendar_event_id"] is None
    assert notion.calls == 1


def test_step_with_existing_id_is_skipped(tmp_path):
    calendar = FlakyCalendar(failures=0)
    pipeline, db, notion = setup(tmp_path, WITH_DEADLINE, calendar)
    with db.connect() as conn:
        conn.execute("UPDATE tasks SET notion_page_id='page-x', calendar_event_id='event-x'")
    assert pipeline.process_queue() == 1
    assert (notion.calls, calendar.calls) == (0, 0)


def test_existing_database_without_the_new_columns_is_migrated(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT NOT NULL UNIQUE, "
        "priority REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', "
        "attempts INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO tasks (message_id, priority, payload) VALUES ('antigo', 7, '{}')")
    conn.commit()
    conn.close()

    db = Database(path)
    Database(path)  # abrir de novo não falha nem duplica colunas

    task = db.next_task()
    assert task.message_id == "antigo"
    assert (task.notion_page_id, task.calendar_event_id) == (None, None)
    db.set_notion_page(task.id, "page-1")
    with db.connect() as c:
        assert c.execute("SELECT notion_page_id FROM tasks").fetchone()[0] == "page-1"
