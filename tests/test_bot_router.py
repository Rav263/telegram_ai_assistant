import unittest

from telegram_ai_assistant.bot_router import BotRouter
from telegram_ai_assistant.security import BotAccessController


class FakeBotApi:
    def __init__(self):
        self.sent_messages = []
        self.answered_callbacks = []
        self.edited_reply_markup = []

    def send_message(self, *, chat_id: int, text: str, reply_markup=None):
        self.sent_messages.append((chat_id, text, reply_markup))
        return {"message_id": len(self.sent_messages)}

    def send_long_message(self, *, chat_id: int, text: str, reply_markup=None):
        return self.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

    def answer_callback_query(self, *, callback_query_id: str, text: str | None = None, show_alert=False):
        self.answered_callbacks.append((callback_query_id, text, show_alert))
        return True

    def edit_message_reply_markup(self, *, chat_id: int, message_id: int, reply_markup=None):
        self.edited_reply_markup.append((chat_id, message_id, reply_markup))
        return True


class FakeBotServices:
    def __init__(self):
        self.calls = []

    def summary(self) -> str:
        self.calls.append(("summary",))
        return "summary response"

    def tasks(self) -> str:
        self.calls.append(("tasks",))
        return "tasks response"

    def review(self) -> str:
        self.calls.append(("review",))
        return "review response"

    def backfill(self) -> str:
        self.calls.append(("backfill",))
        return "backfill response"

    def blacklist(self) -> str:
        self.calls.append(("blacklist",))
        return "blacklist response"

    def settings(self) -> str:
        self.calls.append(("settings",))
        return "settings response"

    def health(self) -> str:
        self.calls.append(("health",))
        return "health response"

    def logs(self) -> str:
        self.calls.append(("logs",))
        return "logs response"

    def help(self) -> str:
        self.calls.append(("help",))
        return "help response"

    def handle_review_callback(self, action: str, item_id: str) -> str:
        self.calls.append(("review_callback", action, item_id))
        return "review callback response"

    def handle_status_callback(self, status: str, item_id: str) -> str:
        self.calls.append(("status_callback", status, item_id))
        return "status callback response"

    def handle_backfill_callback(self, action: str, job_id: str) -> str:
        self.calls.append(("backfill_callback", action, job_id))
        return "backfill callback response"


