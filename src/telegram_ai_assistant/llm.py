from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from .domain import ItemStatus, ItemType, LLMActionType


class LLMValidationError(ValueError):
    pass


ALLOWED_UPDATE_FIELDS = frozenset({"title", "description", "due_at", "item_type"})


def action_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "telegram_action_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "actions": {
                        "type": "array",
                        "items": {
                            "oneOf": [_action_schema(action_type) for action_type in LLMActionType],
                        },
                    },
                },
                "required": ["actions"],
                "additionalProperties": False,
            },
        },
    }


def _action_schema(action_type: LLMActionType) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": [action_type.value]},
            "target_item_id": _nullable_string_schema(),
            "payload": _payload_schema(action_type),
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "source_message_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
            },
            "rationale": _string_schema(),
        },
        "required": [
            "type",
            "target_item_id",
            "payload",
            "confidence",
            "source_message_ids",
            "rationale",
        ],
        "additionalProperties": False,
    }


def _payload_schema(action_type: LLMActionType) -> dict[str, object]:
    if action_type == LLMActionType.CREATE_ITEM:
        return {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": [item_type.value for item_type in ItemType]},
                "title": _string_schema(),
                "description": _string_schema(),
                "due_at": _nullable_string_schema(),
                "metadata": {"type": "object"},
            },
            "required": ["type", "title", "description"],
            "additionalProperties": False,
        }
    if action_type == LLMActionType.UPDATE_ITEM_STATUS:
        return {
            "type": "object",
            "properties": {
                "new_status": {"type": "string", "enum": [status.value for status in ItemStatus]},
                "completed_at": _nullable_string_schema(),
            },
            "required": ["new_status"],
            "additionalProperties": False,
        }
    if action_type == LLMActionType.UPDATE_ITEM_FIELD:
        return {
            "type": "object",
            "properties": {
                "field": {"type": "string", "enum": sorted(ALLOWED_UPDATE_FIELDS)},
                "new_value": _nullable_string_schema(),
            },
            "required": ["field", "new_value"],
            "additionalProperties": False,
        }
    if action_type == LLMActionType.MERGE_DUPLICATE:
        return {
            "type": "object",
            "properties": {
                "duplicate_item_id": _string_schema(),
            },
            "required": ["duplicate_item_id"],
            "additionalProperties": False,
        }
    if action_type == LLMActionType.SCHEDULE_NOTIFICATION:
        return {
            "type": "object",
            "properties": {
                "due_at": _string_schema(),
                "notification_type": _string_schema(),
            },
            "required": ["due_at", "notification_type"],
            "additionalProperties": False,
        }
    if action_type == LLMActionType.LINK_SOURCE:
        return {
            "type": "object",
            "properties": {
                "source_message_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 1,
                },
            },
            "required": ["source_message_ids"],
            "additionalProperties": False,
        }
    return {"type": "object"}


def _string_schema() -> dict[str, object]:
    return {"type": "string", "minLength": 1}


def _nullable_string_schema() -> dict[str, object]:
    return {"type": ["string", "null"], "minLength": 1}


@dataclass(frozen=True)
class ParsedLLMAction:
    action_type: LLMActionType
    payload: dict[str, object]
    confidence: float
    source_message_ids: tuple[int, ...]
    rationale: str
    target_item_id: str | None = None


@dataclass(frozen=True)
class ParsedActionResponse:
    actions: tuple[ParsedLLMAction, ...]


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


def parse_action_response(raw_json: str) -> ParsedActionResponse:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise LLMValidationError("response is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise LLMValidationError("response must be a JSON object")

    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list):
        raise LLMValidationError("actions must be a list")

    return ParsedActionResponse(actions=tuple(_parse_action(action) for action in raw_actions))


