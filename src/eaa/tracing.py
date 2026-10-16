import contextvars
import logging
import time
import uuid
from contextlib import contextmanager

_trace_id = contextvars.ContextVar("trace_id", default="-")
log = logging.getLogger(__name__)

def current_trace_id() -> str:
    return _trace_id.get()

@contextmanager
def trace(name: str):
    token = _trace_id.set(uuid.uuid4().hex[:12])
    start = time.perf_counter()
    try:
        yield current_trace_id()
    finally:
        ms = (time.perf_counter() - start) * 1000
        log.info("span %s finalizado em %.1f ms", name, ms,
                 extra={"trace_id": current_trace_id()})
        _trace_id.reset(token)
