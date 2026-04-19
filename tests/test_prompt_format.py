from src.app.prompts.response import (
    build_response_system_prompt,
    format_retrieved_docs_for_prompt,
)


def test_format_docs_empty():
    result = format_retrieved_docs_for_prompt([])
    assert result == "(本轮未检索知识库, 请基于通用知识回答)"


def test_format_docs_non_empty():
    result = format_retrieved_docs_for_prompt(["第一段", "第二段"])
    assert "[资料1]\n第一段" in result
    assert "[资料2]\n第二段" in result


def test_build_system_prompt_with_report_text():
    result = build_response_system_prompt("中文读写能力筛查作答分析报告\\n作答总量: 15")
    assert "本次会话关联的筛查报告" in result
    assert "报告原文" in result
    assert "报告解读原则" in result


def test_build_system_prompt_excludes_retrieval_block_by_default():
    result = build_response_system_prompt(None)
    assert "# 参考资料" not in result


def test_build_system_prompt_includes_retrieval_block_when_needed():
    result = build_response_system_prompt(
        None,
        need_retrieval=True,
        retrieved_docs="[资料1]\n示例资料",
    )
    assert "# 参考资料" in result
    assert "[资料1]\n示例资料" in result
