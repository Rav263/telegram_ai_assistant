class MutatingTelegramMethodError(RuntimeError):
    pass


class ReadOnlyTelegramGuard:
    MUTATING_METHODS = frozenset(
        {
            "send_message",
            "send_file",
            "edit_message",
            "delete_messages",
            "send_read_acknowledge",
            "mark_read",
            "pin_message",
            "unpin_message",
            "forward_messages",
        }
    )

    def assert_allowed(self, method_name: str) -> None:
        if method_name in self.MUTATING_METHODS:
            raise MutatingTelegramMethodError(f"Telegram method is not allowed in read-only mode: {method_name}")
