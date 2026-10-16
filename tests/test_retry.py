import httpx
import anthropic
import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response
from notion_client import APIErrorCode, APIResponseError

from eaa import retry as r


def _response(status, headers=None):
    request = httpx.Request("POST", "https://api.example.test/v1")
    return httpx.Response(status, headers=headers or {}, request=request)


def anthropic_error(cls, status, headers=None):
    return cls("erro simulado", response=_response(status, headers), body=None)


def notion_error(code, status=500):
    return APIResponseError(code, status, "erro simulado", httpx.Headers(), "{}")


def google_error(status):
    return HttpError(Response({"status": str(status)}), b"{}")


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(r.time, "sleep", calls.append)
    return calls


# --- categorização por API ---

def test_anthropic_categories():
    assert r.category_anthropic(anthropic_error(anthropic.RateLimitError, 429)) == r.RATE_LIMIT
    assert r.category_anthropic(anthropic_error(anthropic.InternalServerError, 500)) == r.ERRO_SERVIDOR
    request = httpx.Request("POST", "https://api.example.test/v1")
    assert r.category_anthropic(anthropic.APIConnectionError(request=request)) == r.ERRO_CONEXAO
    assert r.category_anthropic(anthropic.APITimeoutError(request=request)) == r.ERRO_CONEXAO
    assert r.category_anthropic(ValueError()) is None
    assert r.category_anthropic(anthropic_error(anthropic.AuthenticationError, 401)) is None


def test_notion_categories():
    assert r.category_notion(notion_error(APIErrorCode.RateLimited, 429)) == r.RATE_LIMIT
    assert r.category_notion(notion_error(APIErrorCode.InternalServerError)) == r.ERRO_SERVIDOR
    assert r.category_notion(notion_error(APIErrorCode.ServiceUnavailable, 503)) == r.ERRO_SERVIDOR
    assert r.category_notion(notion_error(APIErrorCode.ObjectNotFound, 404)) is None
    assert r.category_notion(ConnectionError()) == r.ERRO_CONEXAO


def test_google_categories():
    assert r.category_google(google_error(429)) == r.RATE_LIMIT
    assert r.category_google(google_error(503)) == r.ERRO_SERVIDOR
    assert r.category_google(google_error(404)) is None
    assert r.category_google(TimeoutError()) == r.ERRO_CONEXAO


# --- espera ---

def test_backoff_grows_and_respects_cap():
    policy = r.POLICIES[r.ERRO_CONEXAO]
    first, second, capped = (r.backoff_with_jitter(policy, n) for n in (1, 2, 10))
    assert policy["min_wait"] <= first < policy["min_wait"] * 1.2
    assert second > first
    assert capped <= policy["max_wait"] * 1.15


def test_retry_after_header_parsing():
    assert r.retry_after_seconds({"retry-after": "12"}) == 12.0
    assert r.retry_after_seconds({"Retry-After": "7"}) == 7.0
    assert r.retry_after_seconds({}) is None
    assert r.retry_after_seconds(None) is None
    assert r.retry_after_seconds({"retry-after": "abc"}) is None


def test_retry_after_is_read_from_exception_and_capped():
    exc = anthropic_error(anthropic.RateLimitError, 429, {"retry-after": "20"})
    assert r.compute_wait(exc, r.RATE_LIMIT, attempt=1) == 20.0
    huge = anthropic_error(anthropic.RateLimitError, 429, {"retry-after": "9999"})
    assert r.compute_wait(huge, r.RATE_LIMIT, attempt=1) == r.POLICIES[r.RATE_LIMIT]["max_wait"] * 2


# --- decorator ---

def test_retries_transient_error_then_succeeds(sleeps):
    attempts = []

    @r.retry_google
    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise google_error(503)
        return "ok"

    assert flaky() == "ok"
    assert len(attempts) == 3
    assert len(sleeps) == 2


def test_non_retryable_error_is_raised_immediately(sleeps):
    attempts = []

    @r.retry_google
    def not_found():
        attempts.append(1)
        raise google_error(404)

    with pytest.raises(HttpError):
        not_found()
    assert len(attempts) == 1
    assert sleeps == []


@pytest.mark.parametrize("make_error, category", [
    (lambda: google_error(429), r.RATE_LIMIT),
    (lambda: google_error(503), r.ERRO_SERVIDOR),
    (lambda: TimeoutError(), r.ERRO_CONEXAO),
])
def test_gives_up_after_the_attempts_of_each_category(sleeps, make_error, category):
    attempts = []

    @r.retry_google
    def always_fails():
        attempts.append(1)
        raise make_error()

    with pytest.raises(Exception):
        always_fails()
    total = r.POLICIES[category]["attempts"]
    assert len(attempts) == total
    assert len(sleeps) == total - 1
