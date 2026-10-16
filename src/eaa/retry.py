"""Retry com backoff exponencial, separado por tipo de erro.

- RATE_LIMIT (429): respeita o header Retry-After quando existe; senão usa um
  backoff longo, porque insistir rápido só gera mais 429.
- ERRO_SERVIDOR (5xx): problema do outro lado, duração desconhecida. Backoff
  moderado e poucas tentativas.
- ERRO_CONEXAO (timeout, rede): costuma ser um blip. Tenta rápido e mais vezes.

Erros fora dessas categorias (credencial inválida, request malformado,
recurso inexistente) não são repetidos: falhariam do mesmo jeito.
"""
import functools
import logging
import random
import socket
import time
from typing import Callable, Optional

import anthropic
from googleapiclient.errors import HttpError
from notion_client import APIErrorCode, APIResponseError

log = logging.getLogger(__name__)

RATE_LIMIT = "rate_limit"
ERRO_SERVIDOR = "erro_servidor"
ERRO_CONEXAO = "erro_conexao"

# attempts = total de tentativas (chamada original + retries); min/max em segundos
POLICIES = {
    RATE_LIMIT: {"attempts": 6, "min_wait": 5, "max_wait": 90},
    ERRO_SERVIDOR: {"attempts": 4, "min_wait": 3, "max_wait": 30},
    ERRO_CONEXAO: {"attempts": 5, "min_wait": 1, "max_wait": 10},
}

Categorizer = Callable[[BaseException], Optional[str]]


def backoff_with_jitter(policy: dict, attempt: int) -> float:
    """Backoff exponencial limitado ao teto, com até 10% de jitter."""
    wait = min(policy["min_wait"] * 2 ** (attempt - 1), policy["max_wait"])
    return wait + random.uniform(0, wait * 0.1)


def retry_after_seconds(headers) -> Optional[float]:
    if not headers:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def extract_headers(exc: BaseException):
    """Cada lib guarda os headers num lugar diferente; tenta os conhecidos."""
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "headers"):
        return response.headers
    if hasattr(exc, "headers"):
        return exc.headers
    if getattr(exc, "resp", None) is not None:
        return exc.resp  # httplib2.Response também suporta .get(chave)
    return None


def compute_wait(exc: BaseException, category: str, attempt: int) -> float:
    policy = POLICIES[category]
    retry_after = retry_after_seconds(extract_headers(exc))
    if retry_after is not None:
        return min(retry_after, policy["max_wait"] * 2)
    return backoff_with_jitter(policy, attempt)


def build_retry(categorize: Categorizer, api: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                attempt += 1
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    category = categorize(exc)
                    if category is None or attempt >= POLICIES[category]["attempts"]:
                        raise
                    wait = compute_wait(exc, category, attempt)
                    log.warning(
                        "%s: tentativa %d falhou (%s, %s: %s); aguardando %.1fs",
                        api, attempt, category, type(exc).__name__, str(exc)[:200], wait)
                    time.sleep(wait)
        return wrapper
    return decorator


def category_anthropic(exc: BaseException) -> Optional[str]:
    if isinstance(exc, anthropic.RateLimitError):
        return RATE_LIMIT
    if isinstance(exc, anthropic.InternalServerError):
        return ERRO_SERVIDOR
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return ERRO_CONEXAO
    return None


def category_notion(exc: BaseException) -> Optional[str]:
    if isinstance(exc, APIResponseError):
        if exc.code == APIErrorCode.RateLimited:
            return RATE_LIMIT
        if exc.code in (APIErrorCode.InternalServerError, APIErrorCode.ServiceUnavailable):
            return ERRO_SERVIDOR
        return None
    if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout)):
        return ERRO_CONEXAO
    return None


def category_google(exc: BaseException) -> Optional[str]:
    if isinstance(exc, HttpError):
        status = exc.resp.status if exc.resp else None
        if status == 429:
            return RATE_LIMIT
        if status in (500, 502, 503, 504):
            return ERRO_SERVIDOR
        return None
    if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout)):
        return ERRO_CONEXAO
    return None


retry_anthropic = build_retry(category_anthropic, "anthropic")
retry_notion = build_retry(category_notion, "notion")
retry_google = build_retry(category_google, "google")
