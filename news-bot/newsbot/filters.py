from __future__ import annotations

import logging
import re
import unicodedata

from .config import Config
from .models import Item

log = logging.getLogger("newsbot")

CJK_RANGES = (
    (0x3400, 0x4DBF),  # 擴展 A
    (0x4E00, 0x9FFF),  # 常用中日韓
    (0xF900, 0xFAFF),  # 兼容表意文字
    (0x20000, 0x2A6DF),  # 擴展 B
)

_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff\u3400-\u4dbf]+", re.UNICODE)


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in CJK_RANGES)


def cjk_ratio(text: str) -> float:
    """文字入面中文字所佔比例。"""
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if is_cjk(c)) / len(letters)


def is_chinese(text: str, min_ratio: float) -> bool:
    return cjk_ratio(text) >= min_ratio


def normalize(text: str) -> str:
    """標題正規化：全形轉半形、去標點、去空白、小寫。用嚟比對重複。"""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower()
    text = _PUNCT_RE.sub("", text)
    return text


def bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def blocked(item: Item, keywords: list[str]) -> bool:
    haystack = f"{item.title} {item.summary}"
    return any(k in haystack for k in keywords)


def blocked_source(item: Item, patterns: list[str]) -> bool:
    src = (item.source or "").lower()
    return any(p.lower() in src for p in patterns if p)


def truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def is_fresh(item: Item, max_age_hours: float) -> bool:
    # 冇時間戳的當係新嘢（好多 RSS 唔提供時間）
    if item.published is None:
        return True
    return item.age_hours <= max_age_hours


def basic_filters(items: list[Item], cfg: Config) -> list[Item]:
    """淨低：中文 + 新鮮 + 非廣告 + 標題唔太短。"""
    kept: list[Item] = []
    stats = {
        "not_chinese": 0,
        "too_old": 0,
        "blocked": 0,
        "too_short": 0,
        "blocked_source": 0,
    }

    for it in items:
        it.title = it.title.strip()
        if len(it.title) < 6:
            stats["too_short"] += 1
            continue
        if blocked_source(it, cfg.block_sources):
            stats["blocked_source"] += 1
            continue
        if not is_chinese(it.title, cfg.cjk_min_ratio):
            stats["not_chinese"] += 1
            continue
        if blocked(it, cfg.block_keywords):
            stats["blocked"] += 1
            continue
        if not is_fresh(it, cfg.max_age_hours):
            stats["too_old"] += 1
            continue
        it.title = truncate(it.title, cfg.max_title_chars)
        kept.append(it)

    log.info(
        "過濾：剩 %d 則（剔走：非中文 %d／太舊 %d／廣告 %d／黑名單媒體 %d／太短 %d）",
        len(kept),
        stats["not_chinese"],
        stats["too_old"],
        stats["blocked"],
        stats["blocked_source"],
        stats["too_short"],
    )
    return kept
