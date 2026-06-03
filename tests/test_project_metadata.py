from pathlib import Path
import tomllib
import unittest


class ProjectMetadataTests(unittest.TestCase):
    def test_declares_psycopg_binary_dependency(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

        dependencies = pyproject["project"]["dependencies"]

        self.assertIn("psycopg[binary]>=3.2", dependencies)

    def test_declares_telethon_dependency(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

        dependencies = pyproject["project"]["dependencies"]

        self.assertIn("telethon>=1.36", dependencies)


if __name__ == "__main__":
    unittest.main()
