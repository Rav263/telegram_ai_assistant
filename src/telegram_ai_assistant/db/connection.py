from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


ConnectCallable = Callable[[str], Any]


def default_connect(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(database_url)


class PostgresConnectionFactory:
    def __init__(self, database_url: str, connect: ConnectCallable = default_connect):
        self.database_url = database_url
        self._connect = connect

    def connect(self) -> Any:
        return self._connect(self.database_url)

    @contextmanager
    def connection(self) -> Iterator[Any]:
        connection = self.connect()
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()
