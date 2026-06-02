import unittest

from telegram_ai_assistant.cli import build_parser, main


class CLITests(unittest.TestCase):
    def test_parses_version_command(self):
        args = build_parser().parse_args(["version"])

        self.assertEqual(args.command, "version")

    def test_parses_run_worker_command(self):
        args = build_parser().parse_args(["run", "worker"])

        self.assertEqual(args.command, "run")
        self.assertEqual(args.process, "worker")

    def test_version_command_returns_success(self):
        exit_code = main(["version"])

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
