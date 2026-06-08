from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json

from .domain import ExtractedItem, Message
from .llm import ParsedActionResponse, ParsedLLMAction, action_response_format, parse_action_response


PROMPT_MESSAGE_TEXT_LIMIT = 600
PROMPT_OPEN_ITEM_LIMIT = 10
PROMPT_OPEN_ITEM_TITLE_LIMIT = 80
PROMPT_OPEN_ITEM_SOURCE_REF_LIMIT = 0


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
        raw_json = self._llm_client.extract_json(messages=prompt, response_format=action_response_format())
        parsed = parse_action_response(raw_json)
        return parsed_response_to_extraction_result(parsed)


def build_extraction_prompt(
    candidate_messages: Sequence[Message],
    *,
    open_items: Sequence[ExtractedItem] = (),
) -> tuple[dict[str, str], ...]:
    message_records = [
        {
            "telegram_message_id": message.telegram_message_id,
            "direction": message.direction.value,
            "sent_at": message.sent_at.isoformat(),
            **_truncated_field("text", message.content_text, PROMPT_MESSAGE_TEXT_LIMIT),
            "reply_to_message_id": message.reply_to_message_id,
        }
        for message in candidate_messages
    ]
    item_records = [
        {
            "item_id": item.item_id,
            "type": item.item_type.value,
            **_truncated_field("title", item.title, PROMPT_OPEN_ITEM_TITLE_LIMIT),
            "status": item.status.value,
            "due_at": item.due_at.isoformat() if item.due_at is not None else None,
            "source_refs": [
                {
                    "chat_id": source.chat_id,
                    "telegram_message_id": source.telegram_message_id,
                }
                for source in item.sources[:PROMPT_OPEN_ITEM_SOURCE_REF_LIMIT]
            ],
            "source_ref_count": len(item.sources),
        }
        for item in open_items[:PROMPT_OPEN_ITEM_LIMIT]
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
                + _compact_json(message_records)
                + "\nOpen items:\n"
                + _compact_json(item_records)
            ),
        },
    )


def _truncated_field(field_name: str, value: str, limit: int) -> dict[str, object]:
    if len(value) <= limit:
        return {
            field_name: value,
            f"{field_name}_truncated": False,
            f"{field_name}_original_characters": len(value),
        }
    return {
        field_name: value[:limit],
        f"{field_name}_truncated": True,
        f"{field_name}_original_characters": len(value),
    }


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parsed_response_to_extraction_result(
    parsed: ParsedActionResponse,
) -> ExtractionBatchResult:
    return ExtractionBatchResult(actions=parsed.actions)
