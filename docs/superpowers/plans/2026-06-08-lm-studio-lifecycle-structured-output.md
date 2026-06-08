# LM Studio Lifecycle Structured Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure the configured LM Studio model is loaded with the correct context before worker cycles, unload mismatched configured instances before reload, and pass an explicit structured-output JSON schema for action extraction.

**Architecture:** Keep LM Studio transport in `LMStudioClient`, but split model lifecycle helpers from chat-completion request building. Move action response schema construction beside the parser in `llm.py`, then pass the schema from `ExtractionService.extract_batch()` into `LMStudioClient.extract_json()`. Worker startup remains the only automatic lifecycle entry point.

**Tech Stack:** Python 3.11, `urllib.request.Request`, `unittest`, LM Studio native REST `/api/v1/models*`, OpenAI-compatible `/v1/chat/completions`.

---

## Files

- Modify `src/telegram_ai_assistant/llm_client.py`: add list/unload/ensure lifecycle, response-format injection, safe metadata.
- Modify `src/telegram_ai_assistant/llm.py`: add `action_response_format()` schema provider tied to parser contract.
- Modify `src/telegram_ai_assistant/app_context.py`: call `ensure_model_loaded()` through the client factory.
- Modify `src/telegram_ai_assistant/extraction.py`: pass `action_response_format()` into `extract_json()`.
- Modify `src/telegram_ai_assistant/worker.py`: allowlist lifecycle safe metadata.
- Modify `src/telegram_ai_assistant/bot_services.py`: show lifecycle safe metadata in `/logs`.
- Modify `tests/test_llm_client.py`: lifecycle and request wiring tests.
- Modify `tests/test_llm.py`: schema provider tests.
- Modify `tests/test_app_context.py`: factory/runtime wiring expectations.
- Modify `tests/test_bot_services.py` and `tests/test_worker.py`: safe diagnostics expectations.
- Modify `docs/operations/local-runbook.md`: document unload/reload behavior and smoke targets.

## Task 1: Add Lifecycle Tests

**Files:**
- Modify: `tests/test_llm_client.py`

- [ ] **Step 1: Add helpers for request inspection**

Add this helper near `FakeResponse`:

```python
def request_json_body(request):
    return json.loads(request.data.decode("utf-8")) if request.data else None
```

- [ ] **Step 2: Add failing test for list request and reuse**

Add to `LMStudioClientTests`:

```python
def test_ensure_model_loaded_reuses_matching_loaded_instance(self):
    seen_requests = []

    def transport(request):
        seen_requests.append(request)
        return FakeResponse({
            "models": [
                {
                    "type": "llm",
                    "key": "google/gemma-4-12b-qat",
                    "loaded_instances": [
                        {
                            "id": "instance-ok",
                            "config": {"context_length": 8192},
                        }
                    ],
                }
            ]
        })

    client = LMStudioClient(
        base_url="http://192.168.0.10:1234/v1",
        model="google/gemma-4-12b-qat",
        context_length=8192,
        transport=transport,
    )

    client.ensure_model_loaded()

    self.assertEqual(len(seen_requests), 1)
    self.assertEqual(seen_requests[0].full_url, "http://192.168.0.10:1234/api/v1/models")
    self.assertEqual(seen_requests[0].get_method(), "GET")
```

- [ ] **Step 3: Run RED for reuse test**

Run:

```bash
env PYTHONPATH=src python3 -m unittest tests.test_llm_client.LMStudioClientTests.test_ensure_model_loaded_reuses_matching_loaded_instance
```

Expected: FAIL with `AttributeError: 'LMStudioClient' object has no attribute 'ensure_model_loaded'`.

- [ ] **Step 4: Add failing test for unload-before-load**

Add:

