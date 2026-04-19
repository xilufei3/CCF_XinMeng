import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.app.config import settings

GENERAL_SESSION_TYPE = "general"
REPORT_SESSION_TYPE = "report"

DEFAULT_REPORT_ID = "camplus_txt"
REPORT_SESSION_INIT_PREFIX = "[[REPORT_SESSION_INIT::"
REPORT_SESSION_INIT_SUFFIX = "]]"
HIDDEN_CLIENT_MSG_PREFIX = "do-not-render-"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPORT_FILENAMES = {
    "camplus_txt": "answer_analyse_camplus.txt",
}


def normalize_session_type(session_type: str | None) -> str:
    if str(session_type or "").strip().lower() == REPORT_SESSION_TYPE:
        return REPORT_SESSION_TYPE
    return GENERAL_SESSION_TYPE


def parse_report_init_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not (text.startswith(REPORT_SESSION_INIT_PREFIX) and text.endswith(REPORT_SESSION_INIT_SUFFIX)):
        return None

    report_id = text[len(REPORT_SESSION_INIT_PREFIX) : -len(REPORT_SESSION_INIT_SUFFIX)].strip()
    return report_id or DEFAULT_REPORT_ID


def is_hidden_client_msg_id(client_msg_id: str | None) -> bool:
    normalized = str(client_msg_id or "").strip()
    return normalized.startswith(HIDDEN_CLIENT_MSG_PREFIX)


def _normalized_report_id(report_id: str | None) -> str:
    return str(report_id or "").strip() or DEFAULT_REPORT_ID


def _load_report_text_from_local(report_id: str) -> str | None:
    filename = _REPORT_FILENAMES.get(report_id)
    if filename is None:
        return None

    local_dir = Path(settings.report_local_dir)
    if not local_dir.is_absolute():
        local_dir = (_REPO_ROOT / local_dir).resolve()

    report_path = local_dir / filename
    if not report_path.exists():
        # Keep compatibility with legacy layout before reports were moved into data/reports/raw.
        legacy_path = _REPO_ROOT / filename
        report_path = legacy_path if legacy_path.exists() else report_path

    if not report_path.exists():
        return None

    try:
        content = report_path.read_text(encoding="utf-8")
    except Exception:
        return None

    normalized = content.strip()
    if not normalized:
        return None
    return normalized


def _extract_text_from_json_payload(raw_text: str) -> str | None:
    try:
        payload = json.loads(raw_text)
    except Exception:
        return None

    if isinstance(payload, str):
        normalized = payload.strip()
        return normalized or None

    if not isinstance(payload, dict):
        return None

    for key in ("report_text", "raw_text", "content", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _load_report_text_from_api(report_id: str) -> str | None:
    template = str(settings.report_api_url_template or "").strip()
    if not template:
        return None

    if "{report_id}" in template:
        url = template.format(report_id=quote(report_id, safe=""))
    else:
        joiner = "&" if "?" in template else "?"
        url = f"{template}{joiner}report_id={quote(report_id, safe='')}"

    req = Request(url, headers={"Accept": "text/plain, application/json"})

    try:
        with urlopen(req, timeout=settings.report_api_timeout_sec) as response:
            raw_bytes = response.read()
            content_type = str(response.headers.get("Content-Type", "")).lower()
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None
    except Exception:
        return None

    raw_text = raw_bytes.decode("utf-8", errors="replace").strip()
    if not raw_text:
        return None

    if "application/json" in content_type or raw_text.startswith("{") or raw_text.startswith('"'):
        parsed_text = _extract_text_from_json_payload(raw_text)
        if parsed_text is not None:
            return parsed_text

    return raw_text


def load_report_text(report_id: str | None) -> str | None:
    resolved_report_id = _normalized_report_id(report_id)
    report_source = str(settings.report_source or "").strip().lower() or "local"

    if report_source == "api":
        return _load_report_text_from_api(resolved_report_id)
    return _load_report_text_from_local(resolved_report_id)
