import datetime as dt

import httpx
import pytest

from app.chat import llm
from app.chat.interpreter import Reply, ToolCall
from app.chat.service import TOOLS
from app.config import get_settings

TODAY = dt.date(2026, 11, 15)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("FF_LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("FF_LLM_API_KEY")
    get_settings.cache_clear()


def _client(reply: dict | None, status: int = 200, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=reply or {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ask(reply, **kwargs):
    return llm.interpret_with_model("surat ka maal kitna pada hai", TODAY, frozenset({"surat"}), "LR-1", _client(reply, **kwargs))


def test_the_model_is_offered_exactly_the_tools_that_exist():
    assert set(llm.TOOL_SPECS) == set(TOOLS)


def test_without_a_key_the_model_is_not_called():
    assert llm.interpret_with_model("hello", TODAY, frozenset(), None, _client(None, status=500)) is None


def test_a_tool_choice_is_validated_and_returned(with_key):
    seen = []
    reply = {"content": [{"type": "tool_use", "name": "pending_by_destination", "input": {"destination": "surat"}}]}
    assert _ask(reply, seen=seen) == ToolCall("pending_by_destination", {"destination": "surat"})
    sent = seen[0]
    assert sent.headers["x-api-key"] == "test-key" and sent.headers["anthropic-version"] == "2023-06-01"
    body = sent.read().decode()
    assert "surat ka maal" in body and "LR-1" in body and "2026-11-15" in body and '"input_schema"' in body

    dated = {"content": [{"type": "tool_use", "name": "arrivals_on_date", "input": {"date": "2026-11-14"}}]}
    assert _ask(dated) == ToolCall("arrivals_on_date", {"date": dt.date(2026, 11, 14)})
    assert _ask({"content": [{"type": "text", "text": "Which LR do you mean?"}]}) == Reply("Which LR do you mean?")


def test_anything_unusable_falls_back_to_the_rules(with_key):
    bad_replies = (
        {"content": [{"type": "tool_use", "name": "delete_everything", "input": {}}]},
        {"content": [{"type": "tool_use", "name": "pending_older_than", "input": {"days": "many"}}]},
        {"content": [{"type": "tool_use", "name": "lr_details", "input": {"lr_number": "LR-1", "fields": ["password"]}}]},
        {"content": []},
        {"unexpected": True},
    )
    for reply in bad_replies:
        assert _ask(reply) is None, reply
    assert _ask(None, status=529) is None
