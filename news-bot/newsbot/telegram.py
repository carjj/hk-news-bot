from __future__ import annotations

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
