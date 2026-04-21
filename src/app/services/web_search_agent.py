from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.app.config import settings
from src.app.services.bocha_search import bocha_search
from src.app.services.llm import get_web_search_agent_llm

logger = logging.getLogger(__name__)

WEB_SEARCH_AGENT_SYSTEM_PROMPT = """你是一个专业的信息检索助手。你的任务是根据用户问题从互联网上找到最相关、最权威的信息,并整理成结构化摘要。

要求:
1. 只保留与用户问题直接相关的信息,去掉无关内容
2. 忽略广告、营销、SEO 内容
3. 优先保留学术、政府、医院、知名机构来源
4. 输出使用简洁中文,不要写成营销文案
5. 如果可用信息不足,诚实指出不确定性
"""

FRESHNESS_CANDIDATES = {"oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"}

TRUSTED_DOMAIN_HINTS = (
    ".gov",
    ".edu",
    "who.int",
    "nih.gov",
    "cdc.gov",
    "aap.org",
    "gov.cn",
    "edu.cn",
    "ac.cn",
    "org.cn",
    "moe.gov.cn",
    "pku.edu.cn",
    "tsinghua.edu.cn",
)

_NO_LIMIT_HINTS = (
    "历史",
    "沿革",
    "起源",
    "发展历程",
    "发展史",
    "时间线",
    "历年",
    "长期",
    "古代",
    "近代",
    "timeline",
    "history",
)
_ONE_DAY_HINTS = ("今天", "今日", "刚刚", "实时", "24小时", "today", "now", "latest", "breaking")
_ONE_WEEK_HINTS = ("本周", "这周", "近一周", "一周", "week", "weekly")
_ONE_MONTH_HINTS = ("本月", "近一月", "一个月", "month", "monthly")
_ONE_YEAR_HINTS = ("本年", "今年", "近一年", "一年", "year", "annual", "recent")


def _clip_text(text: str, max_chars: int) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _extract_keywords(text: str) -> set[str]:
    normalized = str(text or "").lower()
    matches = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{3,}", normalized)
    # Drop common filler words to keep scoring stable.
    stopwords = {"孩子", "家长", "什么", "怎么", "以及", "可以", "需要", "最新", "研究", "方法"}
    return {token for token in matches if token not in stopwords}


def _authority_score(url: str) -> int:
    host = (urlparse(url).netloc or "").lower()
    if not host:
        return 0
    for hint in TRUSTED_DOMAIN_HINTS:
        if hint in host:
            return 4
    if host.endswith(".org"):
        return 2
    if host.endswith(".com"):
        return 1
    return 0


def _score_result(query_keywords: set[str], item: dict[str, str]) -> float:
    haystack = f"{item.get('title', '')}\n{item.get('snippet', '')}".lower()
    overlap = 0
    for keyword in query_keywords:
        if keyword in haystack:
            overlap += 1
    authority = _authority_score(item.get("url", ""))
    snippet_len_bonus = min(len(item.get("snippet", "")) / 180.0, 2.0)
    return overlap * 1.8 + authority + snippet_len_bonus


def _decide_freshness(query: str) -> str:
    normalized = str(query or "").strip().lower()
    if not normalized:
        return "oneYear"

    if any(hint in normalized for hint in _NO_LIMIT_HINTS):
        return "noLimit"
    if any(hint in normalized for hint in _ONE_DAY_HINTS):
        return "oneDay"
    if any(hint in normalized for hint in _ONE_WEEK_HINTS):
        return "oneWeek"
    if any(hint in normalized for hint in _ONE_MONTH_HINTS):
        return "oneMonth"
    if any(hint in normalized for hint in _ONE_YEAR_HINTS):
        return "oneYear"
    return "oneYear"


def _search_with_freshness_fallback(query: str, count: int) -> tuple[list[dict[str, str]], Exception | None]:
    freshness = _decide_freshness(query)
    if freshness not in FRESHNESS_CANDIDATES:
        freshness = "oneYear"

    attempts = [freshness]
    if freshness != "noLimit":
        attempts.append("noLimit")

    last_error: Exception | None = None
    for idx, attempt in enumerate(attempts, start=1):
        try:
            items = bocha_search(
                query,
                count=count,
                summary=True,
                freshness=attempt,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "web_search_agent bocha_search failed attempt=%s freshness=%s err=%s",
                idx,
                attempt,
                exc,
            )
            continue

        if items:
            if idx > 1:
                logger.info(
                    "web_search_agent bocha_search fallback hit freshness=%s results=%s",
                    attempt,
                    len(items),
                )
            return items, None

        logger.info("web_search_agent bocha_search empty attempt=%s freshness=%s", idx, attempt)

    return [], last_error


def _select_top_results(query: str, items: list[dict[str, str]], top_n: int = 3) -> list[dict[str, str]]:
    if not items:
        return []
    query_keywords = _extract_keywords(query)
    scored = [
        (idx, _score_result(query_keywords, item), item)
        for idx, item in enumerate(items)
    ]
    scored.sort(key=lambda row: (row[1], -row[0]), reverse=True)

    selected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for _, _, item in scored:
        url = str(item.get("url", "")).strip()
        if url and url in seen_urls:
            continue
        selected.append(item)
        if url:
            seen_urls.add(url)
        if len(selected) >= max(1, top_n):
            break

    if not selected:
        return items[: max(1, top_n)]
    return selected


