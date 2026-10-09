#!/usr/bin/env python3
"""中文新聞 Telegram 推送 —— 【單檔案版 / Standalone】

成個 bot 打包喺呢一個檔案入面，唔使 newsbot/ 資料夾、唔使 config.yaml。
放喺邊度都行得通：python main.py

用法：
    python main.py                  # 正常推送
    python main.py --dry-run        # 只預覽唔發送

可選：如果同一個資料夾有 config.yaml，會自動用佢（方便日後改設定）。
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import pathlib
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import yaml

# ------------------------------------------------------------------
#  內置設定（config.yaml 唔存在時用呢份）
# ------------------------------------------------------------------
CONFIG_YAML = r"""

# ============================================================
#  新聞來源設定  ·  全部經過實測可用（繁簡中文）
#  你可以自由增刪；category 決定會放入邊個版塊
# ============================================================

settings:
  # 每次推送最多幾單新聞（各版塊相加）
  max_total: 20
  # 同一個版塊入面，同一間媒體最多出幾單（避免單一媒體洗版）
  max_per_source: 3
  # 兩次推送之間最短相隔幾多分鐘（防止 GitHub cron + cron-job.org 重複推）
  min_interval_minutes: 45
  # 只推送呢個小時數內發佈 / 更新的新聞（舊嘢唔推）
  max_age_hours: 12
  # 相似標題視為「同一單新聞」的門檻（0–1，越大越嚴）
  dupe_threshold: 0.42
  # 標題最少要有幾多成中文字先當中文（濾走英文新聞）
  cjk_min_ratio: 0.25
  # 冇新新聞時唔好出空訊息
  skip_if_empty: true

# 版塊：決定推送順序、數量同開關
sections:
  - key: hk
    title: "🇭🇰 香港"
    limit: 10
    enabled: true
  - key: world
    title: "🌍 國際"
    limit: 10
    enabled: true
  - key: finance
    title: "💰 財經"
    limit: 3
    enabled: false      # 想要財經版塊改做 true
  - key: tech
    title: "🔬 科技"
    limit: 3
    enabled: false      # 想要科技版塊改做 true

# 同一單新聞有幾間媒體報道時，優先顯示邊間（越前越優先）
source_priority:
  - 香港電台
  - RTHK
  - 香港01
  - 明報
  - 星島頭條
  - 星島
  - 信報
  - 東方日報
  - 有線新聞
  - Now 新聞
  - 香港經濟日報
  - 頭條日報
  - BBC
  - 德國之聲
  - RFI
  - 美國之音
  - 中央社
  - 公視
  - 聯合報
  - 自由時報
  - ETtoday
  - Yahoo
  - Google News

# 自動判斷「呢單係香港新聞定國際新聞」
classify:
  # 標題有這些字 → 明顯係外地事件（即使由香港媒體報道，都歸國際版）
  foreign_title_keywords:
    - 美國
    - 中國
    - 內地
    - 大陸
    - 台灣
    - 台北
    - 高雄
    - 日本
    - 東京
    - 韓國
    - 首爾
    - 北韓
    - 平壤
    - 俄羅斯
    - 莫斯科
    - 烏克蘭
    - 基輔
    - 以色列
    - 加沙
    - 伊朗
    - 伊拉克
    - 敘利亞
    - 法國
    - 巴黎
    - 德國
    - 柏林
    - 英國
    - 倫敦
    - 歐盟
    - 北約
    - 聯合國
    - 印度
    - 東盟
    - 澳洲
    - 特朗普
    - 普京
    - 澤連斯基
    - 習近平
    - 白宮
    - 五角大廈
    - 加州
    - 紐約
  # 來源名有這些字 → 香港新聞
  hk_source_keywords:
    - 香港01
    - 香港電台
    - RTHK
    - 星島頭條
    - 頭條日報
    - 明報
    - 東方日報
    - 信報
    - Now 新聞
    - 有線新聞
    - 香港經濟日報
    - 巴士的報
    - 點新聞
    - 香港商報
    - 文匯報
    - 大公報
    - 無綫
    - TVB
    - 橙新聞
    - 香港
    - 港聞
    - 港股
  # 來源名有這些字 → 海外華文媒體，一律唔當香港新聞
  overseas_source_keywords:
    - 加拿大
    - 溫哥華
    - 多倫多
    - 卡加利
    - 美西
    - 美東
    - 紐約
    - 三藩市
    - 舊金山
    - 洛杉磯
    - 澳洲
    - 悉尼
    - 墨爾本
    - 紐西蘭
    - 英國
    - 倫敦
    - 新加坡
    - 馬來西亞
    - 歐洲
  # 標題有這些字 → 香港新聞
  hk_title_keywords:
    - 香港
    - 港鐵
    - 港島
    - 九龍
    - 新界
    - 屯門
    - 沙田
    - 荃灣
    - 觀塘
    - 元朗
    - 大埔
    - 旺角
    - 中環
    - 灣仔
    - 銅鑼灣
    - 深水埗
    - 將軍澳
    - 天水圍
    - 機場
    - 特區政府
    - 特首
    - 行政長官
    - 立法會
    - 區議會
    - 議員
    - 政府總部
    - 房屋局
    - 房委會
    - 公屋
    - 居屋
    - 醫管局
    - 康文署
    - 入境處
    - 海關
    - 警務處
    - 警方
    - 廉政公署
    - 天文台
    - 施政報告
    - 財政預算案
    - 財政司
    - 恒指
    - 港交所
    - 北水
    - 強積金
    - 皇崗
    - 深圳灣
    - 高鐵西九

