import os
import subprocess
import sys
import unittest

from telegram_ai_assistant import __version__


class CLIEntrypointTests(unittest.TestCase):
    def test_module_execution_runs_main(self):
        result = subprocess.run(
            [sys.executable, "-m", "telegram_ai_assistant.cli", "version"],
            capture_output=True,
            cwd=".",
            env={**os.environ, "PYTHONPATH": "src"},
            text=True,
            timeout=5,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), __version__)


if __name__ == "__main__":
    unittest.main()