def _extract_html_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>([\s\S]*?)</title>", html_text, re.IGNORECASE)
    if not match:
        return ""
    return _clip_text(html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip(), 120)


def _html_to_text(html_text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg|iframe).*?>.*?</\1>", " ", html_text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p>|</div>|</article>|</section>|</li>|</h[1-6]>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _fetch_webpage_text(url: str) -> tuple[str, str]:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return "", ""
    timeout_sec = max(3, int(settings.web_search_fetch_timeout))
    timeout = httpx.Timeout(timeout=float(timeout_sec))
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DyslexiaAIMVP/1.0; +https://xingmeng.com)",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(normalized_url)
    except Exception as exc:
        logger.info("web_search_agent fetch failed url=%s err=%s", normalized_url, exc)
        return "", ""

    if response.status_code >= 400:
        logger.info(
            "web_search_agent fetch non-2xx url=%s status=%s",
            normalized_url,
            response.status_code,
        )
        return "", ""

    raw = response.text or ""
    if not raw.strip():
        return "", ""

    title = _extract_html_title(raw)
    text = _html_to_text(raw)
    return title, _clip_text(text, 7000)


def _summarize_source(
    *,
    query: str,
    title: str,
    url: str,
    text: str,
    fallback_snippet: str,
) -> str:
    source_text = str(text or "").strip() or str(fallback_snippet or "").strip()
    if not source_text:
        return "未提取到稳定正文内容。"

    compact_source = _clip_text(source_text, 3500)
    prompt = (
        f"用户问题: {query}\n"
        f"来源标题: {title}\n"
        f"来源链接: {url or '无'}\n\n"
        f"网页内容:\n{compact_source}\n\n"
        "请输出200-300字中文摘要,只保留和问题直接相关的信息。"
    )
    try:
        llm = get_web_search_agent_llm()
        response = llm.invoke(
            [
                SystemMessage(content=WEB_SEARCH_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
        content = response.content
        if isinstance(content, str):
            summarized = content
        elif isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
            summarized = "".join(chunks)
        else:
            summarized = str(content)
        summarized = " ".join(summarized.split()).strip()
        if summarized:
            return _clip_text(summarized, 320)
    except Exception as exc:
        logger.info("web_search_agent summarize failed title=%s err=%s", title, exc)

    fallback = str(fallback_snippet or "").strip() or source_text
    return _clip_text(fallback, 320)


def _render_output(sources: list[dict[str, str]]) -> str:
    if not sources:
        return "未找到高质量相关信息。"
    blocks: list[str] = []
    for idx, source in enumerate(sources, start=1):
        blocks.append(
            "\n".join(
                [
                    f"### 来源 {idx}: {source.get('title') or '未命名来源'}",
                    f"- 链接: {source.get('url') or '无'}",
                    f"- 核心内容: {source.get('summary') or '未提取到有效内容'}",
                ]
            )
        )
    text = "\n\n".join(blocks)
    return _clip_text(text, max(300, int(settings.web_search_max_output_chars)))


class WebSearchAgentInput(BaseModel):
    query: str = Field(description="需要联网检索的问题")


class WebSearchAgentTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "用于联网搜索补充信息。优先返回高可信来源（学术/政府/医院/知名机构）"
        "的结构化摘要和链接。"
    )
    args_schema: type[BaseModel] = WebSearchAgentInput

    def _run(
        self,
        query: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        del run_manager
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "未找到高质量相关信息。"

        search_items, search_error = _search_with_freshness_fallback(
            normalized_query,
            count=max(1, int(settings.bocha_search_count)),
        )
        if search_error is not None:
            return f"未找到高质量相关信息。检索异常: {search_error}"

        if not search_items:
            return "未找到高质量相关信息。"

        selected = _select_top_results(normalized_query, search_items, top_n=6)
        sources: list[dict[str, str]] = []
        for item in selected:
            raw_title = str(item.get("title") or "").strip()
            raw_url = str(item.get("url") or "").strip()
            raw_snippet = str(item.get("snippet") or "").strip()

            page_title, page_text = _fetch_webpage_text(raw_url) if raw_url else ("", "")
            final_title = page_title or raw_title or "未命名来源"
            summary = _summarize_source(
                query=normalized_query,
                title=final_title,
                url=raw_url,
                text=page_text,
                fallback_snippet=raw_snippet,
            )

            sources.append(
                {
                    "title": final_title,
                    "url": raw_url,
                    "summary": summary,
                }
            )

        return _render_output(sources)


_web_search_agent_tool: WebSearchAgentTool | None = None
_web_search_agent_tool_unavailable = False


def get_web_search_agent_tool() -> WebSearchAgentTool | None:
    global _web_search_agent_tool
    global _web_search_agent_tool_unavailable

    if not bool(settings.web_search_enabled):
        return None
    if _web_search_agent_tool_unavailable:
        return None
    if _web_search_agent_tool is not None:
        return _web_search_agent_tool

    if not settings.bocha_api_key.strip():
        _web_search_agent_tool_unavailable = True
        logger.warning("web_search_agent disabled: BOCHA_API_KEY is empty")
        return None

    try:
        _web_search_agent_tool = WebSearchAgentTool()
    except Exception as exc:
        _web_search_agent_tool_unavailable = True
        logger.warning("web_search_agent init failed err=%s", exc)
        return None
    return _web_search_agent_tool