# 國際版塊專用：邊間媒體優先（國際通訊社行先，香港媒體報道國際新聞排後）
world_source_priority:
  - BBC
  - 德國之聲
  - RFI
  - 美國之音
  - 中央社
  - 公視
  - 聯合報
  - 自由時報
  - ETtoday
  - 香港01
  - 星島頭條
  - 香港電台
  - 明報
  - 東方日報
  - 信報
  - Now 新聞
  - 有線新聞
  - 頭條日報
  - 香港經濟日報
  - AM730
  - Yahoo
  - Google News

# 標題顯示上限（太長嘅節目表／數據標題會被截短）
max_title_chars: 68

# 來源名有這些字 → 成個媒體跳過（財經數據頁、海外華人社區生活資訊等）
block_sources:
  # 財經數據頁（唔係新聞）
  - Investing.com
  - 智通財經
  - Yahoo奇摩股市
  - 鉅亨網
  # 海外華人社區生活資訊門戶（想保留自行刪除）
  - 加拿大星島日報
  - Sing Tao Daily 星島日報加拿大
  - 加西网
  - 加西網
  - 溫哥華
  - 多倫多
  - 超級生活
  - 51.ca
  - 約克論壇

# 標題含以下關鍵字直接丟棄（廣告 / 副刊 / 垃圾內容）
block_keywords:
  - 副刊
  - 專欄
  - 星座
  - 運程
  - 生肖
  - 塔羅
  - 限時優惠
  - 折扣碼
  - 優惠碼
  - 抽獎
  - 送禮
  - 賽馬會
  - 六合彩
  - 波盤
  - 足球推介
  - 社評摘要
  - 【重溫】
  - 持股解析
  - 中文廣播
  - 中文广播
  - 節目預告
  - 系統維護
  - 暫停服務
  - 招募義工
  - 導賞團
  - 公開講座
  - 今期號碼
  - 讀者投稿
  # 生活消閒／開箱文（唔係新聞）
  - 一次玩
  - 這樣玩
  - 好玩
  - 景點
  - 打卡
  - 美食
  - 開箱
  - CP值
  - 比價
  - 團購
  - 網購
  - 折扣
  - 穿搭
  - 減肥
  - 養生
  - 命理
  - 開運
  - 招財
  - 好市多
  - 團購
  - 試用心得
  - 評測
  - 超商
  - 手搖飲

