import json
from datetime import date
from types import SimpleNamespace

import pytest

from eaa.claude_client import (CATEGORIES, EXAMPLES, MAX_FORMAT_ATTEMPTS, SYSTEM,
                               ClaudeClient, InvalidClaudeResponse, format_email,
                               parse_extraction)
from eaa.config import Settings
from eaa.models import Email

VALID = {"summary": "Resumo.", "action_required": True,
         "deadline": "2026-10-14T15:00:00-03:00", "category": "reuniao", "keywords": ["a"]}


def raw(**changes):
    data = {**VALID, **changes}
    return json.dumps({k: v for k, v in data.items() if v is not ...})


# --- prompt ---

def test_system_prompt_contains_every_example_email_and_answer():
    assert len(EXAMPLES) >= 5
    for email, result in EXAMPLES:
        assert email.subject in SYSTEM
        assert email.body in SYSTEM
        assert json.dumps(result, ensure_ascii=False) in SYSTEM


def test_examples_cover_every_category():
    assert {result["category"] for _, result in EXAMPLES} == set(CATEGORIES)


def test_every_example_answer_passes_the_validator():
    for _, result in EXAMPLES:
        assert parse_extraction(json.dumps(result)).category == result["category"]


def test_examples_use_only_fictional_addresses():
    for email, _ in EXAMPLES:
        assert email.sender.endswith("@example.test>")


def test_system_prompt_lists_allowed_categories():
    for category in CATEGORIES:
        assert category in SYSTEM


# --- validação ---

def test_valid_response_becomes_an_extraction():
    ext = parse_extraction(raw())
    assert (ext.category, ext.action_required, ext.deadline) == ("reuniao", True, VALID["deadline"])


def test_null_deadline_is_accepted():
    assert parse_extraction(raw(deadline=None)).deadline is None


def test_response_inside_code_fence_is_accepted():
    assert parse_extraction("```json\n" + raw() + "\n```").summary == "Resumo."


@pytest.mark.parametrize("text", [
    "isto não é JSON",
    "[1, 2]",
    raw(summary=...),
    raw(deadline=...),
    raw(category="geral"),
    raw(deadline="amanhã"),
    raw(deadline="2026-10-14T15:00:00"),
    raw(action_required="false"),
    raw(keywords="abc"),
    raw(summary="  "),
])
def test_invalid_response_is_rejected(text):
    with pytest.raises(InvalidClaudeResponse):
        parse_extraction(text)


# --- analyze com cliente falso ---

class FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies.pop(0))])


def make_client(replies):
    client = ClaudeClient.__new__(ClaudeClient)
    client.client = SimpleNamespace(messages=FakeMessages(replies))
    client.model, client.limiter = "modelo-teste", None
    return client


EMAIL = Email("m1", "Dana Teste <dana@example.test>", "Assunto", "Corpo.", "")


def test_invalid_then_valid_response_is_asked_again_and_accepted():
    client = make_client(["lixo", raw()])
    assert client.analyze(EMAIL, today=date(2026, 10, 12)).category == "reuniao"
    assert len(client.client.messages.calls) == 2


def test_always_invalid_response_raises_after_the_format_attempts():
    client = make_client(["lixo"] * 5)
    with pytest.raises(InvalidClaudeResponse):
        client.analyze(EMAIL, today=date(2026, 10, 12))
    assert len(client.client.messages.calls) == MAX_FORMAT_ATTEMPTS


def test_call_sends_model_system_and_today():
    client = make_client([raw()])
    client.analyze(EMAIL, today=date(2026, 10, 12))
    call = client.client.messages.calls[0]
    assert call["model"] == "modelo-teste"
    assert "temperature" not in call
    assert call["system"] == SYSTEM
    assert call["messages"][0]["content"] == format_email(EMAIL, date(2026, 10, 12))
    assert "Hoje: 2026-10-12 (segunda-feira)" in call["messages"][0]["content"]


# --- config ---

def test_default_model():
    settings = Settings()
    assert settings.anthropic_model == "claude-haiku-5-5"
