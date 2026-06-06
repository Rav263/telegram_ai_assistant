from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json

from .domain import ExtractedItem, Message
from .llm import ParsedActionResponse, ParsedLLMAction, parse_action_response


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractionBatchResult:
    actions: tuple[ParsedLLMAction, ...]


class ExtractionService:
    def __init__(self, *, llm_client: object) -> None:
        self._llm_client = llm_client

    def extract_batch(
        self,
        candidate_messages: Sequence[Message],
        *,
        open_items: Sequence[ExtractedItem] = (),
    ) -> ExtractionBatchResult:
        prompt = build_extraction_prompt(candidate_messages, open_items=open_items)
        raw_json = self._llm_client.extract_json(messages=prompt)
        parsed = parse_action_response(raw_json)
        return parsed_response_to_extraction_result(parsed)


def build_extraction_prompt(
    candidate_messages: Sequence[Message],
    *,
    open_items: Sequence[ExtractedItem] = (),
) -> tuple[dict[str, str], ...]:
    message_records = [
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
    item_records = [
        {
            "item_id": item.item_id,
            "type": item.item_type.value,
            "title": item.title,
            "status": item.status.value,
            "due_at": item.due_at.isoformat() if item.due_at is not None else None,
            "source_refs": [
                {
                    "chat_id": source.chat_id,
                    "telegram_message_id": source.telegram_message_id,
                }
                for source in item.sources
            ],
        }
        for item in open_items
    ]
    return (
        {
            "role": "system",
            "content": (
                "Propose actions only. Return valid JSON with a top-level actions array. "
                "Actions may be create_item, update_item_status, update_item_field, "
                "merge_duplicate, schedule_notification, or link_source. "
                "All user-facing generated text must be Russian. Internal JSON keys and enum values stay English. "
                "Never claim that a database update already happened. Prefer updating or linking existing open items "
                "over creating duplicates. Status updates require explicit evidence from owner messages or clear context. "
                "For example, 'Завтра нужно заехать на озон, забрать ирригатор' should propose create_item "
                "and schedule_notification. Completion messages like 'Сделал', 'забрал', or 'отправил' near an "
                "existing item should propose update_item_status."
            ),
        },
        {
            "role": "user",
            "content": (
                "Candidate messages:\n"
                + json.dumps(message_records, ensure_ascii=False, indent=2)
                + "\nOpen items:\n"
                + json.dumps(item_records, ensure_ascii=False, indent=2)
            ),
        },
    )


def parsed_response_to_extraction_result(
    parsed: ParsedActionResponse,
) -> ExtractionBatchResult:
    return ExtractionBatchResult(actions=parsed.actions)
