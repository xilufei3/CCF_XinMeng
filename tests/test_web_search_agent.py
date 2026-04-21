from src.app.config import settings
from src.app.services import web_search_agent as web_search_agent_module
from src.app.services.web_search_agent import WebSearchAgentTool, get_web_search_agent_tool


def test_web_search_agent_tool_formats_structured_output(monkeypatch):
    monkeypatch.setattr(
        web_search_agent_module,
        "bocha_search",
        lambda *_args, **_kwargs: [
            {
                "title": "来源A",
                "url": "https://example.edu/a",
                "snippet": "摘要A",
            },
            {
                "title": "来源B",
                "url": "https://example.org/b",
                "snippet": "摘要B",
            },
        ],
    )
    monkeypatch.setattr(
        web_search_agent_module,
        "_fetch_webpage_text",
        lambda url: ("页面标题" + url[-1], "正文内容" * 100),
    )
    monkeypatch.setattr(
        web_search_agent_module,
        "_summarize_source",
        lambda **kwargs: f"精炼摘要:{kwargs['title']}",
    )

    tool = WebSearchAgentTool()
    output = tool._run("读写障碍最新研究")

    assert "### 来源 1:" in output
    assert "- 链接: https://example.edu/a" in output
    assert "精炼摘要:页面标题a" in output
    assert "### 来源 2:" in output


def test_web_search_agent_tool_degrades_on_bocha_failure(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise RuntimeError("bocha unavailable")

    monkeypatch.setattr(web_search_agent_module, "bocha_search", _raise)

    tool = WebSearchAgentTool()
    output = tool._run("读写障碍")

    assert "未找到高质量相关信息" in output
    assert "bocha unavailable" in output


def test_web_search_agent_uses_one_year_by_default(monkeypatch):
    calls: list[str] = []

    def _fake_search(_query, *, freshness, **_kwargs):
        calls.append(freshness)
        return [{"title": "来源A", "url": "https://example.edu/a", "snippet": "摘要A"}]

    monkeypatch.setattr(web_search_agent_module, "bocha_search", _fake_search)
    monkeypatch.setattr(web_search_agent_module, "_fetch_webpage_text", lambda _url: ("页面标题A", "正文" * 20))
    monkeypatch.setattr(web_search_agent_module, "_summarize_source", lambda **_kwargs: "精炼摘要")

    tool = WebSearchAgentTool()
    output = tool._run("读写障碍干预方法")

    assert "### 来源 1:" in output
    assert calls == ["oneYear"]


def test_web_search_agent_retries_no_limit_after_empty(monkeypatch):
    calls: list[str] = []

    def _fake_search(_query, *, freshness, **_kwargs):
        calls.append(freshness)
        if freshness == "oneYear":
            return []
        return [{"title": "来源A", "url": "https://example.edu/a", "snippet": "摘要A"}]

    monkeypatch.setattr(web_search_agent_module, "bocha_search", _fake_search)
    monkeypatch.setattr(web_search_agent_module, "_fetch_webpage_text", lambda _url: ("页面标题A", "正文" * 20))
    monkeypatch.setattr(web_search_agent_module, "_summarize_source", lambda **_kwargs: "精炼摘要")

    tool = WebSearchAgentTool()
    output = tool._run("读写障碍干预方法")

    assert "### 来源 1:" in output
    assert calls == ["oneYear", "noLimit"]


def test_decide_freshness_prefers_no_limit_for_history_queries():
    freshness = web_search_agent_module._decide_freshness("读写障碍历史沿革与发展历程")
    assert freshness == "noLimit"


def test_get_web_search_agent_tool_respects_switch_and_api_key(monkeypatch):
    monkeypatch.setattr(web_search_agent_module, "_web_search_agent_tool", None)
    monkeypatch.setattr(web_search_agent_module, "_web_search_agent_tool_unavailable", False)

    monkeypatch.setattr(settings, "web_search_enabled", False, raising=False)
    assert get_web_search_agent_tool() is None

    monkeypatch.setattr(settings, "web_search_enabled", True, raising=False)
    monkeypatch.setattr(settings, "bocha_api_key", "", raising=False)
    monkeypatch.setattr(web_search_agent_module, "_web_search_agent_tool_unavailable", False)
    assert get_web_search_agent_tool() is None

    monkeypatch.setattr(settings, "bocha_api_key", "test-key", raising=False)
    monkeypatch.setattr(web_search_agent_module, "_web_search_agent_tool", None)
    monkeypatch.setattr(web_search_agent_module, "_web_search_agent_tool_unavailable", False)
    tool = get_web_search_agent_tool()

    assert isinstance(tool, WebSearchAgentTool)
