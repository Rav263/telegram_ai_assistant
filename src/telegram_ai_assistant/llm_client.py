from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .domain import ItemStatus, ItemType


DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_TOKENS = 8192
EXTRACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "telegram_extraction_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": [item_type.value for item_type in ItemType]},
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            "source_message_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": [
                            "type",
                            "title",
                            "description",
                            "confidence",
                            "source_message_ids",
                            "rationale",
                        ],
                        "additionalProperties": False,
                    },
                },
                "status_changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "new_status": {
                                "type": "string",
                                "enum": [status.value for status in ItemStatus],
                            },
                            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            "source_message_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": [
                            "item_id",
                            "new_status",
                            "confidence",
                            "source_message_ids",
                            "rationale",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["items", "status_changes"],
            "additionalProperties": False,
        },
    },
}


class LMStudioError(RuntimeError):
    def __init__(self, message: str, *, safe_metadata: Mapping[str, object] | None = None):
        super().__init__(message)
        self.safe_metadata = dict(safe_metadata or {})


Transport = Callable[[Request], object]


class LMStudioClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1234/v1",
        model: str = "local-model",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._transport = transport or self._default_transport

    def extract_json(self, *, messages: Sequence[Mapping[str, str]]) -> str:
        request = self._build_request(messages)
        try:
            response = self._transport(request)
            raw_body = _read_body(response)
            try:
                payload = json.loads(raw_body)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
                raise LMStudioError(
                    "LM Studio response was not valid JSON",
                    safe_metadata=_safe_response_metadata(
                        request,
                        None,
                        timeout=self.timeout,
                        max_tokens=self.max_tokens,
                        failure_stage="response_json",
                    ),
                ) from exc
            try:
                return _extract_assistant_content(payload)
            except LMStudioError as exc:
                raise LMStudioError(
                    str(exc),
                    safe_metadata=_safe_response_metadata(
                        request,
                        payload,
                        timeout=self.timeout,
                        max_tokens=self.max_tokens,
                        failure_stage="response_schema",
                    ),
                ) from exc
        except LMStudioError as exc:
            if exc.safe_metadata:
                raise
            raise LMStudioError(
                str(exc),
                safe_metadata=_safe_response_metadata(
                    request,
                    None,
                    timeout=self.timeout,
                    max_tokens=self.max_tokens,
                    failure_stage="response_read",
                ),
            ) from exc
        except Exception as exc:
            raise LMStudioError(
                "LM Studio chat completion request failed",
                safe_metadata=_safe_transport_metadata(
                    request,
                    exc,
                    timeout=self.timeout,
                    max_tokens=self.max_tokens,
                ),
            ) from exc

    def _build_request(self, messages: Sequence[Mapping[str, str]]) -> Request:
        body = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
            "max_tokens": self.max_tokens,
            "max_completion_tokens": self.max_tokens,
            "response_format": EXTRACTION_RESPONSE_FORMAT,
            "stream": False,
        }
        return Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    def _default_transport(self, request: Request) -> bytes:
        with urlopen(request, timeout=self.timeout) as response:
            return response.read()


def _read_body(response: object) -> bytes | str:
    if isinstance(response, bytes | str):
        return response
    if isinstance(response, Mapping):
        return json.dumps(response)
    read = getattr(response, "read", None)
    if callable(read):
        return read()
    raise LMStudioError("LM Studio response is not readable")


def _extract_assistant_content(payload: Any) -> str:
    try:
        choices = payload["choices"]
        content = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LMStudioError("LM Studio response did not include assistant content") from exc

    if not isinstance(content, str) or not content.strip():
        raise LMStudioError("LM Studio assistant content is empty")
    return content


def _safe_endpoint_metadata(request: Request, *, timeout: float, max_tokens: int) -> dict[str, object]:
    parsed = urlsplit(request.full_url)
    return {
        "endpoint_scheme": parsed.scheme,
        "endpoint_host": parsed.hostname or "",
        "endpoint_path": parsed.path,
        "timeout_seconds": timeout,
        "max_tokens": max_tokens,
        "max_completion_tokens": max_tokens,
    }


def _safe_transport_metadata(
    request: Request,
    error: BaseException,
    *,
    timeout: float,
    max_tokens: int,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        **_safe_endpoint_metadata(request, timeout=timeout, max_tokens=max_tokens),
        "transport_error_type": type(error).__name__,
    }
    status = getattr(error, "code", None)
    if isinstance(status, int):
        metadata["http_status"] = status
    return metadata


def _safe_response_metadata(
    request: Request,
    payload: object,
    *,
    timeout: float,
    max_tokens: int,
    failure_stage: str,
) -> dict[str, object]:
    metadata = {
        **_safe_endpoint_metadata(request, timeout=timeout, max_tokens=max_tokens),
        "failure_stage": failure_stage,
    }
    if isinstance(payload, Mapping):
        metadata["response_keys"] = sorted(str(key) for key in payload.keys())[:10]
        choices = payload.get("choices")
        if isinstance(choices, list):
            metadata["choices_count"] = len(choices)
            if choices and isinstance(choices[0], Mapping):
                first_choice = choices[0]
                metadata["choice_keys"] = sorted(str(key) for key in first_choice.keys())[:10]
                finish_reason = first_choice.get("finish_reason")
                if isinstance(finish_reason, str):
                    metadata["finish_reason"] = finish_reason
                message = first_choice.get("message")
                if isinstance(message, Mapping):
                    metadata["message_keys"] = sorted(str(key) for key in message.keys())[:10]
                    content = message.get("content")
                    metadata["content_type"] = type(content).__name__
                    if isinstance(content, str):
                        metadata["content_length"] = len(content)
                    reasoning_content = message.get("reasoning_content")
                    if isinstance(reasoning_content, str):
                        metadata["reasoning_content_length"] = len(reasoning_content)
    return metadata
