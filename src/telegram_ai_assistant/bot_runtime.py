from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
        poll_timeout_seconds: int = 25,
    ):
        self.bot_api = bot_api
        self.router = router
        self.runtime_event_repository = runtime_event_repository
        self.poll_timeout_seconds = poll_timeout_seconds

    def run_forever(
        self,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> BotRunResult:
        offset: int | None = None
        last_update_id: int | None = None
        while True:
            if stop_requested is not None and stop_requested():
                return BotRunResult(status="stopped", last_update_id=last_update_id)

            updates = self.bot_api.get_updates(offset=offset, timeout=self.poll_timeout_seconds)
            for update in updates:
                update_id = _update_id(update)
                try:
                    self.router.handle_update(update)
                except Exception as exc:
                    self._record_update_failure(exc)
                if update_id is not None:
                    last_update_id = update_id
                    offset = update_id + 1

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


def _update_id(update: Mapping[str, Any]) -> int | None:
    value = update.get("update_id")
    if value is None:
        return None
    return int(value)
