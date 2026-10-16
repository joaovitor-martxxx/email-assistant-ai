from eaa.db import Database
from eaa.dedup import content_hash, is_new
from eaa.models import Email

def test_queue_orders_by_priority(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.enqueue("a", 10, "{}")
    db.enqueue("b", 90, "{}")
    assert db.next_task().message_id == "b"

def test_enqueue_is_idempotent(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    assert db.enqueue("a", 1, "{}") is True
    assert db.enqueue("a", 1, "{}") is False

def test_dedup_detects_same_content(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    e = Email("1", "x@y.com", "Oi", "corpo", "")
    assert is_new(db, e) is True
    db.enqueue("1", 1, "{}", content_hash(e))
    assert is_new(db, e) is False

def test_next_task_returns_none_when_queue_is_empty(tmp_path):
    assert Database(str(tmp_path / "t.db")).next_task() is None

def test_equal_priority_keeps_arrival_order(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.enqueue("primeiro", 50, "{}")
    db.enqueue("segundo", 50, "{}")
    assert db.next_task().message_id == "primeiro"

def test_next_task_marks_it_as_processing(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.enqueue("a", 10, "{}")
    db.enqueue("b", 20, "{}")
    db.next_task()
    db.next_task()
    assert db.counts() == {"processing": 2}
    assert db.next_task() is None

def test_done_task_does_not_return(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.enqueue("a", 10, "{}")
    task = db.next_task()
    db.mark_done(task.id)
    assert db.counts() == {"done": 1}
    assert db.next_task() is None

def test_failed_task_with_requeue_returns_and_counts_attempt(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.enqueue("a", 10, "{}")
    task = db.next_task()
    db.mark_failed(task.id, requeue=True)
    again = db.next_task()
    assert again.message_id == "a"
    assert again.attempts == 1

def test_exhausted_task_does_not_return(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.enqueue("a", 10, "{}")
    task = db.next_task()
    db.mark_failed(task.id, requeue=False)
    assert db.counts() == {"failed": 1}
    assert db.next_task() is None
