from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


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
        timeout: float = 30.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._transport = transport or self._default_transport

    def extract_json(self, *, messages: Sequence[Mapping[str, str]]) -> str:
        request = self._build_request(messages)
        try:
            response = self._transport(request)
            payload = json.loads(_read_body(response))
            return _extract_assistant_content(payload)
        except LMStudioError:
            raise
        except Exception as exc:
            raise LMStudioError(
                "LM Studio chat completion request failed",
                safe_metadata=_safe_transport_metadata(request, exc),
            ) from exc

    def _build_request(self, messages: Sequence[Mapping[str, str]]) -> Request:
        body = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
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


def _safe_transport_metadata(request: Request, error: BaseException) -> dict[str, object]:
    parsed = urlsplit(request.full_url)
    metadata: dict[str, object] = {
        "endpoint_scheme": parsed.scheme,
        "endpoint_host": parsed.hostname or "",
        "endpoint_path": parsed.path,
        "transport_error_type": type(error).__name__,
    }
    status = getattr(error, "code", None)
    if isinstance(status, int):
        metadata["http_status"] = status
    return metadata
