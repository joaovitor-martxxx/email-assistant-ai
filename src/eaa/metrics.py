import json
from collections import Counter
from .db import Database

class Metrics:
    def __init__(self):
        self.counters = Counter()

    def incr(self, name: str, n: int = 1) -> None:
        self.counters[name] += n

    def snapshot(self, db: Database) -> dict:
        return {"counters": dict(self.counters), "queue": db.counts()}

def render_dashboard(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, ensure_ascii=False)
