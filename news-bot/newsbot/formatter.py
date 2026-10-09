from __future__ import annotations

from datetime import datetime

from .config import HKT, Config
from .models import Item

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
