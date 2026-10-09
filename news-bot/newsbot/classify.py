from __future__ import annotations

import logging

from .config import Config
from .models import Item

log = logging.getLogger("newsbot")


def _hit(text: str, keywords: list[str]) -> bool:
    low = (text or "").lower()
    return any(k.lower() in low for k in keywords if k)


def is_overseas_source(item: Item, cfg: Config) -> bool:
    """海外華文媒體（加拿大星島、美西世界日報等）唔當香港新聞。"""
    return _hit(item.source, cfg.overseas_source_keywords)


def reclassify(items: list[Item], cfg: Config) -> list[Item]:
    """來源標籤未必準確（例如 Google News 國際版會出香港報道），按來源名同標題重新判斷。"""
    n_hk = 0
    n_world = 0
    for item in items:
        source_is_hk = _hit(item.source, cfg.hk_source_keywords) and not is_overseas_source(
            item, cfg
        )
        title_is_hk = _hit(item.title, cfg.hk_title_keywords) and not is_overseas_source(
            item, cfg
        )

        # 香港媒體報道外國事件（例如 RTHK 報美國航母）→ 歸國際，唔擺香港版
        is_foreign_story = (not title_is_hk) and _hit(item.title, cfg.foreign_title_keywords)

        if source_is_hk or title_is_hk:
            if is_foreign_story:
                item.category = "world"
                n_world += 1
                continue
            item.category = "hk"
            n_hk += 1
        else:
            item.category = "world"
            n_world += 1

    log.info("重新分類：香港 %d 則 ／ 國際 %d 則", n_hk, n_world)
    return items
