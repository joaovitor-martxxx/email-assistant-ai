"""promocao e irrelevante terminam como done, sem Notion nem Calendar."""
import json
import logging
from dataclasses import asdict

import pytest

from eaa.alerting import Alerter
from eaa.db import Database
from eaa.metrics import Metrics
from eaa.models import Email, Extraction
from eaa.pipeline import Pipeline

EMAIL = Email("m1", "loja@example.test", "Assunto", "Corpo.", "")


class FakeGmail:
    def fetch_unread(self):
        return []


class FakeNotion:
    def __init__(self):
        self.calls = 0

    def create_task(self, email, extraction, priority):
        self.calls += 1
        return "page-1"


class FakeCalendar:
    def __init__(self):
        self.calls = 0

    def create_deadline_event(self, email, extraction):
        self.calls += 1
        return "event-1"


def run(tmp_path, category, deadline=None):
    db = Database(str(tmp_path / "t.db"))
    extraction = Extraction("resumo", False, deadline=deadline, category=category)
    payload = json.dumps({"email": asdict(EMAIL), "extraction": asdict(extraction)})
    db.enqueue(EMAIL.message_id, 10, payload)
    notion, calendar = FakeNotion(), FakeCalendar()
    pipeline = Pipeline(db, FakeGmail(), None, notion, calendar, Alerter(99), Metrics())
    return pipeline, db, notion, calendar


@pytest.mark.parametrize("category", ["promocao", "irrelevante"])
def test_skipped_category_does_not_call_notion_or_calendar(tmp_path, category):
    pipeline, db, notion, calendar = run(tmp_path, category, deadline="2026-10-20T12:00:00-03:00")
    assert pipeline.process_queue() == 1
    assert (notion.calls, calendar.calls) == (0, 0)
    assert db.counts() == {"done": 1}


@pytest.mark.parametrize("category", ["promocao", "irrelevante"])
def test_skipped_task_records_the_reason_and_no_ids(tmp_path, category):
    pipeline, db, _, _ = run(tmp_path, category)
    pipeline.process_queue()
    with db.connect() as conn:
        row = conn.execute("SELECT done_reason, notion_page_id, calendar_event_id FROM tasks").fetchone()
    assert (row["done_reason"], row["notion_page_id"], row["calendar_event_id"]) == (
        "skipped_category", None, None)
    assert pipeline.metrics.counters["skipped"] == 1


def test_skip_is_logged_at_info_level(tmp_path, caplog):
    pipeline, _, _, _ = run(tmp_path, "promocao")
    with caplog.at_level(logging.INFO, logger="eaa.pipeline"):
        pipeline.process_queue()
    record = next(r for r in caplog.records if "tarefa pulada" in r.getMessage())
    assert record.levelno == logging.INFO
    assert "promocao" in record.getMessage()


def test_prazo_entrega_calls_notion_and_calendar(tmp_path):
    pipeline, db, notion, calendar = run(tmp_path, "prazo_entrega", deadline="2026-10-20T12:00:00-03:00")
    assert pipeline.process_queue() == 1
    assert (notion.calls, calendar.calls) == (1, 1)
    with db.connect() as conn:
        assert conn.execute("SELECT done_reason FROM tasks").fetchone()[0] is None


@pytest.mark.parametrize("category", ["reuniao", "acao_requerida", "informativo"])
def test_other_categories_still_reach_notion(tmp_path, category):
    pipeline, _, notion, _ = run(tmp_path, category)
    pipeline.process_queue()
    assert notion.calls == 1


# --- banco antigo sem a coluna done_reason ---

OLD_COLUMNS = ("id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT NOT NULL UNIQUE, "
               "priority REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', "
               "attempts INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL, ")
TIMESTAMPS = "created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP"


@pytest.mark.parametrize("extra_columns", [
    "",  # primeira versão do schema
    "notion_page_id TEXT, calendar_event_id TEXT, ",  # versão anterior a done_reason
])
def test_old_database_without_done_reason_is_migrated_and_readable(tmp_path, extra_columns):
    import sqlite3
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE tasks ({OLD_COLUMNS}{extra_columns}{TIMESTAMPS})")
    conn.execute("INSERT INTO tasks (message_id, priority, status, payload) "
                 "VALUES ('antigo-done', 1, 'done', '{}')")
    conn.execute("INSERT INTO tasks (message_id, priority, payload) VALUES ('antigo-pending', 9, '{}')")
    conn.commit()
    conn.close()

    db = Database(path)
    Database(path)  # abrir de novo não falha nem duplica colunas

    with db.connect() as c:
        columns = {r["name"] for r in c.execute("PRAGMA table_info(tasks)")}
        old_done = c.execute("SELECT status, done_reason FROM tasks "
                             "WHERE message_id='antigo-done'").fetchone()
    assert {"notion_page_id", "calendar_event_id", "done_reason"} <= columns
    assert (old_done["status"], old_done["done_reason"]) == ("done", None)

    task = db.next_task()
    assert task.message_id == "antigo-pending"
    db.mark_done(task.id, reason="skipped_category")
    with db.connect() as c:
        row = c.execute("SELECT status, done_reason FROM tasks WHERE id=?", (task.id,)).fetchone()
    assert (row["status"], row["done_reason"]) == ("done", "skipped_category")
