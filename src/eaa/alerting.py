import logging
log = logging.getLogger(__name__)

class Alerter:
    def __init__(self, threshold: int):
        self.threshold = threshold
        self.consecutive_failures = 0

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self, reason: str) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.send(f"{self.consecutive_failures} falhas seguidas: {reason}")

    def send(self, message: str) -> None:
        # Troque por e-mail, Slack ou Telegram conforme a necessidade.
        log.error("ALERTA: %s", message)
