import pytest

from eaa.db import Database


def test_exception_inside_connect_rolls_back_the_write(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("INSERT INTO tasks (message_id, payload) VALUES ('a', '{}')")
            raise RuntimeError("falha no meio da escrita")
    assert db.counts() == {}


def test_reopening_an_existing_database_keeps_its_data(tmp_path):
    path = str(tmp_path / "t.db")
    Database(path).enqueue("a", 5, "{}")
    reopened = Database(path)  # o schema é criado com IF NOT EXISTS
    assert reopened.counts() == {"pending": 1}


def test_tasks_and_seen_hashes_coexist_in_the_same_database(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.enqueue("a", 5, "{}")
    assert db.has_hash("abc") is False
    db.enqueue("b", 5, "{}", content_hash="abc")
    assert db.has_hash("abc") is True
    assert db.counts() == {"pending": 2}


def test_task_and_hash_are_written_in_the_same_transaction(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    with pytest.raises(Exception):
        # o INSERT da tarefa passa; o do hash falha (valor não gravável) e desfaz os dois
        db.enqueue("a", 5, "{}", content_hash=object())
    assert db.counts() == {}