class BotRouterTests(unittest.TestCase):
    def test_denied_user_is_ignored_and_logged(self):
        services = FakeBotServices()
        bot = FakeBotApi()
        audit_events = []
        router = BotRouter(
            access=BotAccessController(allowed_user_id=100),
            bot_api=bot,
            services=services,
            audit_log=audit_events.append,
        )

        router.handle_update(
            {
                "message": {
                    "from": {"id": 999},
                    "chat": {"id": 123},
                    "text": "/summary",
                }
            }
        )

        self.assertEqual(services.calls, [])
        self.assertEqual(bot.sent_messages, [])
        self.assertEqual(audit_events, [{"event": "denied", "user_id": 999}])

    def test_owner_commands_dispatch_to_services(self):
        command_to_call = {
            "/summary": ("summary",),
            "/tasks": ("tasks",),
            "/review": ("review",),
            "/backfill": ("backfill",),
            "/blacklist": ("blacklist",),
            "/settings": ("settings",),
            "/health": ("health",),
            "/logs": ("logs",),
        }

        for command, expected_call in command_to_call.items():
            with self.subTest(command=command):
                services = FakeBotServices()
                bot = FakeBotApi()
                router = BotRouter(
                    access=BotAccessController(allowed_user_id=100),
                    bot_api=bot,
                    services=services,
                )

                router.handle_update(
                    {
                        "message": {
                            "from": {"id": 100},
                            "chat": {"id": 123},
                            "text": command,
                        }
                    }
                )

                self.assertEqual(services.calls, [expected_call])
                self.assertEqual(bot.sent_messages[0], (123, f"{expected_call[0]} response", None))

    def test_start_and_help_dispatch_to_help_service(self):
        for command in ("/start", "/help"):
            with self.subTest(command=command):
                services = FakeBotServices()
                bot = FakeBotApi()
                router = BotRouter(
                    access=BotAccessController(allowed_user_id=100),
                    bot_api=bot,
                    services=services,
                )

                router.handle_update(
                    {
                        "message": {
                            "from": {"id": 100},
                            "chat": {"id": 123},
                            "text": command,
                        }
                    }
                )

                self.assertEqual(services.calls, [("help",)])
                self.assertEqual(bot.sent_messages[0], (123, "help response", None))

    def test_owner_command_can_send_response_markup(self):
        class MarkupServices(FakeBotServices):
            def tasks(self):
                self.calls.append(("tasks",))
                return type(
                    "Response",
                    (),
                    {
                        "text": "tasks response",
                        "reply_markup": {"inline_keyboard": [[{"text": "Done", "callback_data": "x"}]]},
                    },
                )()

        services = MarkupServices()
        bot = FakeBotApi()
        router = BotRouter(
            access=BotAccessController(allowed_user_id=100),
            bot_api=bot,
            services=services,
        )

        router.handle_update(
            {
                "message": {
                    "from": {"id": 100},
                    "chat": {"id": 123},
                    "text": "/tasks",
                }
            }
        )

        self.assertEqual(bot.sent_messages[0][2], {"inline_keyboard": [[{"text": "Done", "callback_data": "x"}]]})

    def test_inline_callbacks_dispatch_to_review_status_and_backfill_actions(self):
        callback_cases = {
            "review:approve:item-1": (
                ("review_callback", "approve", "item-1"),
                "review callback response",
            ),
            "status:completed:item-1": (
                ("status_callback", "completed", "item-1"),
                "status callback response",
            ),
            "backfill:cancel:job-1": (
                ("backfill_callback", "cancel", "job-1"),
                "backfill callback response",
            ),
        }

        for callback_data, (expected_call, expected_answer) in callback_cases.items():
            with self.subTest(callback_data=callback_data):
                services = FakeBotServices()
                bot = FakeBotApi()
                router = BotRouter(
                    access=BotAccessController(allowed_user_id=100),
                    bot_api=bot,
                    services=services,
                )

                router.handle_update(
                    {
                        "callback_query": {
                            "id": "callback-1",
                            "from": {"id": 100},
                            "message": {
                                "chat": {"id": 123},
                                "message_id": 456,
                            },
                            "data": callback_data,
                        }
                    }
                )

                self.assertEqual(services.calls, [expected_call])
                self.assertEqual(bot.answered_callbacks[0], ("callback-1", expected_answer, False))

    def test_backfill_callback_response_sends_message_with_markup(self):
        class BackfillResponseServices(FakeBotServices):
            def handle_backfill_callback(self, action: str, target_id: str):
                self.calls.append(("backfill_callback", action, target_id))
                return type(
                    "Response",
                    (),
                    {
                        "text": "choose chat",
                        "reply_markup": {
                            "inline_keyboard": [[{"text": "Alice", "callback_data": "bf:c:30:0:1001"}]]
                        },
                    },
                )()

        services = BackfillResponseServices()
        bot = FakeBotApi()
        router = BotRouter(
            access=BotAccessController(allowed_user_id=100),
            bot_api=bot,
            services=services,
        )

        router.handle_update(
            {
                "callback_query": {
                    "id": "callback-1",
                    "from": {"id": 100},
                    "message": {
                        "chat": {"id": 123},
                        "message_id": 456,
                    },
                    "data": "bf:d:30",
                }
            }
        )

        self.assertEqual(services.calls, [("backfill_callback", "d", "30")])
        self.assertEqual(bot.answered_callbacks, [("callback-1", "Opened.", False)])
        self.assertEqual(
            bot.sent_messages,
            [
                (
                    123,
                    "choose chat",
                    {"inline_keyboard": [[{"text": "Alice", "callback_data": "bf:c:30:0:1001"}]]},
                )
            ],
        )

    def test_menu_callbacks_dispatch_to_command_services_and_send_message(self):
        callback_cases = {
            "menu:summary:0": ("summary", "summary response"),
            "menu:tasks:0": ("tasks", "tasks response"),
            "menu:review:0": ("review", "review response"),
            "menu:backfill:0": ("backfill", "backfill response"),
            "menu:health:0": ("health", "health response"),
            "menu:logs:0": ("logs", "logs response"),
            "menu:settings:0": ("settings", "settings response"),
            "menu:help:0": ("help", "help response"),
        }

        for callback_data, (expected_method, expected_text) in callback_cases.items():
            with self.subTest(callback_data=callback_data):
                services = FakeBotServices()
                bot = FakeBotApi()
                router = BotRouter(
                    access=BotAccessController(allowed_user_id=100),
                    bot_api=bot,
                    services=services,
                )

                router.handle_update(
                    {
                        "callback_query": {
                            "id": "callback-1",
                            "from": {"id": 100},
                            "message": {
                                "chat": {"id": 123},
                                "message_id": 456,
                            },
                            "data": callback_data,
                        }
                    }
                )

                self.assertEqual(services.calls, [(expected_method,)])
                self.assertEqual(bot.answered_callbacks[0], ("callback-1", "Opened.", False))
                self.assertEqual(bot.sent_messages[0][1], expected_text)


if __name__ == "__main__":
    unittest.main()
