import argparse
import logging
from .alerting import Alerter
from .calendar_client import CalendarWriter
from .claude_client import ClaudeClient
from .config import get_settings
from .db import Database
from .gmail_client import GmailClient, load_credentials
from .logging_setup import setup_logging
from .metrics import Metrics, render_dashboard
from .notion_writer import NotionWriter
from .pipeline import Pipeline
from .rate_limiter import build_limiters

log = logging.getLogger(__name__)

def build_pipeline(settings, db, metrics) -> Pipeline:
    creds = load_credentials(settings.google_credentials_file, settings.google_token_file)
    limiters = build_limiters(settings)
    return Pipeline(
        db=db, gmail=GmailClient(creds, limiters["gmail"]),
        claude=ClaudeClient(settings.anthropic_api_key, settings.anthropic_model,
                            limiters["anthropic"]),
        notion=NotionWriter(settings.notion_token, settings.notion_database_id,
                            limiters["notion"]),
        calendar=CalendarWriter(creds, limiters["calendar"]),
        alerter=Alerter(settings.alert_failure_threshold), metrics=metrics)

def main() -> None:
    parser = argparse.ArgumentParser(prog="eaa")
    parser.add_argument("command", choices=["run-once", "metrics"])
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)
    db, metrics = Database(settings.db_path), Metrics()
    if args.command == "metrics":
        print(render_dashboard(metrics.snapshot(db)))
        return
    reopened = db.reopen_stuck(settings.stuck_task_minutes)
    if reopened:
        log.warning("%d tarefa(s) travada(s) reaberta(s)", reopened)
    removed = db.purge_expired(settings.task_ttl_done_days, settings.task_ttl_failed_days)
    log.info("limpeza por TTL: %s", removed)
    pipeline = build_pipeline(settings, db, metrics)
    pipeline.ingest()
    pipeline.process_queue()
    print(render_dashboard(metrics.snapshot(db)))

if __name__ == "__main__":
    main()
