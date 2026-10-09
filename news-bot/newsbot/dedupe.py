from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timedelta, timezone

log = logging.getLogger("newsbot")

DEFAULT_TTL_DAYS = 7
MAX_ENTRIES = 6000


class SentStore:
    """記住已經推過嘅新聞，避免重複推送。以 JSON 存放，可由 GitHub Actions commit 返 repo。"""

    def __init__(self, path: pathlib.Path, ttl_days: int = DEFAULT_TTL_DAYS):
        self.path = pathlib.Path(path)
        self.ttl = timedelta(days=ttl_days)
        self.data: dict[str, str] = {}
        self.last_push: datetime | None = None
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = raw.get("sent", {}) if isinstance(raw, dict) else {}
            last = (raw or {}).get("last_push")
            if last:
                try:
                    self.last_push = datetime.fromisoformat(last)
                except Exception:
                    self.last_push = None
        except Exception as exc:
            log.warning("讀取 state 失敗（%s），當全新開始", exc)
            self.data = {}
        self.prune()

    def prune(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - self.ttl
        fresh = {}
        for key, iso in self.data.items():
            try:
                if datetime.fromisoformat(iso) >= cutoff:
                    fresh[key] = iso
            except Exception:
                continue
        if len(fresh) > MAX_ENTRIES:
            fresh = dict(
                sorted(fresh.items(), key=lambda kv: kv[1], reverse=True)[:MAX_ENTRIES]
            )
        self.data = fresh

    def is_sent(self, uid: str) -> bool:
        return uid in self.data

    def mark(self, uids: list[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for uid in uids:
            self.data[uid] = now

    def mark_push(self) -> None:
        """記低「呢一刻推咗嘢」，用嚟做最短間隔鎖。"""
        self.last_push = datetime.now(timezone.utc)

    def save(self) -> None:
        self.prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated": datetime.now(timezone.utc).isoformat(),
            "count": len(self.data),
            "last_push": self.last_push.isoformat() if self.last_push else None,
            "sent": self.data,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(self.path)
        log.info("已儲存 %d 條已推送記錄 → %s", len(self.data), self.path)
