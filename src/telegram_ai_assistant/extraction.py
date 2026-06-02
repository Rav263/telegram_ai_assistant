from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any

from .domain import ExtractedItem, Message, SourceRef
from .llm import ParsedExtractionItem, ParsedExtractionResponse, parse_extraction_response


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractionBatchResult:
    items: tuple[ExtractedItem, ...]
    status_changes: tuple[dict[str, Any], ...]


class ExtractionService:
    def __init__(self, *, llm_client: object) -> None:
        self._llm_client = llm_client

    def extract_batch(self, candidate_messages: Sequence[Message]) -> ExtractionBatchResult:
        prompt = build_extraction_prompt(candidate_messages)
        raw_json = self._llm_client.extract_json(messages=prompt)
        parsed = parse_extraction_response(raw_json)
        return parsed_response_to_extraction_result(parsed, candidate_messages)


def build_extraction_prompt(candidate_messages: Sequence[Message]) -> tuple[dict[str, str], ...]:
    records = [
        {
            "account_id": message.account_id,
            "chat_id": message.chat_id,
            "telegram_message_id": message.telegram_message_id,
            "sender_id": message.sender_id,
            "direction": message.direction.value,
            "sent_at": message.sent_at.isoformat(),
            "text": message.content_text,
            "reply_to_message_id": message.reply_to_message_id,
        }
        for message in candidate_messages
    ]
    return (
        {
            "role": "system",
            "content": (
                "Extract tasks, thoughts, commitments, reminders, waiting-for items, "
                "and useful context from Telegram messages. Return only valid JSON with "
                "items and status_changes arrays. Each item must include type, title, "
                "description, confidence, source_message_ids, and rationale."
            ),
        },
        {
            "role": "user",
            "content": "Messages:\n" + json.dumps(records, ensure_ascii=False, indent=2),
        },
    )


def parsed_response_to_extraction_result(
    parsed: ParsedExtractionResponse,
    source_messages: Sequence[Message],
) -> ExtractionBatchResult:
    items = tuple(
        parsed_item_to_extracted_item(index, item, source_messages)
        for index, item in enumerate(parsed.items, start=1)
    )
    return ExtractionBatchResult(items=items, status_changes=parsed.status_changes)


def parsed_item_to_extracted_item(
    index: int,
    parsed_item: ParsedExtractionItem,
    source_messages: Sequence[Message],
) -> ExtractedItem:
    source_refs = _source_refs(parsed_item.source_message_ids, source_messages)
    return ExtractedItem(
        item_id=_item_id(index, parsed_item),
        item_type=parsed_item.item_type,
        title=parsed_item.title,
        description=parsed_item.description,
        confidence=parsed_item.confidence,
        sources=source_refs,
        rationale=parsed_item.rationale,
    )


def _source_refs(source_message_ids: Sequence[int], source_messages: Sequence[Message]) -> tuple[SourceRef, ...]:
    by_message_id = {message.telegram_message_id: message for message in source_messages}
    refs = []
    for message_id in source_message_ids:
        message = by_message_id.get(message_id)
        if message is None:
            raise ExtractionError(f"source message id {message_id} was not provided")
        refs.append(SourceRef(chat_id=message.chat_id, telegram_message_id=message.telegram_message_id))
    return tuple(refs)


def _item_id(index: int, parsed_item: ParsedExtractionItem) -> str:
    source_part = "-".join(str(message_id) for message_id in parsed_item.source_message_ids) or "unknown"
    return f"llm-{index}-{parsed_item.item_type.value}-{source_part}"
