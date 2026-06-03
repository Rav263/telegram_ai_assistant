from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from typing import Any


@dataclass(frozen=True)
class BotRunResult:
    status: str
    last_update_id: int | None = None


class BotRuntime:
    def __init__(
        self,
        *,
        bot_api: Any,
        router: Any,
        runtime_event_repository: Any | None = None,
        state_repository: Any | None = None,
        poll_timeout_seconds: int = 25,
        backoff_seconds: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
        commit: Callable[[], None] | None = None,
        bot_name: str = "default",
    ):
        self.bot_api = bot_api
        self.router = router
        self.runtime_event_repository = runtime_event_repository
        self.state_repository = state_repository
        self.poll_timeout_seconds = poll_timeout_seconds
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep
        self.commit = commit
        self.bot_name = bot_name

    def run_forever(
        self,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> BotRunResult:
        last_update_id = self._load_last_update_id()
        offset = last_update_id + 1 if last_update_id is not None else None
        while True:
            if stop_requested is not None and stop_requested():
                return BotRunResult(status="stopped", last_update_id=last_update_id)

            try:
                updates = self.bot_api.get_updates(offset=offset, timeout=self.poll_timeout_seconds)
            except Exception as exc:
                self._record_poll_failure(exc)
                self._commit()
                self.sleep(self.backoff_seconds)
                continue

            for update in updates:
                update_id = _update_id(update)
                try:
                    self.router.handle_update(update)
                except Exception as exc:
                    self._record_update_failure(exc)
                if update_id is not None:
                    last_update_id = update_id
                    offset = update_id + 1
                    self._save_last_update_id(update_id)
                self._commit()

    def _record_update_failure(self, error: BaseException) -> None:
        if self.runtime_event_repository is None:
            return
        self.runtime_event_repository.record_event(
            component="bot",
            severity="warning",
            event_type="update_failed",
            message="Bot update failed",
            metadata={"error_type": type(error).__name__},
        )

    def _record_poll_failure(self, error: BaseException) -> None:
        if self.runtime_event_repository is None:
            return
        self.runtime_event_repository.record_event(
            component="bot",
            severity="warning",
            event_type="poll_failed",
            message="Bot polling failed",
            metadata={"error_type": type(error).__name__},
        )

    def _load_last_update_id(self) -> int | None:
        if self.state_repository is None:
            return None
        return self.state_repository.get_last_update_id(bot_name=self.bot_name)

    def _save_last_update_id(self, update_id: int) -> None:
        if self.state_repository is None:
            return
        self.state_repository.save_last_update_id(bot_name=self.bot_name, last_update_id=update_id)

    def _commit(self) -> None:
        if self.commit is not None:
            self.commit()


def _update_id(update: Mapping[str, Any]) -> int | None:
    value = update.get("update_id")
    if value is None:
        return None
    return int(value)