sources:
  # ---------- 香港 ----------
  - name: "Google 新聞 · 香港頭條"
    url: "https://news.google.com/rss?hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: hk

  - name: "Google 新聞 · 港聞"
    url: "https://news.google.com/rss/headlines/section/topic/NATION?hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: hk

  - name: "Google 新聞 · 香港 01"
    url: "https://news.google.com/rss/search?q=site:hk01.com&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: hk

  - name: "Google 新聞 · 香港電台"
    url: "https://news.google.com/rss/search?q=site:rthk.hk&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: hk

  - name: "Google 新聞 · 星島頭條"
    url: "https://news.google.com/rss/search?q=site:stheadline.com&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: hk

  - name: "Google 新聞 · 香港突發"
    url: "https://news.google.com/rss/search?q=%E9%A6%99%E6%B8%AF+%E7%AA%81%E7%99%BC+when:12h&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: hk

  # ---------- 國際 ----------
  - name: "Google 新聞 · 國際"
    url: "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: world

  - name: "Google 新聞 · 兩岸"
    url: "https://news.google.com/rss/search?q=%E5%85%A9%E5%B2%B8+when:12h&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: world

  - name: "BBC 中文"
    url: "https://feeds.bbci.co.uk/zhongwen/trad/rss.xml"
    category: world

  - name: "德國之聲中文"
    url: "https://rss.dw.com/rdf/rss-chi-all"
    category: world

  - name: "RFI 法國國際廣播（中文）"
    url: "https://www.rfi.fr/cn/general/rss"
    category: world

  - name: "美國之音中文"
    url: "https://www.voachinese.com/rss/"
    category: world

  - name: "中央社 · 政治"
    url: "https://feeds.feedburner.com/rsscna/politics"
    category: world

  - name: "中央社 · 文化"
    url: "https://feeds.feedburner.com/rsscna/culture"
    category: world

  - name: "ETtoday 新聞雲"
    url: "https://feeds.feedburner.com/ettoday/news"
    category: world

  - name: "自由時報"
    url: "https://news.ltn.com.tw/rss/all.xml"
    category: world

  - name: "公視新聞網"
    url: "https://news.pts.org.tw/xml/newsfeed.xml"
    category: world

  # ---------- 財經（要開版塊先會出）----------
  - name: "Google 新聞 · 港股財經"
    url: "https://news.google.com/rss/search?q=%E6%B8%AF%E8%82%A1+when:12h&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: finance

  - name: "Google 新聞 · 財經"
    url: "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: finance

  - name: "中央社 · 財經"
    url: "https://feeds.feedburner.com/rsscna/finance"
    category: finance

  # ---------- 科技（要開版塊先會出）----------
  - name: "Google 新聞 · 科技"
    url: "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    category: tech

  - name: "中央社 · 科技"
    url: "https://feeds.feedburner.com/rsscna/technology"
    category: tech

