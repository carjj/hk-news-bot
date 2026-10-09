#!/usr/bin/env python3
"""每小時抓取香港及國際中文新聞 → 推送去 Telegram。

用法：
    python main.py                 # 正常推送（需要 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS）
    python main.py --dry-run       # 唔發送，淨係 print 出嚟睇效果
    python main.py --dry-run --save-sample out/sample.html
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
from datetime import datetime, timezone

from newsbot import cluster as cluster_mod
from newsbot.classify import reclassify
from newsbot.cluster import Story, attach_also, rank
from newsbot.config import HKT, Config
from newsbot.dedupe import SentStore
from newsbot.fetcher import fetch_all
from newsbot.filters import basic_filters
from newsbot.formatter import build_digest, build_individual
from newsbot.telegram import Bot, TelegramError, explain_error

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

    stories = cluster_mod.cluster(items, cfg)
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
