import pytest

from eaa.config import Settings
from eaa.rate_limiter import RateLimiter, build_limiters


class FakeTime:
    """Relógio e sleep falsos: o sleep apenas avança o relógio, sem esperar."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make(rate, capacity, t):
    return RateLimiter(rate, capacity, name="teste", clock=t.clock, sleep=t.sleep)


def test_full_bucket_allows_initial_burst_without_waiting():
    t = FakeTime()
    limiter = make(10, 5, t)
    for _ in range(5):
        limiter.acquire()
    assert t.sleeps == []


def test_empty_bucket_waits_one_over_rate():
    t = FakeTime()
    limiter = make(10, 5, t)
    for _ in range(5):
        limiter.acquire()
    limiter.acquire()
    assert t.sleeps == [pytest.approx(0.1)]


def test_bucket_refills_after_idle_time_capped_at_capacity():
    t = FakeTime()
    limiter = make(20, 3, t)
    for _ in range(3):
        limiter.acquire()
    t.now += 10  # tempo de sobra para encher; deve parar em 3 tokens
    for _ in range(3):
        limiter.acquire()
    assert t.sleeps == []
    limiter.acquire()
    assert len(t.sleeps) == 1


def test_sustained_rate_without_burst():
    t = FakeTime()
    limiter = make(10, 1, t)
    for _ in range(10):
        limiter.acquire()
    # 1 token inicial + 9 esperas de 0.1s
    assert t.now == pytest.approx(0.9)


def test_invalid_rate_raises():
    with pytest.raises(ValueError):
        RateLimiter(0)
    with pytest.raises(ValueError):
        RateLimiter(-1)


def test_build_limiters_uses_settings_per_api():
    settings = Settings(anthropic_rps=0.8, notion_rps=2.5, gmail_rps=4, calendar_rps=6)
    limiters = build_limiters(settings)
    assert set(limiters) == {"anthropic", "notion", "gmail", "calendar"}
    assert limiters["anthropic"].rate == 0.8
    assert limiters["notion"].rate == 2.5
    assert limiters["gmail"].rate == 4
    assert limiters["calendar"].name == "calendar"