```python
def test_ensure_model_loaded_unloads_mismatched_instance_before_load(self):
    seen_requests = []

    def transport(request):
        seen_requests.append(request)
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse({
                "models": [
                    {
                        "type": "llm",
                        "key": "google/gemma-4-12b-qat",
                        "loaded_instances": [
                            {
                                "id": "instance-wrong",
                                "config": {"context_length": 4096},
                            }
                        ],
                    }
                ]
            })
        if request.full_url.endswith("/api/v1/models/unload"):
            return FakeResponse({"instance_id": "instance-wrong"})
        return FakeResponse({
            "type": "llm",
            "instance_id": "google/gemma-4-12b-qat",
            "status": "loaded",
            "load_config": {"context_length": 8192},
        })

    client = LMStudioClient(
        base_url="http://192.168.0.10:1234/v1",
        model="google/gemma-4-12b-qat",
        context_length=8192,
        transport=transport,
    )

    client.ensure_model_loaded()

    self.assertEqual([request.get_method() for request in seen_requests], ["GET", "POST", "POST"])
    self.assertEqual(seen_requests[1].full_url, "http://192.168.0.10:1234/api/v1/models/unload")
    self.assertEqual(request_json_body(seen_requests[1]), {"instance_id": "instance-wrong"})
    self.assertEqual(seen_requests[2].full_url, "http://192.168.0.10:1234/api/v1/models/load")
    self.assertEqual(request_json_body(seen_requests[2])["context_length"], 8192)
```

- [ ] **Step 5: Add failing test for mixed matching and mismatched configured instances**

Add:

```python
def test_ensure_model_loaded_unloads_mismatched_configured_instances_even_when_one_matches(self):
    seen_requests = []

    def transport(request):
        seen_requests.append(request)
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse({
                "models": [
                    {
                        "type": "llm",
                        "key": "google/gemma-4-12b-qat",
                        "loaded_instances": [
                            {"id": "instance-ok", "config": {"context_length": 8192}},
                            {"id": "instance-wrong", "config": {"context_length": 4096}},
                        ],
                    }
                ]
            })
        return FakeResponse({"instance_id": "instance-wrong"})

    client = LMStudioClient(
        base_url="http://192.168.0.10:1234/v1",
        model="google/gemma-4-12b-qat",
        context_length=8192,
        transport=transport,
    )

    client.ensure_model_loaded()

    self.assertEqual([request.full_url for request in seen_requests], [
        "http://192.168.0.10:1234/api/v1/models",
        "http://192.168.0.10:1234/api/v1/models/unload",
    ])
    self.assertEqual(request_json_body(seen_requests[1]), {"instance_id": "instance-wrong"})
```

- [ ] **Step 6: Add failing test for unrelated loaded models**

Add:

```python
def test_ensure_model_loaded_does_not_unload_other_models(self):
    seen_requests = []

    def transport(request):
        seen_requests.append(request)
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse({
                "models": [
                    {
                        "type": "llm",
                        "key": "other/model",
                        "loaded_instances": [
                            {"id": "other-instance", "config": {"context_length": 4096}}
                        ],
                    },
                    {
                        "type": "llm",
                        "key": "google/gemma-4-12b-qat",
                        "loaded_instances": [],
                    },
                ]
            })
        return FakeResponse({
            "type": "llm",
            "instance_id": "google/gemma-4-12b-qat",
            "status": "loaded",
            "load_config": {"context_length": 8192},
        })

    client = LMStudioClient(
        base_url="http://192.168.0.10:1234/v1",
        model="google/gemma-4-12b-qat",
        context_length=8192,
        transport=transport,
    )

    client.ensure_model_loaded()

    self.assertEqual([request.full_url for request in seen_requests], [
        "http://192.168.0.10:1234/api/v1/models",
        "http://192.168.0.10:1234/api/v1/models/load",
    ])
```

- [ ] **Step 7: Add failing test for missing configured model**

Add:

