from datetime import datetime, timedelta, timezone

import pytest

from eaa.db import Database

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "ttl.db"))


def insert(db, message_id, status, days_ago):
    ts = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO tasks (message_id, status, payload, created_at, updated_at) "
            "VALUES (?,?,?,?,?)", (message_id, status, "{}", ts, ts))


def ids(db):
    with db.connect() as conn:
        return {r["message_id"] for r in conn.execute("SELECT message_id FROM tasks")}


def test_removes_expired_done_and_failed_and_keeps_recent(db):
    insert(db, "done_old", "done", 45)
    insert(db, "done_recent", "done", 5)
    insert(db, "failed_old", "failed", 100)
    insert(db, "failed_recent", "failed", 60)

    result = db.purge_expired(30, 90, now=NOW)

    assert result == {"done_removed": 1, "failed_removed": 1}
    assert ids(db) == {"done_recent", "failed_recent"}


def test_pending_and_processing_never_expire(db):
    insert(db, "pending_old", "pending", 200)
    insert(db, "processing_old", "processing", 200)

    result = db.purge_expired(30, 90, now=NOW)

    assert result == {"done_removed": 0, "failed_removed": 0}
    assert ids(db) == {"pending_old", "processing_old"}


def test_nothing_removed_when_all_within_ttl(db):
    insert(db, "done_new", "done", 1)
    insert(db, "failed_new", "failed", 1)
    assert db.purge_expired(30, 90, now=NOW) == {"done_removed": 0, "failed_removed": 0}


def test_distinct_ttls_for_done_and_failed(db):
    insert(db, "done_60", "done", 60)    # > 30d: expira
    insert(db, "failed_60", "failed", 60)  # < 90d: fica
    db.purge_expired(30, 90, now=NOW)
    assert ids(db) == {"failed_60"}


def test_ttl_zero_removes_everything_older_than_now(db):
    insert(db, "done_1s", "done", 0.00001)
    insert(db, "failed_1s", "failed", 0.00001)
    result = db.purge_expired(0, 0, now=NOW)
    assert result == {"done_removed": 1, "failed_removed": 1}


def test_defaults_are_30_and_90_days(db):
    insert(db, "done_31", "done", 31)
    insert(db, "failed_89", "failed", 89)
    insert(db, "failed_91", "failed", 91)
    db.purge_expired(now=NOW)
    assert ids(db) == {"failed_89"}
