import asyncio

from src.app.services import chat_service


class _Chunk:
    def __init__(self, content):
        self.content = content


class _FakeGraphApp:
    def __init__(self, events):
        self._events = events

    async def astream_events(self, initial_state, version="v2"):
        assert version == "v2"
        assert isinstance(initial_state, dict)
        for event in self._events:
            yield event


def _collect_stream_items(events):
    async def _run():
        graph_app = _FakeGraphApp(events)
        items = []
        async for item in chat_service._stream_graph_response(
            graph_app=graph_app,
            user_message="hello",
            session_id="s-1",
            chat_history=[],
            session_type="general",
            report_text=None,
        ):
            items.append(item)
        return items

    return asyncio.run(_run())


def test_stream_graph_response_accepts_missing_node_metadata():
    events = [
        {
            "event": "on_chat_model_stream",
            "metadata": {},
            "data": {"chunk": _Chunk("尽力")},
        },
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": _Chunk("支持")},
        },
        {
            "event": "on_chain_end",
            "metadata": {},
            "data": {"output": {"final_response": "尽力支持"}},
        },
    ]

    items = _collect_stream_items(events)

    assert items == [
        ("token", "尽力"),
        ("token", "支持"),
        ("final", "尽力支持"),
    ]


def test_stream_graph_response_ignores_non_llm_response_node_tokens():
    events = [
        {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "route"},
            "data": {"chunk": _Chunk("不应透传")},
        },
        {
            "event": "on_chat_model_stream",
            "metadata": {"node_name": "llm_response"},
            "data": {"chunk": _Chunk("应透传")},
        },
        {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "llm_response"},
            "data": {"output": {"final_response": "应透传"}},
        },
    ]

    items = _collect_stream_items(events)

    assert items == [
        ("token", "应透传"),
        ("final", "应透传"),
    ]


def test_stream_graph_response_supports_on_llm_stream_event_name():
    events = [
        {
            "event": "on_llm_stream",
            "metadata": {"langgraph_node": "llm_response"},
            "data": {"chunk": _Chunk([{"type": "text", "text": "分块"}])},
        },
        {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "llm_response"},
            "data": {"output": {"final_response": "分块"}},
        },
    ]

    items = _collect_stream_items(events)

    assert items == [
        ("token", "分块"),
        ("final", "分块"),
    ]
