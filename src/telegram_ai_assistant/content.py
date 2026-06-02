from __future__ import annotations

from typing import Protocol

from telegram_ai_assistant.domain import Message


class ContentExtractor(Protocol):
    def extract(self, message: Message) -> str:
        pass


class TextContentExtractor:
    def extract(self, message: Message) -> str:
        return message.content_text
