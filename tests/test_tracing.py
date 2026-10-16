import logging

import pytest

from eaa import tracing


def test_default_trace_id_is_dash_outside_a_span():
    assert tracing.current_trace_id() == "-"


def test_span_sets_trace_id_and_restores_it_on_exit():
    with tracing.trace("tarefa") as trace_id:
        assert tracing.current_trace_id() == trace_id
        assert len(trace_id) == 12
    assert tracing.current_trace_id() == "-"


def test_nested_spans_restore_the_outer_id():
    with tracing.trace("externo") as outer:
        with tracing.trace("interno") as inner:
            assert inner != outer
            assert tracing.current_trace_id() == inner
        assert tracing.current_trace_id() == outer


def test_trace_id_is_restored_even_if_the_block_raises():
    with pytest.raises(ValueError):
        with tracing.trace("falha"):
            raise ValueError("erro de propósito")
    assert tracing.current_trace_id() == "-"


def test_each_span_gets_a_distinct_id():
    ids = set()
    for _ in range(20):
        with tracing.trace("t") as trace_id:
            ids.add(trace_id)
    assert len(ids) == 20


def test_span_end_is_logged_with_its_trace_id(caplog):
    with caplog.at_level(logging.INFO, logger="eaa.tracing"):
        with tracing.trace("processar") as trace_id:
            pass
    record = caplog.records[-1]
    assert record.trace_id == trace_id
    assert "processar" in record.getMessage()
