from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OperationsDocsTests(unittest.TestCase):
    def test_manual_unread_smoke_test_mentions_required_safety_checks(self):
        text = (ROOT / "docs/operations/manual-unread-smoke-test.md").read_text()

        self.assertIn("controlled chat", text)
        self.assertIn("unread badge", text)
        self.assertIn("mark_read", text)
        self.assertIn("send_read_acknowledge", text)
        self.assertIn("telegram-ai-assistant run ingestor", text)
        self.assertIn("last_ingested_message_id", text)
        self.assertIn("rollback", text)

    def test_local_runbook_mentions_core_services(self):
        text = (ROOT / "docs/operations/local-runbook.md").read_text()

        self.assertIn("Postgres", text)
        self.assertIn("LM Studio", text)
        self.assertIn(".env", text)
        self.assertIn("telegram-ai-assistant", text)
        self.assertIn("TELEGRAM_SESSION_PATH", text)
        self.assertIn("TELEGRAM_INGEST_CHAT_ID", text)
        self.assertIn("TELEGRAM_INGEST_LIMIT", text)
        self.assertIn("TELEGRAM_INGEST_BOOTSTRAP_MODE", text)
        self.assertIn("TELEGRAM_INGEST_BOOTSTRAP_DAYS", text)
        self.assertIn("telegram-ai-assistant run ingestor", text)
        self.assertIn("TELEGRAM_BACKFILL_CHAT_ID", text)
        self.assertIn("TELEGRAM_BACKFILL_START_AT", text)
        self.assertIn("TELEGRAM_BACKFILL_END_AT", text)
        self.assertIn("TELEGRAM_BACKFILL_LIMIT", text)
        self.assertIn("telegram-ai-assistant run backfill", text)
        self.assertIn("TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS", text)
        self.assertIn("TELEGRAM_LISTENER_DENIED_CHAT_IDS", text)
        self.assertIn("telegram-ai-assistant run listener", text)
        self.assertIn("WORKER_BATCH_SIZE", text)
        self.assertIn("WORKER_POLL_INTERVAL_SECONDS", text)
        self.assertIn("WORKER_ITEM_AUTO_APPLY_THRESHOLD", text)
        self.assertIn("WORKER_STATUS_AUTO_APPLY_THRESHOLD", text)
        self.assertIn("telegram-ai-assistant run worker --once", text)
        self.assertIn("telegram-ai-assistant run worker", text)
        self.assertIn("/logs", text)
        self.assertIn("LOG_LEVEL", text)
        self.assertIn("--log-level debug", text)
        self.assertIn("logs go to stderr", text)
        self.assertIn("docker compose up -d postgres app-listener app-worker", text)
        self.assertIn("docker compose run --rm app-listener telegram-ai-assistant migrate", text)
        self.assertIn("docker compose run --rm app-listener telegram-ai-assistant health", text)


if __name__ == "__main__":
    unittest.main()
