from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import Config
from .filters import bigrams, jaccard, normalize
from .models import Item

log = logging.getLogger("newsbot")


@dataclass
class Story:
    """一單新聞（可能由多間媒體報道）。"""

    main: Item
    also: list[Item] = field(default_factory=list)

    @property
    def category(self) -> str:
        return self.main.category

    @property
    def published(self):
        return self.main.published

    @property
    def uid(self) -> str:
        return normalize(self.main.title)


def priority_rank(source: str, cfg: Config, category: str | None = None) -> int:
    """國際版塊用另一條優先次序：國際通訊社行先，香港媒體報道國際新聞排後。"""
    names = cfg.source_priority
    if category == "world" and cfg.world_source_priority:
        names = cfg.world_source_priority
    src = (source or "").lower()
    for i, name in enumerate(names):
        if name.lower() in src:
            return i
    return len(names)


def cluster(items: list[Item], cfg: Config) -> list[Story]:
    """把相同事件嘅報道合併成一單，避免同一單新聞出幾次。"""
    # 1) 同一條 link 只留一次
    seen_links: set[str] = set()
    unique: list[Item] = []
    for it in items:
        key = it.link.split("?")[0] if "news.google" not in it.link else it.link
        if key in seen_links:
            continue
        seen_links.add(key)
        unique.append(it)

    # 2) 排序：優先媒體行先，其次新嘅行先
    ordered = sorted(
        unique,
        key=lambda i: (
            priority_rank(i.source, cfg, i.category),
            -(i.published.timestamp() if i.published else 0),
        ),
    )

    stories: list[Story] = []
    reps: list[set[str]] = []
    norms: list[str] = []

    for item in ordered:
        norm = normalize(item.title)
        grams = bigrams(norm)
        placed = False
        for idx, rep_grams in enumerate(reps):
            if jaccard(grams, rep_grams) >= cfg.dupe_threshold:
                stories[idx].also.append(item)
                placed = True
                break
        if not placed:
            stories.append(Story(main=item))
            reps.append(grams)
            norms.append(norm)

    log.info("合併後共 %d 單新聞（原本 %d 則報道）", len(stories), len(unique))
    return stories


def attach_also(stories: list[Story]) -> None:
    """把其他媒體嘅連結掛上去 main item。"""
    for story in stories:
        seen: set[str] = set()
        pairs: list[tuple[str, str]] = []
        for other in story.also:
            if other.link == story.main.link:
                continue
            if other.source.lower() == story.main.source.lower():
                continue
            key = other.source.lower()
            if key in seen:
                continue
            seen.add(key)
            pairs.append((other.source, other.link))
        story.main.also = pairs[:4]


def rank(stories: list[Story], cfg: Config) -> list[Story]:
    """分數 = 新鮮度 + 媒體權威度 + 有冇多家報道。"""

    def score(story: Story) -> float:
        freshness = max(0.0, 24.0 - story.main.age_hours) * 0.4  # 越新越高分
        authority = (
            len(cfg.world_source_priority or cfg.source_priority)
            - priority_rank(story.main.source, cfg, story.category)
        ) * 1.0
        coverage = min(len(story.also), 5) * 4.0  # 多間媒體報道 = 更重要
        return freshness + authority + coverage

    return sorted(stories, key=score, reverse=True)
