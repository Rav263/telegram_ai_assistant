from __future__ import annotations

from pathlib import Path
from typing import Protocol


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Cursor(Protocol):
    def execute(self, sql: str, params: object | None = None) -> object:
        ...


class Connection(Protocol):
    def cursor(self) -> Cursor:
        ...


def apply_schema(connection: Connection, schema_path: Path = SCHEMA_PATH) -> None:
    schema_sql = schema_path.read_text(encoding="utf-8")
    cursor = connection.cursor()

    if hasattr(cursor, "__enter__"):
        with cursor as active_cursor:
            active_cursor.execute(schema_sql)
        return

    cursor.execute(schema_sql)
