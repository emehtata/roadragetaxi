
import pytest

from theroadragetrip.performance import advance_chunked


def test_advance_chunked_processes_everything_across_multiple_calls():
    items = list(range(50))
    processed = []
    index = 0
    calls = 0
    while index < len(items):
        index = advance_chunked(items, index, 0.0, processed.append)
        calls += 1
        if calls > len(items):
            pytest.fail("advance_chunked made no forward progress")
    assert processed == items
    assert calls > 1, "a zero budget must force multiple calls, not finish in one"


def test_advance_chunked_finishes_in_one_call_with_a_generous_budget():
    items = list(range(50))
    processed = []
    index = advance_chunked(items, 0, 10.0, processed.append)
    assert index == len(items)
    assert processed == items


def test_advance_chunked_always_processes_at_least_one_item(monkeypatch):
    """A budget_s <= 0 (e.g. a stage that already overran an earlier
    sub-stage's shared deadline) must still make progress, never stall."""
    items = [1, 2, 3]
    processed = []
    index = advance_chunked(items, 0, -1.0, processed.append)
    assert index == 1
    assert processed == [1]
