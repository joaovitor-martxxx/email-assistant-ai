import json
import logging
import sys

import pytest

from eaa.logging_setup import JsonFormatter, setup_logging


def make_record(msg="evento", level=logging.INFO, exc_info=None, **extra):
    record = logging.LogRecord("eaa.teste", level, __file__, 1, msg, (), exc_info)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_valid_json_with_base_fields():
    data = json.loads(JsonFormatter().format(make_record("Olá, ação")))
    assert data["msg"] == "Olá, ação"
    assert data["level"] == "INFO"
    assert data["logger"] == "eaa.teste"
    assert "ts" in data


def test_formatter_keeps_non_ascii_characters_readable():
    assert "ação" in JsonFormatter().format(make_record("ação"))


def test_formatter_includes_known_extra_fields():
    data = json.loads(JsonFormatter().format(make_record(trace_id="abc123", task_id=7, message_id="m1")))
    assert (data["trace_id"], data["task_id"], data["message_id"]) == ("abc123", 7, "m1")


def test_formatter_omits_extra_fields_that_were_not_set():
    data = json.loads(JsonFormatter().format(make_record()))
    assert not {"trace_id", "task_id", "message_id"} & set(data)


def test_formatter_includes_traceback_when_exc_info_is_set():
    try:
        raise ValueError("erro de exemplo")
    except ValueError:
        record = make_record("falhou", logging.ERROR, exc_info=sys.exc_info())
    data = json.loads(JsonFormatter().format(record))
    assert "ValueError" in data["exc"]


@pytest.fixture
def clean_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield root
    root.handlers, root.level = handlers, level


def test_setup_logging_writes_json_lines_to_stdout(capsys, clean_root_logger):
    setup_logging("INFO")
    logging.getLogger("eaa.teste").info("pronto", extra={"task_id": 3})
    line = capsys.readouterr().out.strip()
    assert json.loads(line)["task_id"] == 3


def test_setup_logging_is_idempotent(capsys, clean_root_logger):
    setup_logging("INFO")
    setup_logging("INFO")
    logging.getLogger("eaa.teste").info("uma vez só")
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_setup_logging_respects_level(capsys, clean_root_logger):
    setup_logging("WARNING")
    logger = logging.getLogger("eaa.teste")
    logger.info("não deve aparecer")
    logger.warning("deve aparecer")
    out = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(line)["msg"] for line in out] == ["deve aparecer"]
