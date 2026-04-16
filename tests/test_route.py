import pytest

from src.app.graph.nodes import route as route_module
from src.app.graph.nodes.route import RouteDecision, route_node
from src.app.graph.workflow import _route_next_node


class _FakeRouteChain:
    def __init__(self, decision: RouteDecision):
        self._decision = decision

    def invoke(self, _):
        return self._decision


class _BrokenRouteChain:
    def invoke(self, _):
        raise RuntimeError("route model failed")


class _PlainLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, _):
        return _RawMessage(self._content)


class _RawMessage:
    def __init__(self, content):
        self.content = content


class _IncludeRawParsedChain:
    def invoke(self, _):
        return {
            "parsed": RouteDecision(need_retrieval=True, reason="需要检索"),
            "raw": _RawMessage(""),
            "parsing_error": None,
        }


class _IncludeRawFenceChain:
    def invoke(self, _):
        return {
            "parsed": None,
            "raw": _RawMessage(
                """```json
{
  "need_retrieval": false,
  "reason": "日常闲聊"
}
```"""
            ),
            "parsing_error": ValueError("Invalid JSON"),
        }


def test_route_node_returns_structured_decision(monkeypatch):
    monkeypatch.setattr(
        route_module,
        "_get_route_chain",
        lambda: _FakeRouteChain(RouteDecision(need_retrieval=True, reason="需要专业资料")),
    )

    result = route_node({"user_message": "OG训练法是啥", "session_id": "s-1"})

    assert result["need_retrieval"] is True
    assert result["route_reason"] == "需要专业资料"


def test_route_node_falls_back_to_plain_llm_on_structured_error(monkeypatch):
    monkeypatch.setattr(route_module, "_get_route_chain", lambda: _BrokenRouteChain())
    monkeypatch.setattr(
        route_module,
        "get_route_llm",
        lambda: _PlainLLM('{"need_retrieval": false, "reason": "日常闲聊"}'),
    )

    result = route_node({"user_message": "你好", "session_id": "s-2"})

    assert result["need_retrieval"] is False
    assert result["route_reason"] == "日常闲聊"


def test_route_node_accepts_include_raw_parsed(monkeypatch):
    monkeypatch.setattr(route_module, "_get_route_chain", lambda: _IncludeRawParsedChain())

    result = route_node({"user_message": "OG训练法是啥", "session_id": "s-3"})

    assert result["need_retrieval"] is True
    assert result["route_reason"] == "需要检索"


def test_route_node_recovers_from_fenced_json(monkeypatch):
    monkeypatch.setattr(route_module, "_get_route_chain", lambda: _IncludeRawFenceChain())

    result = route_node({"user_message": "你好", "session_id": "s-4"})

    assert result["need_retrieval"] is False
    assert result["route_reason"] == "日常闲聊"


def test_route_condition_edges():
    assert _route_next_node({"need_retrieval": True}) == "retrieve"
    assert _route_next_node({"need_retrieval": False}) == "llm_response"
