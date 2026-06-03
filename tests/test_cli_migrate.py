import io
import logging
from contextlib import redirect_stdout
import unittest

from telegram_ai_assistant.cli import main


class FakeContext:
    def __init__(self):
        self.migrated = False

    def migrate(self):
        self.migrated = True


class FailingContext:
    def migrate(self):
        raise RuntimeError("could not connect using secret-token")


class CLIMigrateTests(unittest.TestCase):
    def tearDown(self):
        logging.basicConfig(level=logging.WARNING, force=True)

    def test_migrate_command_uses_context_and_returns_success(self):
        context = FakeContext()

        exit_code = main(["migrate"], context_factory=lambda environment: context)

        self.assertEqual(exit_code, 0)
        self.assertTrue(context.migrated)

    def test_migrate_failure_returns_nonzero_without_secret_values(self):
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(["migrate"], context_factory=lambda environment: FailingContext())

        self.assertEqual(exit_code, 1)
        self.assertIn("migration failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