```python
def test_ensure_model_loaded_raises_safe_error_when_configured_model_missing(self):
    def transport(_request):
        return FakeResponse({"models": [{"type": "llm", "key": "other/model", "loaded_instances": []}]})

    client = LMStudioClient(
        base_url="http://192.168.0.10:1234/v1",
        model="google/gemma-4-12b-qat",
        context_length=8192,
        transport=transport,
    )

    with self.assertRaises(LMStudioError) as captured:
        client.ensure_model_loaded()

    self.assertEqual(captured.exception.safe_metadata["failure_stage"], "model_missing")
    self.assertEqual(captured.exception.safe_metadata["configured_model_key"], "google/gemma-4-12b-qat")
    self.assertEqual(captured.exception.safe_metadata["context_length"], 8192)
    self.assertEqual(captured.exception.safe_metadata["observed_model_count"], 1)
```

- [ ] **Step 8: Add failing test for cleanup unload after bad load response**

Add:

```python
def test_ensure_model_loaded_unloads_new_instance_when_load_applies_wrong_context(self):
    seen_requests = []

    def transport(request):
        seen_requests.append(request)
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse({
                "models": [
                    {"type": "llm", "key": "google/gemma-4-12b-qat", "loaded_instances": []}
                ]
            })
        if request.full_url.endswith("/api/v1/models/load"):
            return FakeResponse({
                "type": "llm",
                "instance_id": "new-instance",
                "status": "loaded",
                "load_config": {"context_length": 4096},
            })
        return FakeResponse({"instance_id": "new-instance"})

    client = LMStudioClient(
        base_url="http://192.168.0.10:1234/v1",
        model="google/gemma-4-12b-qat",
        context_length=8192,
        transport=transport,
    )

    with self.assertRaises(LMStudioError) as captured:
        client.ensure_model_loaded()

    self.assertEqual(seen_requests[-1].full_url, "http://192.168.0.10:1234/api/v1/models/unload")
    self.assertEqual(request_json_body(seen_requests[-1]), {"instance_id": "new-instance"})
    self.assertEqual(captured.exception.safe_metadata["failure_stage"], "model_load_config_mismatch")
    self.assertEqual(captured.exception.safe_metadata["configured_model_key"], "google/gemma-4-12b-qat")
    self.assertEqual(captured.exception.safe_metadata["applied_context_length"], 4096)
```

- [ ] **Step 9: Run RED for all lifecycle tests**

Run:

```bash
env PYTHONPATH=src python3 -m unittest tests.test_llm_client
```

Expected: lifecycle tests fail because lifecycle methods are missing.

## Task 2: Implement Lifecycle Methods

**Files:**
- Modify: `src/telegram_ai_assistant/llm_client.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: Add lifecycle public method and request builders**

In `LMStudioClient`, add methods with these signatures:

```python
def ensure_model_loaded(self) -> None:
    ...

def unload_model(self, instance_id: str) -> None:
    ...

def _build_list_models_request(self) -> Request:
    return Request(
        f"{_lm_studio_native_api_base_url(self.base_url)}/api/v1/models",
        headers={"Content-Type": "application/json"},
        method="GET",
    )

