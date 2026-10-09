from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Item:
    """一單新聞。"""

    title: str
    link: str
    source: str
    category: str
    published: datetime | None = None
    summary: str = ""

    # 由 cluster 填入：同一單新聞的其他媒體
    also: list[tuple[str, str]] = field(default_factory=list)  # [(媒體名, url)]

    @property
    def age_hours(self) -> float:
        if not self.published:
            return 0.0
        now = datetime.now(timezone.utc)
        delta = now - self.published
        return max(delta.total_seconds() / 3600.0, 0.0)

    @property
    def uid(self) -> str:
        """去重用的穩定識別（網址 + 標題）。"""
        return f"{self.link}||{self.title}"
