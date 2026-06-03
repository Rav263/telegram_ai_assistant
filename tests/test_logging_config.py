import io
from contextlib import redirect_stderr
import logging
import unittest

from telegram_ai_assistant.config import ConfigError
from telegram_ai_assistant.logging_config import configure_logging, normalize_log_level


class LoggingConfigTests(unittest.TestCase):
    def tearDown(self):
        logging.basicConfig(level=logging.WARNING, force=True)

    def test_normalize_log_level_accepts_case_insensitive_values(self):
        self.assertEqual(normalize_log_level("debug"), "DEBUG")
        self.assertEqual(normalize_log_level("Warning"), "WARNING")

    def test_normalize_log_level_rejects_invalid_values(self):
        with self.assertRaises(ConfigError):
            normalize_log_level("verbose")

    def test_configure_logging_writes_to_stderr_at_selected_level(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            configure_logging("debug")
            logging.getLogger("telegram_ai_assistant.test").debug("probe message")

        output = stderr.getvalue()
        self.assertIn("DEBUG", output)
        self.assertIn("telegram_ai_assistant.test", output)
        self.assertIn("probe message", output)


if __name__ == "__main__":
    unittest.main()
