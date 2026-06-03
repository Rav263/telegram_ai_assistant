import json
import unittest

from telegram_ai_assistant.bot_api import TelegramBotApi


class FakeTransport:
    def __init__(self):
        self.calls = []

    def __call__(self, url: str, body: bytes, headers):
        self.calls.append(
            {
                "url": url,
                "payload": json.loads(body.decode("utf-8")),
                "headers": dict(headers),
            }
        )
        return {"ok": True, "result": {"id": "result-1"}}


class TelegramBotApiTests(unittest.TestCase):
    def test_send_message_posts_expected_json(self):
        transport = FakeTransport()
        api = TelegramBotApi(token="bot-token", transport=transport)

        api.send_message(chat_id=123, text="hello", reply_markup={"inline_keyboard": []})

        self.assertEqual(
            transport.calls[0]["url"],
            "https://api.telegram.org/botbot-token/sendMessage",
        )
        self.assertEqual(
            transport.calls[0]["payload"],
            {
                "chat_id": 123,
                "text": "hello",
                "reply_markup": {"inline_keyboard": []},
            },
        )
        self.assertEqual(transport.calls[0]["headers"]["Content-Type"], "application/json")

    def test_answer_callback_query_posts_expected_json(self):
        transport = FakeTransport()
        api = TelegramBotApi(token="bot-token", transport=transport)

        api.answer_callback_query(
            callback_query_id="callback-1",
            text="applied",
            show_alert=True,
        )

        self.assertEqual(
            transport.calls[0]["url"],
            "https://api.telegram.org/botbot-token/answerCallbackQuery",
        )
        self.assertEqual(
            transport.calls[0]["payload"],
            {
                "callback_query_id": "callback-1",
                "text": "applied",
                "show_alert": True,
            },
        )

    def test_edit_message_reply_markup_posts_expected_json(self):
        transport = FakeTransport()
        api = TelegramBotApi(token="bot-token", transport=transport)

        api.edit_message_reply_markup(
            chat_id=123,
            message_id=456,
            reply_markup={"inline_keyboard": [[{"text": "Done", "callback_data": "x"}]]},
        )

        self.assertEqual(
            transport.calls[0]["url"],
            "https://api.telegram.org/botbot-token/editMessageReplyMarkup",
        )
        self.assertEqual(
            transport.calls[0]["payload"],
            {
                "chat_id": 123,
                "message_id": 456,
                "reply_markup": {"inline_keyboard": [[{"text": "Done", "callback_data": "x"}]]},
            },
        )

    def test_get_updates_posts_expected_json_and_returns_result(self):
        transport = FakeTransport()
        api = TelegramBotApi(token="bot-token", transport=transport)

        result = api.get_updates(offset=42, timeout=15)

        self.assertEqual(result, {"id": "result-1"})
        self.assertEqual(
            transport.calls[0]["url"],
            "https://api.telegram.org/botbot-token/getUpdates",
        )
        self.assertEqual(
            transport.calls[0]["payload"],
            {
                "offset": 42,
                "timeout": 15,
                "allowed_updates": ["message", "callback_query"],
            },
        )


if __name__ == "__main__":
    unittest.main()
