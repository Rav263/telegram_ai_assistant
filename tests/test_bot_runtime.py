import unittest

from telegram_ai_assistant.bot_runtime import BotRuntime


class FakeBotApi:
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def get_updates(self, *, offset, timeout):
        self.calls.append({"offset": offset, "timeout": timeout})
        if self.batches:
            return self.batches.pop(0)
        return []


class FakeRouter:
    def __init__(self, fail_update_id=None):
        self.updates = []
        self.fail_update_id = fail_update_id

    def handle_update(self, update):
        self.updates.append(update)
        if update.get("update_id") == self.fail_update_id:
            raise RuntimeError("private message text")


class FakeRuntimeEventRepository:
    def __init__(self):
        self.events = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)


class BotRuntimeTests(unittest.TestCase):
    def test_long_polls_updates_and_advances_offset(self):
        api = FakeBotApi(
            [
                [{"update_id": 10, "message": {"text": "/logs"}}],
                [{"update_id": 12, "message": {"text": "/health"}}],
            ]
        )
        router = FakeRouter()
        runtime = BotRuntime(bot_api=api, router=router, poll_timeout_seconds=15)

        result = runtime.run_forever(stop_requested=lambda: len(api.calls) >= 2)

        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.last_update_id, 12)
        self.assertEqual(
            api.calls,
            [
                {"offset": None, "timeout": 15},
                {"offset": 11, "timeout": 15},
            ],
        )
        self.assertEqual([update["update_id"] for update in router.updates], [10, 12])

    def test_records_update_failures_without_raw_update_text_and_keeps_offset(self):
        api = FakeBotApi(
            [
                [{"update_id": 20, "message": {"text": "secret text"}}],
                [],
            ]
        )
        router = FakeRouter(fail_update_id=20)
        events = FakeRuntimeEventRepository()
        runtime = BotRuntime(
            bot_api=api,
            router=router,
            runtime_event_repository=events,
            poll_timeout_seconds=5,
        )

        result = runtime.run_forever(stop_requested=lambda: len(api.calls) >= 2)

        self.assertEqual(result.last_update_id, 20)
        self.assertEqual(api.calls[1]["offset"], 21)
        self.assertEqual(events.events[0]["component"], "bot")
        self.assertEqual(events.events[0]["severity"], "warning")
        self.assertEqual(events.events[0]["event_type"], "update_failed")
        self.assertEqual(events.events[0]["metadata"], {"error_type": "RuntimeError"})
        self.assertNotIn("secret text", str(events.events))


if __name__ == "__main__":
    unittest.main()
