#!/usr/bin/env python3
"""設定體檢：唔使真推送，就檢查 Token、Chat ID、Bot 權限對唔對。

只會印出長度同 username／channel 名，唔會洩漏任何秘密。
GitHub Actions 會自動跑呢一步。手動都可以跑：python check_setup.py
"""

from __future__ import annotations

import os
import sys

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def mask(value: str) -> str:
    """淨係露頭尾，中間打格仔。"""
    if not value:
        return "(空)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-3:]} (長度 {len(value)})"


def call(token: str, method: str, **params) -> dict:
    resp = requests.post(API.format(token=token, method=method), json=params, timeout=20)
    try:
        return resp.json()
    except Exception:
        return {"ok": False, "description": f"HTTP {resp.status_code}"}


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chats_raw = os.environ.get("TELEGRAM_CHAT_IDS", "").strip()

    print("=" * 58)
    print("🔍 設定體檢")
    print("=" * 58)

    ok = True

    # 1) 環境變數
    print("\n【1】環境變數")
    print(f"  TELEGRAM_BOT_TOKEN : {'✅ 已設定  ' + mask(token) if token else '❌ 未設定'}")
    if not token:
        print("      → 去 Settings → Secrets and variables → Actions 加 TELEGRAM_BOT_TOKEN")
        print("      → 搵 @BotFather 傾 /mybots 可以攞返 token")
        ok = False

    chat_ids = [c.strip() for c in chats_raw.split(",") if c.strip()]
    print(f"  TELEGRAM_CHAT_IDS  : {'✅ 已設定（' + str(len(chat_ids)) + ' 個目標）' if chat_ids else '❌ 未設定'}")
    for cid in chat_ids:
        print(f"      · {mask(cid)}")
    if not chat_ids:
        print("      → 加 TELEGRAM_CHAT_IDS：public channel 填 @channelname，群組/私人填數字 ID")
        ok = False

    if not token:
        print("\n❌ 冇 Token，檢查唔到落去。請先設定 Secrets。")
        return 1

    # 2) Token 有冇效
    print("\n【2】Bot Token 有冇效")
    me = call(token, "getMe")
    if me.get("ok"):
        r = me["result"]
        print(f"  ✅ Token 有效：@{r.get('username')}（{r.get('first_name')}）")
    else:
        code = me.get("error_code")
        print(f"  ❌ Token 無效：{code} {me.get('description')}")
        if code == 401:
            print("      → Token 錯咗或者抄漏。去 @BotFather → /mybots → 揀你個 bot → API Token 重新抄一次")
            print("      → 注意：Token 中間有個「:」，前後都唔可以有空格")
        ok = False

    # 3) 每個推送目標
    if chat_ids:
        print("\n【3】推送目標（Bot 有冇權限寫嘢）")
        for cid in chat_ids:
            chat = call(token, "getChat", chat_id=cid)
            if chat.get("ok"):
                r = chat["result"]
                title = r.get("title") or r.get("first_name") or r.get("username")
                print(f"  ✅ {mask(cid)} → 「{title}」（{r.get('type')}）")
            else:
                code = chat.get("error_code")
                desc = chat.get("description", "")
                print(f"  ❌ {mask(cid)} → {code} {desc}")
                if code == 400:
                    print("      → Chat ID 錯／搵唔到。public channel 要連埋 @；群組 ID 係負數（-100開頭）")
                elif code == 403:
                    print("      → Bot 未入到去。Channel 要加 Bot 做 Admin 並開 Post Messages")
                ok = False

            # 試吓有冇權限（channel 要 admin，群組要夠權）
            if chat.get("ok") and chat["result"].get("type") == "channel":
                admins = call(token, "getChatAdministrators", chat_id=cid)
                if admins.get("ok"):
                    me_id = me.get("result", {}).get("id")
                    is_admin = any(
                        (a.get("user") or {}).get("id") == me_id for a in admins["result"]
                    )
                    if is_admin:
                        print("      ✅ Bot 係 Admin，可以發文")
                    else:
                        print("      ❌ Bot 唔係 Admin → Channel 設定 → Administrators → 加 Bot")
                        ok = False

    print("\n" + "=" * 58)
    if ok:
        print("🎉 全部設定正確！應該可以正常推送。")
    else:
        print("⚠️  上面有項目要執返好，跟住提示改就得。")
    print("=" * 58)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
