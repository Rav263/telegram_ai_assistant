import unittest

from telegram_ai_assistant.db.connection import PostgresConnectionFactory


class FakeConnection:
    def __init__(self) -> None:
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


class PostgresConnectionFactoryTests(unittest.TestCase):
    def test_connect_calls_injected_connect_with_database_url(self):
        calls: list[str] = []
        connection = FakeConnection()

        def connect(database_url: str) -> FakeConnection:
            calls.append(database_url)
            return connection

        factory = PostgresConnectionFactory(
            "postgresql://localhost/assistant",
            connect=connect,
        )

        self.assertIs(factory.connect(), connection)
        self.assertEqual(calls, ["postgresql://localhost/assistant"])

    def test_connection_commits_and_closes_on_success(self):
        connection = FakeConnection()
        factory = PostgresConnectionFactory(
            "postgresql://localhost/assistant",
            connect=lambda database_url: connection,
        )

        with factory.connection() as active_connection:
            self.assertIs(active_connection, connection)

        self.assertEqual(connection.events, ["commit", "close"])

    def test_connection_rolls_back_and_closes_on_failure(self):
        connection = FakeConnection()
        factory = PostgresConnectionFactory(
            "postgresql://localhost/assistant",
            connect=lambda database_url: connection,
        )

        with self.assertRaises(RuntimeError):
            with factory.connection():
                raise RuntimeError("boom")

        self.assertEqual(connection.events, ["rollback", "close"])


if __name__ == "__main__":
    unittest.main()
