from src.app.services.report_session import (
    DEFAULT_REPORT_ID,
    REPORT_SESSION_TYPE,
    is_hidden_client_msg_id,
    load_report_text,
    normalize_session_type,
    parse_report_init_command,
)


def test_parse_report_init_command():
    assert parse_report_init_command("[[REPORT_SESSION_INIT::camplus_txt]]") == "camplus_txt"
    assert parse_report_init_command("[[REPORT_SESSION_INIT::]]") == DEFAULT_REPORT_ID
    assert parse_report_init_command("hello") is None


def test_normalize_session_type():
    assert normalize_session_type("report") == REPORT_SESSION_TYPE
    assert normalize_session_type("anything") == "general"


def test_hidden_client_msg_id_and_text_report_load():
    assert is_hidden_client_msg_id("do-not-render-123") is True
    assert is_hidden_client_msg_id("normal-id") is False

    report_text = load_report_text("camplus_txt")
    assert isinstance(report_text, str)
    assert "中文读写能力筛查作答分析报告" in report_text
