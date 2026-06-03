from pathlib import Path
import tomllib
import unittest


class DockerPackagingTests(unittest.TestCase):
    def test_dockerfile_installs_project_and_runs_listener_cli(self):
        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM python:3.11-slim", dockerfile)
        self.assertIn("useradd", dockerfile)
        self.assertIn("/var/lib/telegram-ai-assistant/sessions", dockerfile)
        self.assertIn("pip install --no-cache-dir .", dockerfile)
        self.assertIn('CMD ["telegram-ai-assistant", "run", "listener"]', dockerfile)

    def test_docker_compose_defines_postgres_listener_and_worker(self):
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("postgres:", compose)
        self.assertIn("app-listener:", compose)
        self.assertIn("app-worker:", compose)
        self.assertIn("telegram-ai-assistant run listener", compose)
        self.assertIn("telegram-ai-assistant run worker", compose)
        self.assertIn("telegram-sessions", compose)
        self.assertIn("TELEGRAM_SESSION_PATH", compose)
        self.assertIn("/var/lib/telegram-ai-assistant/sessions", compose)
        self.assertIn("type: bind", compose)
        self.assertIn(
            "source: ${TELEGRAM_DATA_DIR:-${HOME}/.telegram/telegram_ai_assistant}/postgres",
            compose,
        )
        self.assertIn("target: /var/lib/postgresql/data", compose)
        self.assertNotIn("postgres-data:", compose)
        self.assertIn("env_file:", compose)
        self.assertIn("required: false", compose)

    def test_dockerignore_excludes_local_sensitive_and_generated_files(self):
        dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

        self.assertIn(".git", dockerignore)
        self.assertIn(".venv", dockerignore)
        self.assertIn(".worktrees", dockerignore)
        self.assertIn(".local", dockerignore)
        self.assertIn("*.session", dockerignore)

    def test_schema_sql_is_included_in_installed_package_data(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["tool"]["setuptools"]["package-data"]["telegram_ai_assistant.db"],
            ["schema.sql"],
        )


if __name__ == "__main__":
    unittest.main()
