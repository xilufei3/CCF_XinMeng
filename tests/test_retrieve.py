import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from src.app.graph.nodes import retrieve as retrieve_module
from src.app.graph.nodes.retrieve import retrieve_node


class _FixedRetriever(BaseRetriever):
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del query, run_manager
        return [Document(page_content="文档A"), Document(page_content="文档B")]


class _BrokenRetriever(BaseRetriever):
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del query, run_manager
        raise RuntimeError("boom")


def test_retrieve_node_with_fixed_docs(monkeypatch):
    monkeypatch.setattr(retrieve_module, "get_retriever", lambda: _FixedRetriever())

    result = retrieve_node({"user_message": "专业咨询", "session_id": "s-4"})

    assert result["retrieved_docs"] == ["文档A", "文档B"]


def test_retrieve_node_raises_on_error(monkeypatch):
    monkeypatch.setattr(retrieve_module, "get_retriever", lambda: _BrokenRetriever())

    with pytest.raises(RuntimeError, match="boom"):
        retrieve_node({"user_message": "专业咨询", "session_id": "s-5"})
