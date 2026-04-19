from src.app.graph.nodes.llm_response import _format_docs, build_system_prompt


def test_format_docs_empty():
    result = _format_docs([])
    assert result == "(本轮未检索知识库, 请基于通用知识回答)"


def test_format_docs_non_empty():
    result = _format_docs(["第一段", "第二段"])
    assert "[资料1]\n第一段" in result
    assert "[资料2]\n第二段" in result


def test_build_system_prompt_with_report_text():
    result = build_system_prompt("中文读写能力筛查作答分析报告\\n作答总量: 15")
    assert "本次会话关联的筛查报告" in result
    assert "报告原文" in result
    assert "报告解读原则" in result