"""


# ==================================================================
#  以下係程式本體（由 newsbot/ 各個模組合併而成）
# ==================================================================



# ===== config.py =====

import logging
import os
import pathlib
from dataclasses import dataclass, field
from datetime import timedelta, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parent

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
        else:
            if CONFIG_YAML:
                logging.getLogger("newsbot").warning("搵唔到 config.yaml，改用內置設定")
                raw = yaml.safe_load(CONFIG_YAML) or {}

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


# ===== models.py =====

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


# ===== fetcher.py =====

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import requests


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


# ===== filters.py =====

import logging
import re
import unicodedata


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


# ===== classify.py =====

import logging


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


# ===== cluster.py =====

import logging
from dataclasses import dataclass, field


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


# ===== dedupe.py =====

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


# ===== formatter.py =====

from datetime import datetime


TELEGRAM_LIMIT = 3900  # 官方上限 4096，留啲緩衝


def esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def ago(item: Item) -> str:
    hours = item.age_hours
    if hours < 1:
        mins = max(1, int(hours * 60))
        return f"{mins} 分鐘前"
    if hours < 24:
        return f"{int(hours)} 小時前"
    return f"{int(hours // 24)} 日前"


def hk_time(dt: datetime) -> str:
    local = dt.astimezone(HKT)
    return f"{local.month}月{local.day}日 {local.hour:02d}:{local.minute:02d}"


def _item_line(index: int, item: Item, with_summary: bool = False) -> str:
    line = f'{index}. <a href="{esc(item.link)}">{esc(item.title)}</a>\n'
    meta = f"    <i>{esc(item.source)} · {ago(item)}</i>"
    if item.also:
        extras = " ".join(
            f'<a href="{esc(url)}">{esc(name)}</a>' for name, url in item.also[:2]
        )
        extra_names = "、".join(name for name, _ in item.also)
        meta += f" · 另見：{extras}" if extras else f" · 另見：{esc(extra_names)}"
    line += meta + "\n"
    if with_summary and item.summary and len(item.summary) > 30:
        summary = item.summary[:110].rstrip()
        line += f"    {esc(summary)}…\n"
    return line


def build_digest(sections: list[dict], cfg: Config, now: datetime) -> list[str]:
    """sections = [{"title": "🇭🇰 香港", "items": [Item, ...]}, ...]

    會自動按 Telegram 4096 字上限逐條拆成幾則訊息，每則都保留版塊標題。
    """
    header = (
        f"🗞️ <b>中文新聞速報</b>\n"
        f"<i>{esc(hk_time(now))} (HKT) · 香港及國際</i>\n"
    )
    cont_header = "🗞️ <b>中文新聞速報（續）</b>\n"
    footer = "\n─────────\n🤖 每小時自動更新 · 只推中文報道"

    chunks: list[str] = []
    current = header
    started = False

    for sec in sections:
        if not sec["items"]:
            continue
        for i, item in enumerate(sec["items"], start=1):
            line = _item_line(i, item)
            piece = f'\n{sec["title"]}\n{line}' if i == 1 else line
            if started and len(current) + len(piece) > TELEGRAM_LIMIT:
                chunks.append(current.rstrip())
                # 新一則訊息要重複版塊標題（標「續」），否則編號會斷層
                current = cont_header + f'{sec["title"]}（續）\n{line}'
            else:
                current += piece
            started = True

    if len(current) + len(footer) > TELEGRAM_LIMIT and started:
        chunks.append(current.rstrip())
        current = footer
    else:
        current += footer
    chunks.append(current.rstrip())

    return [c for c in chunks if c.strip()]


def build_individual(item: Item, section_title: str) -> str:
    text = f'{section_title}\n<b><a href="{esc(item.link)}">{esc(item.title)}</a></b>\n'
    if item.summary:
        text += f"{esc(item.summary[:180])}\n"
    text += f"<i>{esc(item.source)} · {ago(item)}</i>"
    if item.also:
        extras = " ".join(
            f'<a href="{esc(url)}">{esc(name)}</a>' for name, url in item.also[:3]
        )
        if extras:
            text += f"\n另見：{extras}"
    return text


# ===== telegram.py =====

import logging
import time

import requests

log = logging.getLogger("newsbot")

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 20


class TelegramError(RuntimeError):
    pass


def explain_error(desc: str) -> list[str]:
    """把 Telegram 嘅錯誤碼翻譯成人話 + 點樣執。"""
    hints: list[str] = []
    if "401" in desc or "Unauthorized" in desc:
        hints.append("Token 錯咗／抄漏。去 @BotFather → /mybots → 揀你個 bot → API Token 重新抄一次（要有中間個「:」）")
    if "403" in desc or "Forbidden" in desc:
        hints.append("Bot 未做 Channel Admin，或者未入群組。Channel：Settings → Administrators → 加 Bot 並開 Post Messages")
    if "400" in desc:
        if "chat not found" in desc:
            hints.append("Chat ID 錯。Public channel 要連埋 @（例如 @my_channel）；群組 ID 係 -100 開頭嘅負數")
        else:
            hints.append("Chat ID 格式有問題，或者訊息內容唔合規格")
    if "429" in desc:
        hints.append("推得太密被限速，等一陣再試")
    if "group chat was upgraded" in desc or "migrated" in desc:
        hints.append("群組升級咗做超級群組，Chat ID 變咗，要重新拎過")
    return hints or ["睇上面錯誤碼對照 README 嘅常見問題，或者將 raw log 傳畀我睇"]


class Bot:
    def __init__(self, token: str, disable_preview: bool = True):
        self.token = token
        self.disable_preview = disable_preview

    def _call(self, method: str, payload: dict) -> dict:
        url = API.format(token=self.token, method=method)
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=TIMEOUT)
                data = resp.json()
                if data.get("ok"):
                    return data["result"]
                code = data.get("error_code")
                desc = data.get("description", "")
                # 429 限速：跟住 retry_after 等
                retry_after = (data.get("parameters") or {}).get("retry_after")
                if code == 429 and retry_after and attempt < 2:
                    log.warning("Telegram 限速，等 %s 秒再試", retry_after)
                    time.sleep(float(retry_after) + 1)
                    continue
                raise TelegramError(f"{code}: {desc}")
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(2 * (attempt + 1))
        raise TelegramError(f"Telegram API 連線失敗：{last_exc}")

    def send(self, chat_id: str, text: str) -> dict:
        return self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": self.disable_preview,
                "disable_notification": False,
            },
        )

    def get_me(self) -> dict:
        return self._call("getMe", {})

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict]:
        payload: dict = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        try:
            return self._call("getUpdates", payload)
        except TelegramError:
            return []


# ===== 主程式 =====

#!/usr/bin/env python3
"""每小時抓取香港及國際中文新聞 → 推送去 Telegram。