def _build_unload_request(self, instance_id: str) -> Request:
    return Request(
        f"{_lm_studio_native_api_base_url(self.base_url)}/api/v1/models/unload",
        data=json.dumps({"instance_id": instance_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
```

- [ ] **Step 2: Add JSON request helper**

Add private helper:

```python
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
```

- [ ] **Step 3: Implement model list parsing**

Add helpers:

```python
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
```

- [ ] **Step 4: Implement config matching and metadata**

Add helpers:

```python
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
```

- [ ] **Step 5: Implement `ensure_model_loaded()`**

Implementation outline:

```python
def ensure_model_loaded(self) -> None:
    payload = self._send_json_request(
        self._build_list_models_request(),
        failure_stage="model_list_response",
        context_length=self.context_length,
    )
    models = _models_from_payload(payload)
    configured_model = next(
        (model for model in models if model.get("key") == self.model),
        None,
    )
    if configured_model is None:
        raise LMStudioError(
            "Configured LM Studio model is not available",
            safe_metadata={
                "failure_stage": "model_missing",
                "configured_model_key": self.model,
                "context_length": self.context_length or 0,
                "observed_model_count": len(models),
                "observed_instance_count": 0,
                "mismatched_instance_count": 0,
            },
        )

    instances = _loaded_instances(configured_model)
    mismatched = [
        instance for instance in instances if not _instance_matches_context(instance, self.context_length)
    ]
    for instance in mismatched:
        instance_id = _instance_id(instance)
        if instance_id:
            self.unload_model(instance_id)

    if any(_instance_matches_context(instance, self.context_length) for instance in instances):
        return

    self.load_model()
```

- [ ] **Step 6: Change `load_model()` to return instance id and cleanup on mismatch**

Change `load_model()` to:

```python
def load_model(self) -> str | None:
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
        _validate_model_load_response(payload, context_length=self.context_length)
    except LMStudioError:
        if instance_id:
            self.unload_model(instance_id)
        raise
    return instance_id
```

Add helper:

```python
def _response_instance_id(payload: object) -> str:
    if not isinstance(payload, Mapping):
        return ""
    value = payload.get("instance_id")
    return value if isinstance(value, str) else ""
```

- [ ] **Step 7: Run GREEN for lifecycle tests**

Run:

```bash
env PYTHONPATH=src python3 -m unittest tests.test_llm_client
```

Expected: PASS.

- [ ] **Step 8: Commit lifecycle implementation**

Run:

```bash
git add src/telegram_ai_assistant/llm_client.py tests/test_llm_client.py
git commit -m "feat: reconcile lm studio model lifecycle"
```

## Task 3: Add Structured Output Schema Provider

**Files:**
- Modify: `src/telegram_ai_assistant/llm.py`
- Modify: `src/telegram_ai_assistant/llm_client.py`
- Modify: `src/telegram_ai_assistant/extraction.py`
- Test: `tests/test_llm.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/test_extraction.py`

- [ ] **Step 1: Write failing schema provider test**

In `tests/test_llm.py`, import `action_response_format` and add:

```python
def test_action_response_format_provides_strict_json_schema(self):
    response_format = action_response_format()

    self.assertEqual(response_format["type"], "json_schema")
    json_schema = response_format["json_schema"]
    self.assertEqual(json_schema["name"], "telegram_action_response")
    self.assertTrue(json_schema["strict"])
    schema = json_schema["schema"]
    self.assertEqual(schema["required"], ["actions"])
    branches = schema["properties"]["actions"]["items"]["oneOf"]
    action_schema = next(
        branch for branch in branches
        if branch["properties"]["type"]["enum"] == ["create_item"]
    )
    self.assertEqual(
        action_schema["required"],
        ["type", "target_item_id", "payload", "confidence", "source_message_ids", "rationale"],
    )
    self.assertFalse(action_schema["additionalProperties"])
```

- [ ] **Step 2: Add failing branch-count and fresh-dict tests**

Add:

```python
def test_action_response_format_has_one_branch_per_action_type(self):
    response_format = action_response_format()

    action_schema = response_format["json_schema"]["schema"]["properties"]["actions"]["items"]
    branches = action_schema["oneOf"]
    branch_types = {
        branch["properties"]["type"]["enum"][0]
        for branch in branches
    }

    self.assertEqual(branch_types, {action_type.value for action_type in LLMActionType})
```

Add:

```python
def test_action_response_format_returns_fresh_dict(self):
    first = action_response_format()
    second = action_response_format()

    first["json_schema"]["name"] = "mutated"

    self.assertEqual(second["json_schema"]["name"], "telegram_action_response")
```

- [ ] **Step 3: Run RED for schema provider**

Run:

```bash
env PYTHONPATH=src python3 -m unittest tests.test_llm.LLMParsingTests.test_action_response_format_provides_strict_json_schema
```

Expected: FAIL because `action_response_format` does not exist.

- [ ] **Step 4: Implement schema provider in `llm.py`**

Add:

```python
def action_response_format() -> dict[str, object]:
    action_branches = [_action_schema(action_type) for action_type in LLMActionType]
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "telegram_action_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "actions": {"type": "array", "items": {"oneOf": action_branches}},
                },
                "required": ["actions"],
                "additionalProperties": False,
            },
        },
    }
