from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import requests

from .config import Config
from .models import Item

log = logging.getLogger("newsbot")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _to_utc(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = getattr(entry, key, None) or entry.get(key) if hasattr(entry, "get") else None
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _source_name(entry, fallback: str) -> str:
    # Google News 會提供 <source> 元素
    src = entry.get("source") if hasattr(entry, "get") else None
    if isinstance(src, dict) and src.get("title"):
        return strip_html(src["title"])
    if hasattr(entry, "source") and getattr(entry, "source", None):
        return strip_html(str(entry.source))
    author = entry.get("author") if hasattr(entry, "get") else None
    if author:
        return strip_html(str(author))[:40]
    return fallback


# 「標題 (09:08) - 20261009 - 兩岸 - 明報新聞網」→「標題」
# 「標題 - 20261008 - 每日明報」→「標題」
_JUNK_TAIL_RE = re.compile(
    r"(?:\s*[（(]\s*\d{1,2}:\d{2}\s*[)）])?"
    r"(?:\s*-\s*20\d{6}(?:\s*-\s*[^\-|]{1,16})*)?$"
)
_DASHES = {"－": "-", "–": "-", "—": "-", "−": "-", "﹘": "-"}


def _clean_title(title: str) -> tuple[str, str | None]:
    """Google News 標題格式為「標題 - 媒體名」，拆開佢並清走日期/欄位尾巴。"""
    title = strip_html(title)
    for dash, plain in _DASHES.items():
        title = title.replace(dash, plain)
    for _ in range(3):  # 有啲標題有幾層尾巴，loop 清乾淨
        cleaned = _JUNK_TAIL_RE.sub("", title).strip()
        if cleaned == title:
            break
        title = cleaned
    tail = None
    if " - " in title:
        head, _, maybe = title.rpartition(" - ")
        if head and 0 < len(maybe) <= 24:
            title, tail = head.strip(), maybe.strip()
    return title, tail


def parse_feed(url: str, body: bytes, fallback_name: str, category: str) -> list[Item]:
    feed = feedparser.parse(body)
    items: list[Item] = []
    for entry in feed.entries:
        raw_title = entry.get("title") or ""
        if not raw_title:
            continue
        title, tail = _clean_title(raw_title)
        link = entry.get("link") or ""
        if not link:
            continue
        source = _source_name(entry, tail or fallback_name)
        summary = strip_html(entry.get("summary") or entry.get("description") or "")
        items.append(
            Item(
                title=title,
                link=link,
                source=source,
                category=category,
                published=_to_utc(entry),
                summary=summary[:300],
            )
        )
    return items


def _fetch_one(source, cfg: Config) -> list[Item]:
    try:
        resp = requests.get(
            source.url,
            timeout=cfg.request_timeout,
            headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
        )
        resp.raise_for_status()
        items = parse_feed(source.url, resp.content, source.name, source.category)
        log.info("  ✓ %-28s %d 則", source.name, len(items))
        return items
    except Exception as exc:  # 單一來源壞掉唔可以拖垮全個 run
        log.warning("  ✗ %-28s %s", source.name, type(exc).__name__)
        return []


def fetch_all(cfg: Config) -> list[Item]:
    log.info("抓取 %d 個新聞來源…", len(cfg.sources))
    results: list[Item] = []
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
        for items in pool.map(lambda s: _fetch_one(s, cfg), cfg.sources):
            results.extend(items)
    log.info("共抓到 %d 則原始新聞", len(results))
    return results
