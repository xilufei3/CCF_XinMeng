from __future__ import annotations

from typing import Any

import httpx

from src.app.config import settings

BOCHA_SEARCH_ENDPOINT = "https://api.bochaai.com/v1/web-search"


def _string_field(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_results_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    candidates.append(payload.get("results"))

    data = payload.get("data")
    if isinstance(data, dict):
        candidates.append(data.get("results"))
        web_pages = data.get("webPages")
        if isinstance(web_pages, dict):
            candidates.append(web_pages.get("value"))

    web_pages = payload.get("webPages")
    if isinstance(web_pages, dict):
        candidates.append(web_pages.get("value"))

    items = payload.get("items")
    candidates.append(items)

    for candidate in candidates:
        if isinstance(candidate, list):
            normalized: list[dict[str, Any]] = []
            for item in candidate:
                if isinstance(item, dict):
                    normalized.append(item)
            if normalized:
                return normalized
    return []


def bocha_search(
    query: str,
    *,
    count: int | None = None,
    summary: bool = True,
    freshness: str = "noLimit",
) -> list[dict[str, str]]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return []

    api_key = settings.bocha_api_key.strip()
    if not api_key:
        raise RuntimeError("BOCHA_API_KEY is empty")

    payload: dict[str, Any] = {
        "query": normalized_query,
        "summary": bool(summary),
        "freshness": freshness,
        "count": max(1, int(count or settings.bocha_search_count)),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    timeout_sec = max(3, int(settings.web_search_fetch_timeout) + 2)
    timeout = httpx.Timeout(timeout=float(timeout_sec))
    with httpx.Client(timeout=timeout) as client:
        response = client.post(BOCHA_SEARCH_ENDPOINT, json=payload, headers=headers)

    if response.status_code >= 400:
        detail = response.text[:300].replace("\n", " ")
        raise RuntimeError(f"bocha search failed status={response.status_code} detail={detail}")

    body: Any
    try:
        body = response.json()
    except Exception as exc:
        raise RuntimeError("bocha search returned non-json payload") from exc

    if not isinstance(body, dict):
        return []

    items = _extract_results_list(body)
    normalized_items: list[dict[str, str]] = []
    for item in items:
        title = _string_field(item, ("title", "name"))
        url = _string_field(item, ("url", "link", "href"))
        snippet = _string_field(item, ("summary", "snippet", "description", "content"))
        if not title and not url and not snippet:
            continue
        normalized_items.append(
            {
                "title": title or "未命名来源",
                "url": url,
                "snippet": snippet,
            }
        )
    return normalized_items
