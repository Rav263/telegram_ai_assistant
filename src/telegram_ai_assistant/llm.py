from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .domain import ItemType


class LLMValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedExtractionItem:
    item_type: ItemType
    title: str
    description: str
    confidence: float
    source_message_ids: tuple[int, ...]
    rationale: str


@dataclass(frozen=True)
class ParsedExtractionResponse:
    items: tuple[ParsedExtractionItem, ...]
    status_changes: tuple[dict[str, Any], ...]


def parse_extraction_response(raw_json: str) -> ParsedExtractionResponse:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise LLMValidationError("response is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise LLMValidationError("response must be a JSON object")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise LLMValidationError("items must be a list")

    parsed_items = tuple(_parse_item(item) for item in raw_items)
    status_changes = payload.get("status_changes", [])
    if not isinstance(status_changes, list):
        raise LLMValidationError("status_changes must be a list")

    return ParsedExtractionResponse(items=parsed_items, status_changes=tuple(status_changes))


def _parse_item(raw_item: object) -> ParsedExtractionItem:
    if not isinstance(raw_item, dict):
        raise LLMValidationError("item must be an object")

    try:
        item_type = ItemType(str(raw_item["type"]))
        title = _require_str(raw_item, "title")
        description = _require_str(raw_item, "description")
        confidence = float(raw_item["confidence"])
        rationale = _require_str(raw_item, "rationale")
    except KeyError as exc:
        raise LLMValidationError(f"missing field: {exc.args[0]}") from exc
    except ValueError as exc:
        raise LLMValidationError("invalid item type or confidence") from exc

    if confidence < 0.0 or confidence > 1.0:
        raise LLMValidationError("confidence must be between 0 and 1")

    source_message_ids = raw_item.get("source_message_ids")
    if not isinstance(source_message_ids, list) or not all(isinstance(value, int) for value in source_message_ids):
        raise LLMValidationError("source_message_ids must be a list of integers")

    return ParsedExtractionItem(
        item_type=item_type,
        title=title,
        description=description,
        confidence=confidence,
        source_message_ids=tuple(source_message_ids),
        rationale=rationale,
    )


def _require_str(raw_item: dict[str, Any], field_name: str) -> str:
    value = raw_item[field_name]
    if not isinstance(value, str) or not value.strip():
        raise LLMValidationError(f"{field_name} must be a non-empty string")
    return value
