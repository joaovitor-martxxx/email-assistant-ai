from datetime import datetime, timedelta, timezone

import pytest

from eaa.config import Settings
from eaa.db import Database

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "stuck.db"))


def insert(db, message_id, status, minutes_ago):
    ts = (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO tasks (message_id, status, payload, created_at, updated_at) "
            "VALUES (?,?,?,?,?)", (message_id, status, "{}", ts, ts))


def test_stuck_processing_task_is_reopened_and_can_be_taken_again(db):
    insert(db, "travada", "processing", 45)
    assert db.reopen_stuck(30, now=NOW) == 1
    assert db.next_task().message_id == "travada"


def test_recent_processing_task_is_left_alone(db):
    insert(db, "em_andamento", "processing", 5)
    assert db.reopen_stuck(30, now=NOW) == 0
    assert db.counts() == {"processing": 1}


def test_only_processing_tasks_are_reopened(db):
    insert(db, "done_old", "done", 500)
    insert(db, "failed_old", "failed", 500)
    insert(db, "pending_old", "pending", 500)
    assert db.reopen_stuck(30, now=NOW) == 0
    assert db.counts() == {"done": 1, "failed": 1, "pending": 1}


def test_reopening_does_not_count_as_an_attempt(db):
    insert(db, "travada", "processing", 45)
    db.reopen_stuck(30, now=NOW)
    assert db.next_task().attempts == 0


def test_limit_is_configurable(db):
    insert(db, "t", "processing", 10)
    assert db.reopen_stuck(30, now=NOW) == 0
    assert db.reopen_stuck(5, now=NOW) == 1


def test_default_limit_is_30_minutes(db):
    insert(db, "t29", "processing", 29)
    insert(db, "t31", "processing", 31)
    assert db.reopen_stuck(now=NOW) == 1
    assert Settings().stuck_task_minutes == 30
