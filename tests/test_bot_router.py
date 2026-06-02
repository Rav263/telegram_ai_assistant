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

    def test_inline_callbacks_dispatch_to_review_status_and_backfill_actions(self):
        callback_cases = {
            "review:approve:item-1": ("review_callback", "approve", "item-1"),
            "status:completed:item-1": ("status_callback", "completed", "item-1"),
            "backfill:cancel:job-1": ("backfill_callback", "cancel", "job-1"),
        }

        for callback_data, expected_call in callback_cases.items():
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
                self.assertEqual(bot.answered_callbacks[0], ("callback-1", services.calls[0][0].replace("_", " "), False))


if __name__ == "__main__":
    unittest.main()
