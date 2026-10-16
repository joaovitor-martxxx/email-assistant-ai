from datetime import datetime, timezone
from eaa.models import Email, Extraction
from eaa.scoring import priority_score

def mk(sender="a@x.com", subject="oi", body=""):
    return Email("1", sender, subject, body, "")

def test_action_required_raises_score():
    low = priority_score(mk(), Extraction("s", False))
    high = priority_score(mk(), Extraction("s", True))
    assert high > low

def test_deadline_tomorrow_adds_points():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    ext = Extraction("s", True, deadline="2026-10-10T12:00:00+00:00")
    assert priority_score(mk(), ext, now) >= 70

def test_score_capped_at_100():
    ext = Extraction("s", True, deadline="2026-10-10T12:00:00+00:00")
    email = mk("chefe@x.com", "urgente prazo hoje", "asap vencimento amanhã")
    assert priority_score(email, ext, datetime(2026,10,10,tzinfo=timezone.utc)) == 100.0

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)

def test_urgent_word_raises_score():
    ext = Extraction("s", False)
    assert priority_score(mk(subject="URGENTE: contrato"), ext) > priority_score(mk(subject="contrato"), ext)

def test_vip_sender_raises_score():
    ext = Extraction("s", False)
    assert priority_score(mk(sender="diretoria@example.test"), ext) > priority_score(mk(), ext)

def test_distant_deadline_adds_nothing():
    far = Extraction("s", False, deadline="2026-12-01T12:00:00+00:00")
    assert priority_score(mk(), far, NOW) == priority_score(mk(), Extraction("s", False), NOW)

def test_deadline_in_three_days_adds_less_than_tomorrow():
    soon = priority_score(mk(), Extraction("s", False, deadline="2026-10-13T00:00:00+00:00"), NOW)
    tomorrow = priority_score(mk(), Extraction("s", False, deadline="2026-10-10T12:00:00+00:00"), NOW)
    assert 0 < soon < tomorrow

def test_invalid_deadline_is_ignored():
    assert priority_score(mk(), Extraction("s", False, deadline="não é data"), NOW) == 0.0

def test_naive_deadline_is_treated_as_utc():
    naive = priority_score(mk(), Extraction("s", False, deadline="2026-10-10T12:00:00"), NOW)
    aware = priority_score(mk(), Extraction("s", False, deadline="2026-10-10T12:00:00+00:00"), NOW)
    assert naive == aware
