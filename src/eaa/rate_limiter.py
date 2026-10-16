"""Rate limiter proativo (token bucket), um por API externa.

O retry (retry.py) é reativo: só age depois que a API devolveu 429/5xx. Este
módulo espaça as chamadas antes de enviá-las, para que o 429 seja exceção.

Cada balde enche na taxa configurada até `capacity` tokens; cada chamada
consome um. Com o balde vazio, `acquire()` espera até haver token, o que
permite rajadas curtas sem violar a média sustentada.
"""
import logging
import threading
import time
from typing import Callable

from .config import Settings

log = logging.getLogger(__name__)

LOG_THRESHOLD_SECONDS = 0.05  # esperas menores que isso não geram log
EPSILON = 1e-9


class RateLimiter:
    def __init__(self, rate_per_second: float, capacity: int | None = None,
                 name: str = "default",
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if rate_per_second <= 0:
            raise ValueError("rate_per_second deve ser maior que zero")
        self.rate = rate_per_second
        self.capacity = capacity if capacity is not None else max(1, round(rate_per_second))
        self.name = name
        self._clock, self._sleep = clock, sleep
        self._tokens = float(self.capacity)
        self._last = clock()
        self._lock = threading.Lock()

    def acquire(self, cost: float = 1) -> None:
        """Bloqueia até existir `cost` token(s), consome e retorna. Chame
        imediatamente antes de cada chamada real à API."""
        while True:
            with self._lock:
                now = self._clock()
                self._tokens = min(self.capacity,
                                   self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= cost - EPSILON:  # tolera erro de ponto flutuante
                    self._tokens = max(0.0, self._tokens - cost)
                    return
                wait = (cost - self._tokens) / self.rate
            if wait > LOG_THRESHOLD_SECONDS:
                log.debug("rate limit (%s): aguardando %.2fs", self.name, wait)
            self._sleep(wait)  # fora do lock, para não travar outras threads


def build_limiters(settings: Settings) -> dict[str, RateLimiter]:
    return {
        "anthropic": RateLimiter(settings.anthropic_rps, name="anthropic"),
        "notion": RateLimiter(settings.notion_rps, name="notion"),
        "gmail": RateLimiter(settings.gmail_rps, name="gmail"),
        "calendar": RateLimiter(settings.calendar_rps, name="calendar"),
    }
