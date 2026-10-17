"""Falha de um e-mail na ingestão não derruba os demais nem o marca como visto."""
import json

from eaa.alerting import Alerter
from eaa.claude_client import InvalidClaudeResponse
from eaa.db import Database
from eaa.dedup import content_hash
from eaa.metrics import Metrics
from eaa.models import Email, Extraction
from eaa.pipeline import Pipeline


class FakeGmail:
    def fetch_unread(self):
        return [Email("m1", "ana@example.test", "Primeiro", "Corpo do primeiro.", ""),
                Email("m2", "bia@example.test", "Segundo", "Corpo do segundo.", ""),
                Email("m3", "caio@example.test", "Terceiro", "Corpo do terceiro.", "")]


class FlakyClaude:
    def __init__(self, broken=()):
        self.broken, self.calls = set(broken), []

    def analyze(self, email):
        self.calls.append(email.message_id)
        if email.message_id in self.broken:
            raise RuntimeError("Claude fora do ar")
        return Extraction("resumo", True)


class OkNotion:
    def __init__(self):
        self.created = []

    def create_task(self, email, extraction, priority):
        self.created.append(email.message_id)
        return f"page-{email.message_id}"


class NoCalendar:
    def create_deadline_event(self, email, extraction):
        return None


def build(db, claude, notion):
    return Pipeline(db, FakeGmail(), claude, notion, NoCalendar(), Alerter(99), Metrics())


def test_failing_email_does_not_stop_the_others(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    pipeline = build(db, FlakyClaude(broken={"m2"}), OkNotion())
    assert pipeline.ingest() == 2
    assert db.counts() == {"pending": 2}
    assert pipeline.metrics.counters["ingest_failed"] == 1


def test_failed_email_is_logged_with_its_message_id(tmp_path, caplog):
    db = Database(str(tmp_path / "t.db"))
    build(db, FlakyClaude(broken={"m2"}), OkNotion()).ingest()
    record = next(r for r in caplog.records if r.getMessage() == "falha ao ingerir e-mail")
    assert record.message_id == "m2"


def test_failed_email_is_processed_on_the_next_run(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    notion = OkNotion()
    build(db, FlakyClaude(broken={"m2"}), notion).ingest()

    second = build(db, FlakyClaude(), notion)  # Claude voltou
    assert second.ingest() == 1  # só o m2; m1 e m3 já foram vistos
    assert second.metrics.counters["duplicates"] == 2
    second.process_queue()
    assert sorted(notion.created) == ["m1", "m2", "m3"]
    assert db.counts() == {"done": 3}


# --- resposta inválida da Claude (após as tentativas de formato) ---

class InvalidClaude:
    def __init__(self):
        self.calls = 0

    def analyze(self, email):
        self.calls += 1
        raise InvalidClaudeResponse("JSON inválido")


def test_invalid_response_is_stored_as_failed_with_the_hash(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    claude = InvalidClaude()
    pipeline = build(db, claude, OkNotion())
    assert pipeline.ingest() == 0
    assert db.counts() == {"failed": 3}
    assert pipeline.metrics.counters["ingest_invalid_response"] == 3
    with db.connect() as conn:
        payload = json.loads(conn.execute(
            "SELECT payload FROM tasks WHERE message_id='m1'").fetchone()["payload"])
    assert payload["email"]["message_id"] == "m1" and "JSON inválido" in payload["error"]


def test_invalid_response_email_is_not_reprocessed_nor_charged_again(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    first = InvalidClaude()
    build(db, first, OkNotion()).ingest()
    second = InvalidClaude()
    pipeline = build(db, second, OkNotion())
    assert pipeline.ingest() == 0
    assert second.calls == 0  # nenhuma chamada à API
    assert pipeline.metrics.counters["duplicates"] == 3
    assert pipeline.process_queue() == 0  # failed nunca vai para a fila


def test_other_errors_still_leave_no_hash(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    build(db, FlakyClaude(broken={"m2"}), OkNotion()).ingest()
    assert db.counts() == {"pending": 2}
    assert not db.has_hash(content_hash(FakeGmail().fetch_unread()[1]))
