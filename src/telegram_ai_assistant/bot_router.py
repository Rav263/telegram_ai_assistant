from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .security import BotAccessController


COMMANDS = {
    "/start": "help",
    "/help": "help",
    "/summary": "summary",
    "/tasks": "tasks",
    "/review": "review",
    "/backfill": "backfill",
    "/blacklist": "blacklist",
    "/settings": "settings",
    "/health": "health",
    "/logs": "logs",
}


class BotRouter:
    def __init__(
        self,
        *,
        access: BotAccessController,
        bot_api: Any,
        services: Any,
        audit_log: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.access = access
        self.bot_api = bot_api
        self.services = services
        self.audit_log = audit_log

    def handle_update(self, update: Mapping[str, Any]) -> None:
        if "message" in update:
            self._handle_message(update["message"])
            return
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])

    def _handle_message(self, message: Mapping[str, Any]) -> None:
        user_id = int(message.get("from", {}).get("id", 0))
        if not self.access.is_allowed(user_id):
            self._audit_denied(user_id)
            return

        chat_id = int(message.get("chat", {}).get("id", 0))
        command = _extract_command(str(message.get("text", "")))
        method_name = COMMANDS.get(command)
        if method_name is None:
            return

        response = getattr(self.services, method_name)()
        self._send_response(chat_id=chat_id, response=response)

    def _handle_callback(self, callback_query: Mapping[str, Any]) -> None:
        user_id = int(callback_query.get("from", {}).get("id", 0))
        callback_id = str(callback_query.get("id", ""))
        if not self.access.is_allowed(user_id):
            self._audit_denied(user_id)
            if callback_id:
                self.bot_api.answer_callback_query(
                    callback_query_id=callback_id,
                    text="Access denied",
                    show_alert=True,
                )
            return

        data = str(callback_query.get("data", ""))
        parts = data.split(":", 2)
        if len(parts) != 3:
            return

        kind, action, target_id = parts
        if kind == "menu":
            self._handle_menu_callback(callback_query=callback_query, callback_id=callback_id, action=action)
        elif kind == "review":
            answer_text = str(self.services.handle_review_callback(action, target_id))
        elif kind == "status":
            answer_text = str(self.services.handle_status_callback(action, target_id))
        elif kind == "backfill":
            response = self.services.handle_backfill_callback(action, target_id)
            self._handle_callback_response(callback_query=callback_query, callback_id=callback_id, response=response)
            return
        elif kind == "bf":
            response = self.services.handle_backfill_callback(action, target_id)
            self._handle_callback_response(callback_query=callback_query, callback_id=callback_id, response=response)
            return
        elif kind == "policy":
            response = self.services.handle_policy_callback(action, target_id)
            self._handle_callback_response(callback_query=callback_query, callback_id=callback_id, response=response)
            return
        else:
            return

        if kind != "menu":
            self.bot_api.answer_callback_query(callback_query_id=callback_id, text=answer_text)

    def _handle_menu_callback(self, *, callback_query: Mapping[str, Any], callback_id: str, action: str) -> None:
        method_name = {
            "summary": "summary",
            "tasks": "tasks",
            "review": "review",
            "backfill": "backfill",
            "health": "health",
            "logs": "logs",
            "settings": "settings",
            "blacklist": "blacklist",
            "help": "help",
        }.get(action)
        if method_name is None:
            return

        response = getattr(self.services, method_name)()
        if callback_id:
            self.bot_api.answer_callback_query(callback_query_id=callback_id, text="Opened.")

        message = callback_query.get("message", {})
        chat_id = int(message.get("chat", {}).get("id", 0))
        if chat_id:
            self._send_response(chat_id=chat_id, response=response)

    def _handle_callback_response(
        self,
        *,
        callback_query: Mapping[str, Any],
        callback_id: str,
        response: Any,
    ) -> None:
        if not hasattr(response, "text"):
            self.bot_api.answer_callback_query(callback_query_id=callback_id, text=str(response))
            return

        self.bot_api.answer_callback_query(callback_query_id=callback_id, text="Opened.")
        message = callback_query.get("message", {})
        chat_id = int(message.get("chat", {}).get("id", 0))
        if chat_id:
            self._send_response(chat_id=chat_id, response=response)

    def _audit_denied(self, user_id: int) -> None:
        if self.audit_log is not None:
            self.audit_log({"event": "denied", "user_id": user_id})

    def _send_response(self, *, chat_id: int, response: Any) -> None:
        text = str(getattr(response, "text", response))
        reply_markup = getattr(response, "reply_markup", None)
        send_long_message = getattr(self.bot_api, "send_long_message", None)
        if callable(send_long_message):
            send_long_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            return
        self.bot_api.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


def _extract_command(text: str) -> str:
    command = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    if "@" in command:
        command = command.split("@", 1)[0]
    return command
