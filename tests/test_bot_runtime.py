import unittest

from telegram_ai_assistant.bot_runtime import BotRuntime


class FakeBotApi:
    def __init__(self, batches, errors=()):
        self.batches = list(batches)
        self.errors = list(errors)
        self.calls = []

    def get_updates(self, *, offset, timeout):
        self.calls.append({"offset": offset, "timeout": timeout})
        if self.errors:
            raise self.errors.pop(0)
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


class FakeBotRuntimeStateRepository:
    def __init__(self, last_update_id=None):
        self.last_update_id = last_update_id
        self.saved = []

    def get_last_update_id(self, *, bot_name):
        return self.last_update_id

    def save_last_update_id(self, *, bot_name, last_update_id):
        self.saved.append((bot_name, last_update_id))
        self.last_update_id = last_update_id


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

    def test_uses_persisted_offset_and_saves_each_processed_update_id(self):
        api = FakeBotApi([[{"update_id": 30, "message": {"text": "/tasks"}}]])
        state = FakeBotRuntimeStateRepository(last_update_id=29)
        runtime = BotRuntime(
            bot_api=api,
            router=FakeRouter(),
            state_repository=state,
        )

        result = runtime.run_forever(stop_requested=lambda: len(api.calls) >= 2)

        self.assertEqual(api.calls[0]["offset"], 30)
        self.assertEqual(state.saved, [("default", 30)])
        self.assertEqual(result.last_update_id, 30)

    def test_commits_after_processed_update(self):
        api = FakeBotApi([[{"update_id": 40, "message": {"text": "/tasks"}}]])
        commits = []
        runtime = BotRuntime(
            bot_api=api,
            router=FakeRouter(),
            state_repository=FakeBotRuntimeStateRepository(),
            commit=lambda: commits.append("commit"),
        )

        runtime.run_forever(stop_requested=lambda: len(api.calls) >= 2)

        self.assertEqual(commits, ["commit"])

    def test_records_poll_failures_with_backoff_without_raw_error_text(self):
        api = FakeBotApi([[]], errors=[RuntimeError("secret token in transport")])
        events = FakeRuntimeEventRepository()
        sleeps = []
        runtime = BotRuntime(
            bot_api=api,
            router=FakeRouter(),
            runtime_event_repository=events,
            sleep=sleeps.append,
            backoff_seconds=3,
        )

        result = runtime.run_forever(stop_requested=lambda: len(api.calls) >= 2)

        self.assertEqual(result.status, "stopped")
        self.assertEqual(sleeps, [3])
        self.assertEqual(events.events[0]["component"], "bot")
        self.assertEqual(events.events[0]["event_type"], "poll_failed")
        self.assertEqual(events.events[0]["metadata"], {"error_type": "RuntimeError"})
        self.assertNotIn("secret token", str(events.events))


if __name__ == "__main__":
    unittest.main()
