from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from telegram_ai_assistant.env import load_dotenv, load_environment


class EnvLoaderTests(unittest.TestCase):
    def test_load_dotenv_parses_comments_empty_lines_and_quotes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                """
# comment
TELEGRAM_API_HASH='hash value'
DATABASE_URL="postgresql://localhost/db"
BACKFILL_DAYS=30
""",
                encoding="utf-8",
            )

            values = load_dotenv(path)

        self.assertEqual(values["TELEGRAM_API_HASH"], "hash value")
        self.assertEqual(values["DATABASE_URL"], "postgresql://localhost/db")
        self.assertEqual(values["BACKFILL_DAYS"], "30")

    def test_missing_dotenv_returns_empty_mapping(self):
        self.assertEqual(load_dotenv(Path("/tmp/missing-telegram-ai.env")), {})

    def test_shell_environment_overrides_dotenv_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DATABASE_URL=postgresql://dotenv/db\n", encoding="utf-8")

            values = load_environment(path, {"DATABASE_URL": "postgresql://shell/db"})

        self.assertEqual(values["DATABASE_URL"], "postgresql://shell/db")
