from src.app.graph.nodes.llm_response import _format_docs


def test_format_docs_empty():
    result = _format_docs([])
    assert result == "(本轮未检索知识库, 请基于通用知识回答)"


def test_format_docs_non_empty():
    result = _format_docs(["第一段", "第二段"])
    assert "[资料1]\n第一段" in result
    assert "[资料2]\n第二段" in result
