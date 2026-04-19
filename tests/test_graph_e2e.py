from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from src.app.graph.nodes import llm_response as llm_response_module
from src.app.graph.nodes import retrieve as retrieve_module
from src.app.graph.nodes import route as route_module
from src.app.graph.nodes.route import RouteDecision
from src.app.graph.workflow import build_graph
from src.app.prompts import PROMPT_VERSION


class _FixedRetriever(BaseRetriever):
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del query, run_manager
        return [Document(page_content="资料片段")]


def test_graph_end_to_end_general_branch(monkeypatch):
    route_module._route_chain = RunnableLambda(
        lambda _: RouteDecision(need_retrieval=False, reason="通用对话")
    )
    monkeypatch.setattr(
        llm_response_module,
        "_invoke_with_optional_web_search",
        lambda _state, _docs_text: AIMessage(content="你好，我在。"),
    )

    graph = build_graph()
    state = {
        "user_message": "你们是什么机构",
        "chat_history": [],
        "session_id": "thread-1",
        "need_retrieval": False,
        "route_reason": None,
        "retrieved_docs": [],
        "final_response": "",
        "prompt_version": PROMPT_VERSION,
    }

    result = graph.invoke(state)

    assert result["need_retrieval"] is False
    assert result["route_reason"] == "通用对话"
    assert result["retrieved_docs"] == []
    assert result["final_response"] == "你好，我在。"
    assert result["prompt_version"] == PROMPT_VERSION


def test_graph_end_to_end_retrieval_branch(monkeypatch):
    route_module._route_chain = RunnableLambda(
        lambda _: RouteDecision(need_retrieval=True, reason="需要专业资料")
    )
    monkeypatch.setattr(retrieve_module, "get_retriever", lambda: _FixedRetriever())
    monkeypatch.setattr(
        llm_response_module,
        "_invoke_with_optional_web_search",
        lambda _state, _docs_text: AIMessage(content="建议联系专业老师。"),
    )

    graph = build_graph()
    state = {
        "user_message": "OG训练法具体流程是什么",
        "chat_history": [],
        "session_id": "thread-2",
        "need_retrieval": False,
        "route_reason": None,
        "retrieved_docs": [],
        "final_response": "",
        "prompt_version": PROMPT_VERSION,
    }

    result = graph.invoke(state)

    assert result["need_retrieval"] is True
    assert result["route_reason"] == "需要专业资料"
    assert result["retrieved_docs"] == ["资料片段"]
    assert result["final_response"] == "建议联系专业老师。"
