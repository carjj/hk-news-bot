#!/usr/bin/env python3
"""可選：長期運行的 Telegram Bot（對話指令 + 每小時自動推送）

GitHub Actions 淨係做「定時推送」。如果你仲想用戶可以主動 /news 問新聞，
或者想唔使開 GitHub 都可以推送，就喺 Render / Railway / 自己部機跑呢個檔案：

    python bot.py

需要 .env 入面有 TELEGRAM_BOT_TOKEN。
"""

from __future__ import annotations

import json
import logging
import pathlib
import threading
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

from newsbot.config import HKT
from newsbot.telegram import Bot

load_dotenv()

ROOT = pathlib.Path(__file__).resolve().parent
SUBS_FILE = ROOT / "state" / "subscribers.json"
STATE_FILE = ROOT / "state" / "sent.json"

log = logging.getLogger("newsbot.bot")

HELP = (
    "🗞️ <b>中文新聞 bot</b>\n\n"
    "每小時自動推送香港及國際中文新聞。\n\n"
    "指令：\n"
    "/news — 即刻攞一次最新新聞\n"
    "/hk — 淨係香港新聞\n"
    "/world — 淨係國際新聞\n"
    "/finance — 財經新聞\n"
    "/tech — 科技新聞\n"
    "/stop — 停止自動推送\n"
    "/start — 重新訂閱\n"
    "/help — 說明"
)

SECTION_ALIASES = {
    "/news": "hk,world,finance,tech",
    "/hk": "hk",
    "/world": "world",
    "/finance": "finance",
    "/tech": "tech",
}


class Subscribers:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ids: list[str] = []
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self.ids = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.ids = []
        else:
            self.ids = []

    def save(self) -> None:
        self.path.write_text(
            json.dumps(sorted(set(self.ids)), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(self, chat_id) -> bool:
        key = str(chat_id)
        if key in self.ids:
            return False
        self.ids.append(key)
        self.save()
        return True

    def remove(self, chat_id) -> bool:
        key = str(chat_id)
        if key not in self.ids:
            return False
        self.ids.remove(key)
        self.save()
        return True


def build_config(sections: str, chat_ids: list[str], state_path: pathlib.Path):
    """動態建立 Config（唔改環境變數，方便一次過對唔同 chat 用唔同版塊）。"""
    from newsbot.config import Config

    cfg = Config.load()
    cfg.dry_run = False
    cfg.chat_ids = chat_ids
    if sections:
        wanted = {s.strip().lower() for s in sections.split(",") if s.strip()}
        cfg.sections = [s for s in cfg.sections if s.key in wanted]
    # 唔同版塊用唔同去重記錄，避免 /hk 食咗 /world 嘅額度
    cfg.state_path = state_path
    return cfg


def push_once(chat_ids: list[str], sections: str = "", force: bool = False,
              state_path: pathlib.Path = STATE_FILE) -> None:
    """跑一次抓取 + 推送。force=True 時無視去重記錄（畀 /news 之類嘅手動指令用）。"""
    from main import run

    cfg = build_config(sections, chat_ids, state_path)
    if force:
        # 臨時用一個空嘅 state，等手動指令一定有嘢出
        tmp = state_path.with_name(state_path.stem + "-manual.json")
        cfg.state_path = tmp
        cfg.max_age_hours = max(cfg.max_age_hours, 24)
    try:
        run(cfg)
    except Exception as exc:  # noqa: BLE001
        log.exception("推送失敗：%s", exc)


def hourly_loop(subs: Subscribers, minute: int = 8) -> None:
    """每小時喺 HKT 的 HH:MM 推一次。"""
    while True:
        now = datetime.now(HKT)
        target = now.replace(minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(hours=1)
        wait = (target - now).total_seconds()
        log.info("下次自動推送：%s（%.0f 分鐘後）", target.strftime("%H:%M HKT"), wait / 60)
        time.sleep(wait)
        if not subs.ids:
            log.info("未有訂閱者，跳過。")
            continue
        log.info("開始每小時推送 → %d 個目標", len(subs.ids))
        push_once(subs.ids)


def handle(command: str, chat, subs: Subscribers) -> str | None:
    """回傳要 reply 的文字；None 代表已經由 push_once 處理。"""
    chat_id = chat["id"]

    if command in ("/start", "/help"):
        subs.add(chat_id)
        return HELP
    if command == "/stop":
        subs.remove(chat_id)
        return "👋 已停止自動推送。想恢復隨時 /start"
    if command in SECTION_ALIASES:
        subs.add(chat_id)
        threading.Thread(
            target=push_once,
            args=([str(chat_id)], SECTION_ALIASES[command]),
            kwargs={"force": True},
            daemon=True,
        ).start()
        return "⏳ 搵緊最新中文新聞，等一陣…"
    return "唔係好明 🤔 試下 /help 睇有咩指令"


def main() -> None:
    import os

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    )
    load_dotenv()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("❌ 請先喺 .env 設定 TELEGRAM_BOT_TOKEN")

    bot = Bot(token)
    me = bot.get_me()
    log.info("Bot 已啟動：@%s", me.get("username"))

    subs = Subscribers(SUBS_FILE)

    # 環境變數入面有設定頻道嘅話，一齊自動推送
    extra = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
    for cid in extra:
        subs.add(cid)

    threading.Thread(target=hourly_loop, args=(subs,), daemon=True).start()

    offset = None
    log.info("開始接收訊息…")
    while True:
        try:
            updates = bot.get_updates(offset)
        except Exception as exc:  # noqa: BLE001
            log.warning("getUpdates 失敗：%s", exc)
            time.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            command = text.split()[0].split("@")[0].lower()
            try:
                reply = handle(command, msg["chat"], subs)
                if reply:
                    bot.send(str(msg["chat"]["id"]), reply)
            except Exception as exc:  # noqa: BLE001
                log.exception("處理 %s 失敗：%s", command, exc)


if __name__ == "__main__":
    main()