用法：
    python main.py                 # 正常推送（需要 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS）
    python main.py --dry-run       # 唔發送，淨係 print 出嚟睇效果
    python main.py --dry-run --save-sample out/sample.html
"""




log = logging.getLogger("newsbot")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def pick_sections(stories: list[Story], cfg: Config) -> tuple[list[dict], list[Story]]:
    """按版塊配額挑選新聞，回傳 (版塊內容, 實際會推送嘅 stories)。"""
    chosen: list[Story] = []
    blocks: list[dict] = []
    remaining = cfg.max_total

    for section in cfg.sections:
        if not section.enabled or remaining <= 0:
            continue
        bucket = [s for s in stories if s.category == section.key]
        # 每個版塊入面，同一間媒體最多出 cfg.max_per_source 單，避免洗版
        take: list[Story] = []
        per_source: dict[str, int] = {}
        for story in bucket:
            if len(take) >= min(section.limit, remaining):
                break
            src = story.main.source.lower()
            if per_source.get(src, 0) >= cfg.max_per_source:
                continue
            per_source[src] = per_source.get(src, 0) + 1
            take.append(story)
        if not take:
            continue
        chosen.extend(take)
        remaining -= len(take)
        blocks.append(
            {"key": section.key, "title": section.title, "items": [s.main for s in take]}
        )
    return blocks, chosen


def collect(
    cfg: Config, now: datetime, store: SentStore | None = None
) -> tuple[list[dict], list[Story], SentStore]:
    """抓取 → 過濾 → 分類 → 合併 → 去重 → 配額。唔做任何推送。"""
    store = store or SentStore(cfg.state_path)
    raw = fetch_all(cfg)
    items = basic_filters(raw, cfg)
    if not items:
        log.warning("冇抓到任何合適嘅中文新聞。")
        return [], [], store

    items = reclassify(items, cfg)

    stories = cluster(items, cfg)
    attach_also(stories)
    stories = rank(stories, cfg)

    fresh = [s for s in stories if not store.is_sent(s.uid)]
    log.info("扣除已推送，剩 %d 單新新聞", len(fresh))

    blocks, chosen = pick_sections(fresh, cfg)
    return blocks, chosen, store


def render(blocks: list[dict], cfg: Config, now: datetime) -> list[str]:
    if cfg.mode == "individual":
        messages: list[str] = []
        for block in blocks:
            for item in block["items"]:
                messages.append(build_individual(item, block["title"]))
        return messages
    return build_digest(blocks, cfg, now)


def run(cfg: Config, save_sample: str | None = None) -> int:
    now = datetime.now(timezone.utc)

    # 1) 寧靜時段（香港時間）唔推送
    if cfg.quiet_hours:
        hk_hour = now.astimezone(HKT).hour
        if hk_hour in cfg.quiet_hours:
            log.info("而家係香港時間 %d 點，屬於寧靜時段，跳過。", hk_hour)
            return 0

    # 1.5) 最短推送間隔鎖
    #      GitHub Actions 內置 cron + cron-job.org 會各 trigger 一次，
    #      呢個鎖確保同一個鐘唔會重複推送。
    store = SentStore(cfg.state_path)
    if not cfg.dry_run and store.last_push:
        gap_min = (now - store.last_push).total_seconds() / 60.0
        if gap_min < cfg.min_interval_minutes:
            log.info(
                "⏸️  上次推送係 %.0f 分鐘前（少過設定嘅 %d 分鐘），跳過，避免重複推送。",
                gap_min,
                cfg.min_interval_minutes,
            )
            return 0

    # 2) 抓取、過濾、去重
    blocks, chosen, store = collect(cfg, now, store)
    if not blocks:
        log.info("呢一小時冇新新聞，唔推送。")
        store.save()
        return 0

    # 3) 產生訊息
    messages = render(blocks, cfg, now)

    # 4) 推送 / 預覽
    if cfg.dry_run:
        print("\n" + "=" * 26 + " DRY RUN 預覽 " + "=" * 26)
        for i, msg in enumerate(messages, 1):
            print(f"\n----- 訊息 {i}/{len(messages)}（{len(msg)} 字）-----\n")
            print(msg)
        print("\n" + "=" * 66)
        if save_sample:
            path = pathlib.Path(save_sample)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() == ".html":
                path.write_text(to_html(messages), encoding="utf-8")
            else:
                path.write_text("\n\n<!-- ---- -->\n\n".join(messages), encoding="utf-8")
            log.info("範例已儲存 → %s", path)
    else:
        bot = Bot(cfg.bot_token, cfg.disable_preview)
        sent = 0
        try:
            for chat_id in cfg.chat_ids:
                for msg in messages:
                    bot.send(chat_id, msg)
                    sent += 1
        except TelegramError as exc:
            log.error("❌ Telegram 推送失敗：%s", exc)
            for hint in explain_error(str(exc)):
                log.error("   💡 %s", hint)
            return 2
        log.info("✅ 已推送 %d 則訊息到 %d 個目標", sent, len(cfg.chat_ids))

    # 5) 記錄，下個鐘唔會再推同一單
    if not cfg.dry_run:
        store.mark_push()
    store.mark([s.uid for s in chosen])
    store.save()
    log.info("完成：推送 %d 單新聞", len(chosen))
    return 0


def to_html(messages: list[str]) -> str:
    """把 Telegram HTML 訊息包成一個靚靚嘅預覽頁（純內嵌 CSS，可離線開）。"""
    cards = []
    for msg in messages:
        body = msg.replace("\n", "<br>")
        cards.append(
            f'<div class="msg"><div class="avatar">🗞️</div><div class="bubble">{body}</div></div>'
        )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Telegram 新聞推送預覽</title>
<style>
  body{{margin:0;padding:28px 16px;background:#0e1621;color:#e7edf3;
       font:15px/1.75 -apple-system,"PingFang HK","Microsoft JhengHei","Noto Sans TC",sans-serif;}}
  .wrap{{max-width:640px;margin:0 auto;}}
  h1{{font-size:17px;font-weight:600;color:#8fb4d9;margin:0 0 4px}}
  .sub{{font-size:13px;color:#6b7f93;margin-bottom:22px}}
  .msg{{display:flex;gap:10px;margin-bottom:18px}}
  .avatar{{width:36px;height:36px;border-radius:50%;background:#1f2c3a;display:flex;
           align-items:center;justify-content:center;font-size:18px;flex:0 0 36px}}
  .bubble{{background:#182533;border-radius:14px;border-top-left-radius:4px;
           padding:12px 15px;max-width:100%;word-break:break-word}}
  .bubble a{{color:#64b5f6;text-decoration:none}}
  .bubble a:hover{{text-decoration:underline}}
  .bubble i{{color:#7b8fa3}}
  code{{color:#ffb74d}}
</style></head><body><div class="wrap">
<h1>Telegram 推送預覽</h1>
<div class="sub">下面係 bot 實際會傳送去 Telegram 嘅訊息（HTML 格式原樣呈現）</div>
{''.join(cards)}
</div></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram 中文新聞每小時推送")
    parser.add_argument("--config", help="config.yaml 路徑")
    parser.add_argument("--dry-run", action="store_true", help="只預覽唔發送")
    parser.add_argument("--save-sample", help="dry-run 時把結果寫入檔案（.html 會出預覽頁）")
    args = parser.parse_args()

    setup_logging()

    cfg = Config.load(args.config)
    if args.dry_run:
        cfg.dry_run = True

    errors = cfg.validate()
    if errors:
        for err in errors:
            log.error("設定錯誤：%s", err)
        if not cfg.dry_run:
            log.error("提示：加 --dry-run 可以唔使 token 都睇到效果")
            return 1

    try:
        return run(cfg, args.save_sample)
    except Exception as exc:  # noqa: BLE001
        log.exception("執行失敗：%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

