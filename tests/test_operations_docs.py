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
        self.assertIn("rollback", text)

    def test_local_runbook_mentions_core_services(self):
        text = (ROOT / "docs/operations/local-runbook.md").read_text()

        self.assertIn("Postgres", text)
        self.assertIn("LM Studio", text)
        self.assertIn(".env", text)
        self.assertIn("telegram-ai-assistant", text)


if __name__ == "__main__":
    unittest.main()
