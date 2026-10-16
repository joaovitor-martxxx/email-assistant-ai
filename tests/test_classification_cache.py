"""A classificação é gravada no payload da fila no momento da ingestão, então
retentativas (Notion/Calendar fora do ar) nunca chamam a API do Claude de novo."""
from eaa.alerting import Alerter
from eaa.db import Database
from eaa.metrics import Metrics
from eaa.models import Email, Extraction
from eaa.pipeline import Pipeline


class FakeGmail:
    def fetch_unread(self):
        return [Email("m1", "ana@example.test", "Contrato", "Assinar até sexta.", "")]


class FakeClaude:
    def __init__(self):
        self.calls = 0

    def analyze(self, email):
        self.calls += 1
        return Extraction("Assinar contrato", True, deadline="2026-10-20T12:00:00+00:00",
                          category="contrato", keywords=["contrato"])


class FlakyNotion:
    def __init__(self, failures):
        self.failures, self.created = failures, []

    def create_task(self, email, extraction, priority):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("Notion fora do ar")
        self.created.append(extraction)
        return "page-1"


class FakeCalendar:
    def create_deadline_event(self, email, extraction):
        return None


def build(tmp_path, notion):
    claude = FakeClaude()
    pipeline = Pipeline(Database(str(tmp_path / "t.db")), FakeGmail(), claude, notion,
                        FakeCalendar(), Alerter(threshold=99), Metrics())
    return pipeline, claude


def test_retry_after_notion_failure_does_not_call_claude_again(tmp_path):
    notion = FlakyNotion(failures=2)
    pipeline, claude = build(tmp_path, notion)

    pipeline.ingest()
    # process_queue esvazia a fila: falha, volta para pending, falha, volta, e a 3ª dá certo
    assert pipeline.process_queue() == 1

    assert claude.calls == 1
    assert pipeline.db.counts() == {"done": 1}


def test_cached_classification_is_what_reaches_notion(tmp_path):
    notion = FlakyNotion(failures=1)
    pipeline, _ = build(tmp_path, notion)
    pipeline.ingest()
    pipeline.process_queue()
    assert notion.created == [Extraction("Assinar contrato", True,
                                         deadline="2026-10-20T12:00:00+00:00",
                                         category="contrato", keywords=["contrato"])]


def test_reingesting_same_email_does_not_classify_again(tmp_path):
    pipeline, claude = build(tmp_path, FlakyNotion(failures=0))
    pipeline.ingest()
    pipeline.ingest()
    assert claude.calls == 1