```

Add helper:

```python
def _action_schema(action_type: LLMActionType) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": [action_type.value]},
            "target_item_id": {"type": ["string", "null"]},
            "payload": _payload_schema(action_type),
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "source_message_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
            "rationale": {"type": "string"},
        },
        "required": ["type", "target_item_id", "payload", "confidence", "source_message_ids", "rationale"],
        "additionalProperties": False,
    }
```

Add `_payload_schema(action_type)` with parser-required fields for each action. Keep parser validation authoritative for Russian text and timezone awareness.

- [ ] **Step 5: Accept per-call response format in `LMStudioClient`**

Change signature:

```python
def extract_json(
    self,
    *,
    messages: Sequence[Mapping[str, str]],
    response_format: Mapping[str, object],
) -> str:
```

In `_build_request`, add parameter:

```python
def _build_request(
    self,
    messages: Sequence[Mapping[str, str]],
    *,
    response_format: Mapping[str, object],
) -> Request:
```

In `_build_request`, change:

```python
"response_format": dict(response_format),
```

- [ ] **Step 6: Pass provider from extraction service**

In `src/telegram_ai_assistant/extraction.py`, import `action_response_format` and call:

```python
raw_json = self._llm_client.extract_json(
    messages=prompt,
    response_format=action_response_format(),
)
```

- [ ] **Step 7: Update client tests**

In `tests/test_llm_client.py`, pass a sentinel `response_format` to `extract_json()`:

```python
content = client.extract_json(
    messages=[{"role": "user", "content": "extract"}],
    response_format=action_response_format(),
)
```

Replace client schema internals assertions with:

```python
def test_extract_json_uses_provided_response_format(self):
    seen_requests = []
    custom_format = {"type": "json_schema", "json_schema": {"name": "custom", "schema": {"type": "object"}}}

    def transport(request):
        seen_requests.append(request)
        return FakeResponse({"choices": [{"message": {"content": "{\"actions\": []}"}}]})

    client = LMStudioClient(transport=transport)

    client.extract_json(
        messages=[{"role": "user", "content": "extract"}],
        response_format=custom_format,
    )

    body = request_json_body(seen_requests[0])
    self.assertEqual(body["response_format"], custom_format)
```

- [ ] **Step 8: Update extraction test**

In `tests/test_extraction.py`, update fake client to capture `response_format`:

```python
class FakeLLMClient:
    def __init__(self, raw_json):
        self.raw_json = raw_json
        self.received_messages = None
        self.received_response_format = None

    def extract_json(self, *, messages, response_format):
        self.received_messages = messages
        self.received_response_format = response_format
        return self.raw_json
