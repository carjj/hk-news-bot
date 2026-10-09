from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field
from datetime import timedelta, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 香港時間（香港全年無夏令時間，固定 UTC+8）
HKT = timezone(timedelta(hours=8), name="HKT")

DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass
class Section:
    key: str
    title: str
    limit: int
    enabled: bool


@dataclass
class Source:
    name: str
    url: str
    category: str


@dataclass
class Config:
    bot_token: str
    chat_ids: list[str]
    max_total: int = 14
    max_per_source: int = 2
    min_interval_minutes: int = 45  # 兩次推送之間最短相隔（防止兩個 trigger 重複推）
    max_age_hours: float = 12.0
    dupe_threshold: float = 0.42
    cjk_min_ratio: float = 0.25
    skip_if_empty: bool = True
    dry_run: bool = False
    mode: str = "digest"  # digest | individual
    state_path: pathlib.Path = ROOT / "state" / "sent.json"
    sections: list[Section] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    source_priority: list[str] = field(default_factory=list)
    world_source_priority: list[str] = field(default_factory=list)
    block_keywords: list[str] = field(default_factory=list)
    hk_source_keywords: list[str] = field(default_factory=list)
    hk_title_keywords: list[str] = field(default_factory=list)
    overseas_source_keywords: list[str] = field(default_factory=list)
    foreign_title_keywords: list[str] = field(default_factory=list)
    block_sources: list[str] = field(default_factory=list)
    max_title_chars: int = 68
    disable_preview: bool = True
    quiet_hours: list[int] = field(default_factory=list)
    request_timeout: int = 15
    max_workers: int = 16

    @classmethod
    def load(cls, config_path: str | os.PathLike | None = None) -> "Config":
        path = pathlib.Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        raw = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        settings = raw.get("settings") or {}

        sections = [
            Section(
                key=s["key"],
                title=s.get("title", s["key"]),
                limit=int(s.get("limit", 5)),
                enabled=bool(s.get("enabled", True)),
            )
            for s in (raw.get("sections") or [])
        ]

        # 環境變數可以臨時開關版塊，例如 SECTIONS= hk,world
        sec_env = _env("SECTIONS")
        if sec_env:
            wanted = {x.strip().lower() for x in sec_env.split(",") if x.strip()}
            sections = [s for s in sections if s.key in wanted]

        sources = [
            Source(name=s["name"], url=s["url"], category=s.get("category", "world"))
            for s in (raw.get("sources") or [])
            if s.get("url")
        ]

        token = _env("TELEGRAM_BOT_TOKEN", "") or ""
        chats_raw = _env("TELEGRAM_CHAT_IDS") or _env("TELEGRAM_CHAT_ID") or ""
        chat_ids = [c.strip() for c in chats_raw.split(",") if c.strip()]

        quiet_raw = _env("QUIET_HOURS", "") or ""  # 例： "0-6" 或 "1,2,3"
        quiet_hours = parse_hour_range(quiet_raw)

        return cls(
            bot_token=token,
            chat_ids=chat_ids,
            max_total=_env_int("MAX_TOTAL", int(settings.get("max_total", 14))),
            max_per_source=_env_int("MAX_PER_SOURCE", int(settings.get("max_per_source", 2))),
            min_interval_minutes=_env_int(
                "MIN_INTERVAL_MINUTES", int(settings.get("min_interval_minutes", 45))
            ),
            max_age_hours=_env_float("MAX_AGE_HOURS", float(settings.get("max_age_hours", 12))),
            dupe_threshold=_env_float("DUPE_THRESHOLD", float(settings.get("dupe_threshold", 0.42))),
            cjk_min_ratio=_env_float("CJK_MIN_RATIO", float(settings.get("cjk_min_ratio", 0.25))),
            skip_if_empty=_env_bool("SKIP_IF_EMPTY", bool(settings.get("skip_if_empty", True))),
            dry_run=_env_bool("DRY_RUN", False),
            mode=(_env("MODE") or "digest").lower(),
            state_path=pathlib.Path(_env("STATE_PATH") or (ROOT / "state" / "sent.json")),
            sections=sections,
            sources=sources,
            source_priority=list(raw.get("source_priority") or []),
            world_source_priority=list(raw.get("world_source_priority") or []),
            block_keywords=list(raw.get("block_keywords") or []),
            hk_source_keywords=list((raw.get("classify") or {}).get("hk_source_keywords") or []),
            hk_title_keywords=list((raw.get("classify") or {}).get("hk_title_keywords") or []),
            overseas_source_keywords=list(
                (raw.get("classify") or {}).get("overseas_source_keywords") or []
            ),
            foreign_title_keywords=list(
                (raw.get("classify") or {}).get("foreign_title_keywords") or []
            ),
            block_sources=list(raw.get("block_sources") or []),
            max_title_chars=_env_int("MAX_TITLE_CHARS", int(raw.get("max_title_chars", 68))),
            disable_preview=_env_bool("DISABLE_PREVIEW", True),
            quiet_hours=quiet_hours,
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.dry_run:
            if not self.bot_token:
                errors.append("缺少 TELEGRAM_BOT_TOKEN（@BotFather 開 bot 拎）")
            if not self.chat_ids:
                errors.append("缺少 TELEGRAM_CHAT_IDS（channel 用 @你的channel名，個人/群組用數字 ID）")
        if not self.sources:
            errors.append("config.yaml 入面冇任何新聞來源")
        if not self.sections:
            errors.append("config.yaml 入面冇啟用任何版塊")
        return errors


def parse_hour_range(spec: str) -> list[int]:
    """把 "0-6" / "1,2,3" / "23-2" 轉成香港時間的小時清單。"""
    spec = (spec or "").strip()
    if not spec:
        return []
    hours: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            try:
                start, end = int(start_s), int(end_s)
            except ValueError:
                continue
            h = start
            while True:
                hours.add(h % 24)
                if h % 24 == end % 24:
                    break
                h = (h + 1) % 24
        else:
            try:
                hours.add(int(part) % 24)
            except ValueError:
                continue
    return sorted(hours)
