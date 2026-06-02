from pathlib import Path
import re
import unittest


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "telegram_ai_assistant"
    / "db"
    / "schema.sql"
)


class DBSchemaTests(unittest.TestCase):
    def test_schema_defines_all_mvp_tables(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = SCHEMA_PATH.read_text(encoding="utf-8").lower()

        required_tables = (
            "accounts",
            "chats",
            "messages",
            "raw_updates",
            "message_candidates",
            "extracted_items",
            "item_status_events",
            "review_queue",
            "llm_runs",
            "backfill_jobs",
            "bot_actions",
            "settings",
        )

        for table_name in required_tables:
            with self.subTest(table_name=table_name):
                self.assertRegex(
                    schema,
                    rf"create\s+table\s+if\s+not\s+exists\s+{table_name}\b",
                )

    def test_messages_are_unique_per_account_chat_and_telegram_message(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn(
            "unique (account_id, chat_id, telegram_message_id)",
            schema,
        )


if __name__ == "__main__":
    unittest.main()