```

Assert:

```python
self.assertEqual(client.received_response_format["json_schema"]["name"], "telegram_action_response")
```

- [ ] **Step 9: Run GREEN for schema/provider tests**

Run:

```bash
env PYTHONPATH=src python3 -m unittest tests.test_llm tests.test_llm_client tests.test_extraction
```

Expected: PASS.

- [ ] **Step 10: Commit schema provider**

Run:

```bash
git add src/telegram_ai_assistant/llm.py src/telegram_ai_assistant/llm_client.py src/telegram_ai_assistant/extraction.py tests/test_llm.py tests/test_llm_client.py tests/test_extraction.py
git commit -m "feat: provide structured action response schema"
```

## Task 4: Safe Diagnostics And Runtime Docs

**Files:**
- Modify: `src/telegram_ai_assistant/worker.py`
- Modify: `src/telegram_ai_assistant/bot_services.py`
- Modify: `tests/test_worker.py`
- Modify: `tests/test_bot_services.py`
- Modify: `docs/operations/local-runbook.md`

- [ ] **Step 1: Add safe metadata keys**

Add these keys to `SAFE_LLM_FAILURE_METADATA_KEYS` and `SAFE_LOG_METADATA_KEYS`:

```python
"configured_model_key",
"observed_model_count",
"observed_instance_count",
"mismatched_instance_count",
"instance_id",
```

Keep existing `context_length` and `applied_context_length`.

- [ ] **Step 2: Add worker metadata test**

In `tests/test_worker.py`, extend `test_records_lm_failure_safe_diagnostics_without_raw_details` safe metadata with:

```python
"configured_model_key": "google/gemma-4-12b-qat",
"observed_model_count": 2,
"observed_instance_count": 1,
"mismatched_instance_count": 1,
"instance_id": "instance-wrong",
```

Assert those keys are preserved and `"raw"` is not.

- [ ] **Step 3: Add bot log formatting test**

In `tests/test_bot_services.py`, extend `test_logs_includes_allowlisted_lm_studio_diagnostics` metadata with the same keys and assert:

```python
self.assertIn("configured_model_key=google/gemma-4-12b-qat", text)
self.assertIn("observed_model_count=2", text)
self.assertIn("observed_instance_count=1", text)
self.assertIn("mismatched_instance_count=1", text)
self.assertIn("instance_id=instance-wrong", text)
```

- [ ] **Step 4: Run RED/GREEN for diagnostics**

Run:

```bash
env PYTHONPATH=src python3 -m unittest tests.test_worker tests.test_bot_services
```

Expected: PASS after allowlist changes.

- [ ] **Step 5: Update runbook**

In `docs/operations/local-runbook.md`, replace the LM Studio paragraph with text that states:

```markdown
On worker startup, the app lists LM Studio models through `/api/v1/models`. If `LM_STUDIO_MODEL`
is already loaded with `LM_STUDIO_CONTEXT_LENGTH`, it is reused. If the configured model is loaded
with different parameters, the worker unloads that instance through `/api/v1/models/unload` and then
loads it through `/api/v1/models/load`. Other loaded models are not touched.
```

Add smoke guidance:

```markdown
For local smoke testing, use a small local model such as `gemma-2b4`. For production smoke testing,
target `LM_STUDIO_BASE_URL=http://192.168.0.10:1234/v1` with `gemma-4-12b-qat` fully on GPU.
```

- [ ] **Step 6: Run docs tests**

Run:

```bash
env PYTHONPATH=src python3 -m unittest tests.test_operations_docs
```

Expected: PASS.

- [ ] **Step 7: Commit diagnostics/docs**

Run:

```bash
git add src/telegram_ai_assistant/worker.py src/telegram_ai_assistant/bot_services.py tests/test_worker.py tests/test_bot_services.py docs/operations/local-runbook.md
git commit -m "chore: document lm studio lifecycle diagnostics"
```

## Task 5: Verification And Optional Smoke

**Files:**
- No required code files.

- [ ] **Step 1: Run full unit suite**

Run:

```bash
env PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2: Check git diff**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: only expected untracked local cache directories remain; latest commits are the lifecycle/schema/docs commits.

- [ ] **Step 3: Optional local LM Studio smoke**

Run only when local LM Studio server is running and `gemma-2b4` is available:

```bash
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1 \
LM_STUDIO_MODEL=gemma-2b4 \
LM_STUDIO_CONTEXT_LENGTH=8192 \
env PYTHONPATH=src python3 -m unittest tests.test_llm_client
```

Expected: unit tests still pass; this does not perform a network integration by default.

- [ ] **Step 4: Optional production smoke**

Run only with explicit operator intent because it touches the production LM Studio server:

```bash
LM_STUDIO_BASE_URL=http://192.168.0.10:1234/v1 \
LM_STUDIO_MODEL=gemma-4-12b-qat \
LM_STUDIO_CONTEXT_LENGTH=8192 \
PYTHONPATH=src python3 -m telegram_ai_assistant.cli run worker --once
```

Expected: worker startup ensures the model, then either processes a batch or reports safe diagnostics. If model parameters are wrong, LM Studio logs should show unload followed by load.

- [ ] **Step 5: Final report**

Report:

- commit hashes;
- unit test result;
- whether optional local/prod smoke was run;
- any operational restart needed, usually:

```bash
docker compose up -d --build app-worker app-bot
```
