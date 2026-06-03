from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib import request


class BotApiError(RuntimeError):
    pass


class TelegramBotApi:
    def __init__(
        self,
        *,
        token: str,
        transport=None,
        base_url: str = "https://api.telegram.org",
    ):
        self.token = token
        self.transport = transport or _urllib_transport
        self.base_url = base_url.rstrip("/")

    def send_message(self, *, chat_id: int, text: str, reply_markup: Mapping[str, Any] | None = None):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", payload)

    def get_updates(self, *, offset: int | None = None, timeout: int = 25):
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        return self._post("getUpdates", payload)

    def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ):
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text is not None:
            payload["text"] = text
        return self._post("answerCallbackQuery", payload)

    def edit_message_reply_markup(
        self,
        *,
        chat_id: int,
        message_id: int,
        reply_markup: Mapping[str, Any] | None = None,
    ):
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._post("editMessageReplyMarkup", payload)

    def _post(self, endpoint: str, payload: Mapping[str, Any]):
        url = f"{self.base_url}/bot{self.token}/{endpoint}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        response = self.transport(url, body, headers)
        if isinstance(response, Mapping) and response.get("ok") is False:
            raise BotApiError(str(response.get("description", "Telegram Bot API request failed")))
        if isinstance(response, Mapping) and "result" in response:
            return response["result"]
        return response


def _urllib_transport(url: str, body: bytes, headers: Mapping[str, str]):
    http_request = request.Request(url, data=body, headers=dict(headers), method="POST")
    with request.urlopen(http_request) as response:
        return json.loads(response.read().decode("utf-8"))
