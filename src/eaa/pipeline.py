import json
import logging
from dataclasses import asdict
from .alerting import Alerter
from .calendar_client import CalendarWriter
from .claude_client import ClaudeClient, InvalidClaudeResponse
from .db import Database
from .dedup import content_hash, is_new
from .gmail_client import GmailClient
from .metrics import Metrics
from .models import Email, Extraction
from .notion_writer import NotionWriter
from .scoring import priority_score
from .tracing import trace

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3

class Pipeline:
    def __init__(self, db: Database, gmail: GmailClient, claude: ClaudeClient,
                 notion: NotionWriter, calendar: CalendarWriter,
                 alerter: Alerter, metrics: Metrics):
        self.db, self.gmail, self.claude = db, gmail, claude
        self.notion, self.calendar = notion, calendar
        self.alerter, self.metrics = alerter, metrics

    def ingest(self) -> int:
        added = 0
        for email in self.gmail.fetch_unread():
            try:
                if not is_new(self.db, email):
                    self.metrics.incr("duplicates")
                    continue
                extraction = self.claude.analyze(email)
                score = priority_score(email, extraction)
                payload = json.dumps({"email": asdict(email), "extraction": asdict(extraction)})
                if self.db.enqueue(email.message_id, score, payload, content_hash(email)):
                    added += 1
                    self.metrics.incr("enqueued")
            except InvalidClaudeResponse as exc:
                # formato inválido persiste após as tentativas: guarda como failed COM hash,
                # para não reprocessar nem pagar a API de novo por este e-mail
                log.error("resposta inválida da Claude; e-mail registrado como failed",
                          extra={"message_id": email.message_id})
                payload = json.dumps({"email": asdict(email), "error": str(exc)})
                self.db.enqueue_failed(email.message_id, payload, content_hash(email))
                self.metrics.incr("ingest_invalid_response")
            except Exception:
                # sem tarefa e sem hash: o e-mail será tentado de novo na próxima execução
                log.exception("falha ao ingerir e-mail",
                              extra={"message_id": email.message_id})
                self.metrics.incr("ingest_failed")
        return added

    def process_queue(self) -> int:
        done = 0
        while (task := self.db.next_task()) is not None:
            with trace("process_task"):
                try:
                    data = json.loads(task.payload)
                    email = Email(**data["email"])
                    extraction = Extraction(**data["extraction"])
                    # cada passo grava o id que criou; na retentativa, passo com id é pulado
                    if not task.notion_page_id:
                        page_id = self.notion.create_task(email, extraction, task.priority)
                        self.db.set_notion_page(task.id, page_id)
                    if not task.calendar_event_id:
                        event_id = self.calendar.create_deadline_event(email, extraction)
                        if event_id:  # sem prazo não há evento e nada a gravar
                            self.db.set_calendar_event(task.id, event_id)
                    self.db.mark_done(task.id)
                    self.alerter.record_success()
                    self.metrics.incr("done")
                    done += 1
                except Exception as exc:
                    log.exception("falha na tarefa", extra={"task_id": task.id})
                    self.db.mark_failed(task.id, requeue=task.attempts + 1 < MAX_ATTEMPTS)
                    self.alerter.record_failure(str(exc))
                    self.metrics.incr("failed")
        return done
