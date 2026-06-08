from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_TOKENS = 8192


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
        context_length: int | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.context_length = context_length
        self._transport = transport or self._default_transport

    def load_model(self) -> None:
        if self.context_length is None:
            return None
        request = self._build_load_request()
        payload = self._send_json_request(
            request,
            failure_stage="model_load_response",
            context_length=self.context_length,
        )
        instance_id = _response_instance_id(payload)
        try:
            _validate_model_load_response(
                payload,
                context_length=self.context_length,
                model=self.model,
                instance_id=instance_id,
            )
        except LMStudioError:
            if instance_id:
                self.unload_model(instance_id)
            raise
        return instance_id

    def ensure_model_loaded(self) -> None:
        request = self._build_list_models_request()
        payload = self._send_json_request(
            request,
            failure_stage="model_list_response",
            context_length=self.context_length,
        )
        models = _models_from_payload(payload)
        configured_model = next((model for model in models if model.get("key") == self.model), None)
        if configured_model is None:
            raise LMStudioError(
                "Configured LM Studio model is not available",
                safe_metadata={
                    **_safe_endpoint_metadata(
                        request,
                        timeout=self.timeout,
                        max_tokens=self.max_tokens,
                        context_length=self.context_length,
                    ),
                    "failure_stage": "model_missing",
                    "configured_model_key": self.model,
                    "observed_model_count": len(models),
                    "observed_instance_count": 0,
                    "mismatched_instance_count": 0,
                },
            )

        instances = _loaded_instances(configured_model)
        matching_instances = [
            instance for instance in instances if _instance_matches_context(instance, self.context_length)
        ]
        mismatched_instances = [
            instance for instance in instances if not _instance_matches_context(instance, self.context_length)
        ]

        for instance in mismatched_instances:
            instance_id = _instance_id(instance)
            if instance_id:
                self.unload_model(instance_id)

        if matching_instances:
            return

        self.load_model()

    def unload_model(self, instance_id: str) -> None:
        request = self._build_unload_request(instance_id)
        try:
            self._send_json_request(
                request,
                failure_stage="model_unload_failed",
                context_length=self.context_length,
            )
        except LMStudioError as exc:
            metadata = {
                **exc.safe_metadata,
                "failure_stage": "model_unload_failed",
                "configured_model_key": self.model,
                "instance_id": instance_id,
            }
            raise LMStudioError(str(exc), safe_metadata=metadata) from exc

    def extract_json(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        response_format: Mapping[str, object],
    ) -> str:
        request = self._build_request(messages, response_format=response_format)
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

    def _build_request(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        response_format: Mapping[str, object],
    ) -> Request:
        body = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
            "max_tokens": self.max_tokens,
            "max_completion_tokens": self.max_tokens,
            "response_format": dict(response_format),
            "stream": False,
        }
        return Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    def _build_list_models_request(self) -> Request:
        return Request(
            f"{_lm_studio_native_api_base_url(self.base_url)}/api/v1/models",
            headers={"Content-Type": "application/json"},
            method="GET",
        )

    def _build_load_request(self) -> Request:
        body = {
            "model": self.model,
            "context_length": self.context_length,
            "echo_load_config": True,
        }
        return Request(
            f"{_lm_studio_native_api_base_url(self.base_url)}/api/v1/models/load",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    def _build_unload_request(self, instance_id: str) -> Request:
        return Request(
            f"{_lm_studio_native_api_base_url(self.base_url)}/api/v1/models/unload",
            data=json.dumps({"instance_id": instance_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    def _default_transport(self, request: Request) -> bytes:
        with urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def _send_json_request(
        self,
        request: Request,
        *,
        failure_stage: str,
        context_length: int | None = None,
    ) -> object:
        try:
            response = self._transport(request)
            raw_body = _read_body(response)
            try:
                return json.loads(raw_body)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
                raise LMStudioError(
                    "LM Studio response was not valid JSON",
                    safe_metadata=_safe_response_metadata(
                        request,
                        None,
                        timeout=self.timeout,
                        max_tokens=self.max_tokens,
                        context_length=context_length,
                        failure_stage=f"{failure_stage}_json",
                    ),
                ) from exc
        except LMStudioError:
            raise
        except Exception as exc:
            raise LMStudioError(
                "LM Studio request failed",
                safe_metadata=_safe_transport_metadata(
                    request,
                    exc,
                    timeout=self.timeout,
                    max_tokens=self.max_tokens,
                    context_length=context_length,
                ),
            ) from exc


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


def _models_from_payload(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        raise LMStudioError("LM Studio models response must be an object")
    models = payload.get("models")
    if not isinstance(models, list):
        raise LMStudioError("LM Studio models response did not include models")
    return [model for model in models if isinstance(model, Mapping)]


def _loaded_instances(model: Mapping[str, object]) -> list[Mapping[str, object]]:
    instances = model.get("loaded_instances", [])
    if not isinstance(instances, list):
        return []
    return [instance for instance in instances if isinstance(instance, Mapping)]


def _instance_id(instance: Mapping[str, object]) -> str:
    value = instance.get("id")
    return value if isinstance(value, str) else ""


def _instance_context_length(instance: Mapping[str, object]) -> int | None:
    config = instance.get("config")
    if not isinstance(config, Mapping):
        return None
    value = config.get("context_length")
    return value if isinstance(value, int) else None


def _instance_matches_context(instance: Mapping[str, object], context_length: int | None) -> bool:
    if context_length is None:
        return True
    return _instance_context_length(instance) == context_length


def _response_instance_id(payload: object) -> str:
    if not isinstance(payload, Mapping):
        return ""
    value = payload.get("instance_id")
    return value if isinstance(value, str) else ""


def _validate_model_load_response(
    payload: Any,
    *,
    context_length: int,
    model: str,
    instance_id: str,
) -> None:
    if not isinstance(payload, Mapping):
        raise LMStudioError("LM Studio model load response must be an object")
    if payload.get("status") != "loaded":
        raise LMStudioError(
            "LM Studio model load response did not confirm loaded status",
            safe_metadata={
                "failure_stage": "model_load_response_schema",
                "configured_model_key": model,
                "context_length": context_length,
                "instance_id": instance_id,
                "response_keys": sorted(str(key) for key in payload.keys())[:10],
            },
        )
    if not instance_id:
        raise LMStudioError(
            "LM Studio model load response did not include instance id",
            safe_metadata={
                "failure_stage": "model_load_missing_instance_id",
                "configured_model_key": model,
                "context_length": context_length,
                "response_keys": sorted(str(key) for key in payload.keys())[:10],
            },
        )
    load_config = payload.get("load_config")
    if not isinstance(load_config, Mapping):
        return
    applied_context_length = load_config.get("context_length")
    if isinstance(applied_context_length, int) and applied_context_length != context_length:
        raise LMStudioError(
            "LM Studio model load response applied a different context length",
            safe_metadata={
                "failure_stage": "model_load_config_mismatch",
                "configured_model_key": model,
                "context_length": context_length,
                "instance_id": instance_id,
                "applied_context_length": applied_context_length,
            },
        )


def _lm_studio_native_api_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.rstrip("/"))
    path = parsed.path.rstrip("/")
    if path == "/v1" or path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "")).rstrip("/")


def _safe_endpoint_metadata(
    request: Request,
    *,
    timeout: float,
    max_tokens: int,
    context_length: int | None = None,
) -> dict[str, object]:
    parsed = urlsplit(request.full_url)
    metadata: dict[str, object] = {
        "endpoint_scheme": parsed.scheme,
        "endpoint_host": parsed.hostname or "",
        "endpoint_path": parsed.path,
        "timeout_seconds": timeout,
        "max_tokens": max_tokens,
        "max_completion_tokens": max_tokens,
    }
    metadata.update(_safe_request_body_metadata(request))
    if context_length is not None:
        metadata["context_length"] = context_length
    return metadata


def _safe_request_body_metadata(request: Request) -> dict[str, object]:
    data = request.data
    if not data:
        return {}
    metadata: dict[str, object] = {"request_body_bytes": len(data)}
    try:
        payload = json.loads(data)
    except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return metadata
    if not isinstance(payload, Mapping):
        return metadata

    model = payload.get("model")
    if isinstance(model, str):
        metadata["configured_model_key"] = model

    messages = payload.get("messages")
    if isinstance(messages, list):
        metadata["message_count"] = len(messages)
        prompt_characters = 0
        for message in messages:
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    prompt_characters += len(content)
        metadata["prompt_characters"] = prompt_characters

    response_format = payload.get("response_format")
    if isinstance(response_format, Mapping):
        json_schema = response_format.get("json_schema")
        if isinstance(json_schema, Mapping):
            schema_name = json_schema.get("name")
            if isinstance(schema_name, str):
                metadata["response_format_name"] = schema_name

    return metadata


def _safe_transport_metadata(
    request: Request,
    error: BaseException,
    *,
    timeout: float,
    max_tokens: int,
    context_length: int | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        **_safe_endpoint_metadata(
            request,
            timeout=timeout,
            max_tokens=max_tokens,
            context_length=context_length,
        ),
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
    context_length: int | None = None,
) -> dict[str, object]:
    metadata = {
        **_safe_endpoint_metadata(
            request,
            timeout=timeout,
            max_tokens=max_tokens,
            context_length=context_length,
        ),
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
