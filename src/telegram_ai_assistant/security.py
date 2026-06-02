from dataclasses import dataclass


@dataclass(frozen=True)
class BotAccessController:
    allowed_user_id: int

    def is_allowed(self, telegram_user_id: int) -> bool:
        return telegram_user_id == self.allowed_user_id
