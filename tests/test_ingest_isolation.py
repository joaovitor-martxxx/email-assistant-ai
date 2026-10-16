"""Falha de um e-mail na ingestão não derruba os demais nem o marca como visto."""
from eaa.alerting import Alerter
from eaa.db import Database
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
