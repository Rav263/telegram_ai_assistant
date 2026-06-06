import json
import unittest

from telegram_ai_assistant import bot_api
from telegram_ai_assistant.bot_api import TelegramBotApi


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def read(self):
        return json.dumps({"ok": True, "result": {"id": "proxied"}}).encode("utf-8")


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

    def test_urllib_proxy_transport_uses_http_and_https_proxy(self):
        captured = {}
        original_proxy_handler = bot_api.request.ProxyHandler
        original_build_opener = bot_api.request.build_opener

        class FakeProxyHandler:
            def __init__(self, proxies):
                captured["proxies"] = proxies

        class FakeOpener:
            def open(self, http_request):
                captured["url"] = http_request.full_url
                return FakeResponse()

        bot_api.request.ProxyHandler = FakeProxyHandler
        bot_api.request.build_opener = lambda handler: FakeOpener()
        try:
            transport = bot_api._urllib_proxy_transport("http://proxy.local:8080")
            result = transport("https://api.telegram.org/bot-token/getUpdates", b"{}", {})
        finally:
            bot_api.request.ProxyHandler = original_proxy_handler
            bot_api.request.build_opener = original_build_opener

        self.assertEqual(result, {"ok": True, "result": {"id": "proxied"}})
        self.assertEqual(
            captured["proxies"],
            {
                "http": "http://proxy.local:8080",
                "https": "http://proxy.local:8080",
            },
        )
        self.assertEqual(captured["url"], "https://api.telegram.org/bot-token/getUpdates")

    def test_send_long_message_splits_text_and_keeps_markup_on_last_chunk(self):
        transport = FakeTransport()
        api = TelegramBotApi(token="bot-token", transport=transport)

        api.send_long_message(
            chat_id=123,
            text="abcdef",
            reply_markup={"inline_keyboard": []},
            max_length=3,
        )

        self.assertEqual(
            [call["payload"] for call in transport.calls],
            [
                {"chat_id": 123, "text": "abc"},
                {
                    "chat_id": 123,
                    "text": "def",
                    "reply_markup": {"inline_keyboard": []},
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