def _parse_action(raw_action: object) -> ParsedLLMAction:
    if not isinstance(raw_action, dict):
        raise LLMValidationError("action must be an object")

    try:
        action_type = LLMActionType(str(raw_action["type"]))
        confidence = float(raw_action["confidence"])
        rationale = _require_str(raw_action, "rationale")
    except KeyError as exc:
        raise LLMValidationError(f"missing field: {exc.args[0]}") from exc
    except ValueError as exc:
        raise LLMValidationError("invalid action type or confidence") from exc

    if confidence < 0.0 or confidence > 1.0:
        raise LLMValidationError("confidence must be between 0 and 1")

    source_message_ids = raw_action.get("source_message_ids")
    if not isinstance(source_message_ids, list) or not source_message_ids:
        raise LLMValidationError("source_message_ids must be a non-empty list")
    if not all(isinstance(value, int) for value in source_message_ids):
        raise LLMValidationError("source_message_ids must be a list of integers")

    payload = raw_action.get("payload")
    if not isinstance(payload, dict):
        raise LLMValidationError("payload must be an object")

    target_item_id = raw_action.get("target_item_id")
    if target_item_id is not None and not isinstance(target_item_id, str):
        raise LLMValidationError("target_item_id must be a string")

    _validate_action_payload(action_type=action_type, payload=payload, target_item_id=target_item_id)
    _validate_russian_action_text(action_type=action_type, payload=payload, rationale=rationale)

    return ParsedLLMAction(
        action_type=action_type,
        payload=dict(payload),
        confidence=confidence,
        source_message_ids=tuple(source_message_ids),
        rationale=rationale,
        target_item_id=target_item_id,
    )


def _validate_action_payload(
    *,
    action_type: LLMActionType,
    payload: dict[str, object],
    target_item_id: str | None,
) -> None:
    if action_type == LLMActionType.CREATE_ITEM:
        _require_item_type(payload.get("type"))
        _require_payload_str(payload, "title")
        _require_payload_str(payload, "description")
        _validate_optional_due_at(payload.get("due_at"))
        return

    if action_type in {
        LLMActionType.UPDATE_ITEM_STATUS,
        LLMActionType.UPDATE_ITEM_FIELD,
        LLMActionType.MERGE_DUPLICATE,
        LLMActionType.LINK_SOURCE,
    } and not target_item_id:
        raise LLMValidationError("target_item_id is required")

    if action_type == LLMActionType.UPDATE_ITEM_STATUS:
        _require_item_status(payload.get("new_status"))
        _validate_optional_due_at(payload.get("completed_at"))
        return

    if action_type == LLMActionType.UPDATE_ITEM_FIELD:
        field = str(payload.get("field", ""))
        if field not in ALLOWED_UPDATE_FIELDS:
            raise LLMValidationError("invalid update field")
        if "new_value" not in payload:
            raise LLMValidationError("missing field: new_value")
        if field == "due_at":
            _validate_optional_due_at(payload.get("new_value"))
        if field == "item_type":
            _require_item_type(payload.get("new_value"))
        return

    if action_type == LLMActionType.MERGE_DUPLICATE:
        _require_payload_str(payload, "duplicate_item_id")
        return

    if action_type == LLMActionType.SCHEDULE_NOTIFICATION:
        _validate_due_at(payload.get("due_at"))
        _require_payload_str(payload, "notification_type")
        return

    if action_type == LLMActionType.LINK_SOURCE:
        linked_sources = payload.get("source_message_ids")
        if not isinstance(linked_sources, list) or not linked_sources:
            raise LLMValidationError("source_message_ids must be a non-empty list")


def _validate_russian_action_text(
    *,
    action_type: LLMActionType,
    payload: dict[str, object],
    rationale: str,
) -> None:
    values = [rationale]
    if action_type == LLMActionType.CREATE_ITEM:
        values.append(str(payload.get("title", "")))
        values.append(str(payload.get("description", "")))
    if action_type == LLMActionType.UPDATE_ITEM_FIELD and payload.get("field") in {"title", "description"}:
        values.append(str(payload.get("new_value", "")))
    for value in values:
        if not _has_cyrillic(value):
            raise LLMValidationError("user-facing text must be Russian")


def _has_cyrillic(value: str) -> bool:
    return any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in value)


def _require_payload_str(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise LLMValidationError(f"{field_name} must be a non-empty string")
    return value


def _require_item_type(value: object) -> None:
    try:
        ItemType(str(value))
    except ValueError as exc:
        raise LLMValidationError("invalid item type") from exc


def _require_item_status(value: object) -> None:
    try:
        ItemStatus(str(value))
    except ValueError as exc:
        raise LLMValidationError("invalid item status") from exc


def _validate_optional_due_at(value: object) -> None:
    if value is None:
        return
    _validate_due_at(value)


def _validate_due_at(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LLMValidationError("due_at must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise LLMValidationError("due_at must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LLMValidationError("due_at must be timezone-aware")


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
