from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMetadata:
    chat_id: int
    chat_type: str
    title: str = ""
    is_megagroup: bool = False
    is_broadcast: bool = False


@dataclass(frozen=True)
class ChatIngestionPolicy:
    allowed_channel_ids: frozenset[int] = frozenset()
    denied_chat_ids: frozenset[int] = frozenset()

    def can_read(self, chat: ChatMetadata) -> bool:
        if chat.chat_id in self.denied_chat_ids:
            return False
        if chat.is_broadcast:
            return chat.chat_id in self.allowed_channel_ids
        if chat.is_megagroup:
            return True
        return chat.chat_type in {"private", "group", "supergroup"}
