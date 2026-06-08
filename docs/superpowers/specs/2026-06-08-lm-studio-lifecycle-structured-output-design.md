# LM Studio Lifecycle And Structured Output Design

Date: 2026-06-08

## Goal

Make the worker's LM Studio integration deterministic and inspectable:

- keep the configured model loaded with the intended runtime configuration;
- avoid disturbing unrelated models already loaded in LM Studio;
- explicitly unload the configured model before reloading it when its active parameters are wrong;
- use LM Studio/OpenAI-compatible structured output with a provided JSON schema for action extraction;
- keep all diagnostics safe for `/logs`.

## Problem

The worker currently calls LM Studio through `/v1/chat/completions` and already sends a `response_format` JSON schema. Model loading was added as a startup step, but it only posts `/api/v1/models/load` with `context_length`; it does not first inspect loaded instances, does not verify whether an existing instance already has the right config, and does not unload a mismatched instance before loading again.

This can leave LM Studio serving a model loaded manually or previously with an unsuitable context length. The result is fragile: context-size errors, repeated validation failures, and uncertainty about which model instance handled a request.

The current response schema is also broad around `payload`: LM Studio sees only `payload: object`, while the Python parser enforces action-specific payload rules later. That leaves avoidable format errors for the parser.

## Documentation Basis

LM Studio's current REST docs define:

- `GET /api/v1/models` for available models and each model's `loaded_instances`, including `id` and `config.context_length`.
- `POST /api/v1/models/load` for loading a model with configuration such as `context_length`, and `echo_load_config` to return the applied config.
- `POST /api/v1/models/unload` for unloading a loaded instance by `instance_id`.
- `/v1/chat/completions` structured output via `response_format.type=json_schema` and `response_format.json_schema.schema`; the JSON object still arrives as a string in `choices[0].message.content`.

References:

- https://lmstudio.ai/docs/developer/rest
- https://lmstudio.ai/docs/developer/rest/list
- https://lmstudio.ai/docs/developer/rest/load
- https://lmstudio.ai/docs/developer/rest/unload
- https://lmstudio.ai/docs/developer/openai-compat/structured-output
- https://lmstudio.ai/docs/developer/openai-compat/chat-completions

## Scope

In scope:

- Add an explicit model lifecycle method that lists, compares, unloads, and loads.
- Treat the configured `LM_STUDIO_MODEL` as the only model this app owns.
- Preserve unrelated loaded models.
- Unload mismatched loaded instances of the configured model before reloading.
- Unload a newly loaded instance if LM Studio reports an applied config that does not match the requested config.
- Move action structured output schema construction behind a provider function.
- Tighten the JSON schema so LM Studio gets action-level shape information.
- Add safe lifecycle diagnostics for `/logs`.
- Add local test guidance for a local LM Studio model and production smoke guidance for `192.168.0.10`.

Out of scope:

- Downloading missing models automatically.
- Multi-worker distributed locking.
- Managing multiple LM Studio model profiles.
- Changing the Telegram extraction business rules.
- Logging raw LLM responses or raw Telegram message text.

## Desired Configuration

Existing settings stay:

- `LM_STUDIO_BASE_URL`
- `LM_STUDIO_MODEL`
- `LM_STUDIO_MAX_TOKENS`
- `LM_STUDIO_CONTEXT_LENGTH`

The first implementation only compares `context_length`, because that is the parameter currently exposed in app settings and directly tied to the observed failure. The lifecycle code should be structured so future optional settings can be added without changing the flow:

- `eval_batch_size`
- `flash_attention`
- `offload_kv_cache_to_gpu`
- `num_experts`

## Model Lifecycle

Add `LMStudioClient.ensure_model_loaded()` and call it once from worker startup before the worker loop.

Flow:

1. Call `GET /api/v1/models`.
2. Find the model whose `key` equals configured `LM_STUDIO_MODEL`.
3. If the model is missing, fail with `LMStudioError` and safe metadata.
4. Inspect `loaded_instances`.
5. If an instance has a matching desired config, keep it and return.
6. If one or more instances of the configured model are loaded with mismatched config, unload each mismatched instance by `instance_id`.
7. Load the configured model with desired config using `POST /api/v1/models/load` and `echo_load_config=true`.
8. Validate the load response:
   - status is `loaded`;
   - response includes an `instance_id`;
   - echoed `load_config.context_length` equals requested `LM_STUDIO_CONTEXT_LENGTH` when present.
9. If validation fails after load and a new `instance_id` is available, call unload for that new instance before raising.

Important rule: do not unload models with a different `key`. The app only owns `LM_STUDIO_MODEL`.

## Request Endpoints

The client should derive native REST base URL from the OpenAI-compatible base:

- `http://host:1234/v1` -> `http://host:1234/api/v1/...`
- `http://host:1234/custom/v1` -> `http://host:1234/custom/api/v1/...`

Requests:

- list: `GET {native_base}/models`
- load: `POST {native_base}/models/load`
- unload: `POST {native_base}/models/unload`
- chat: unchanged `POST {openai_base}/chat/completions`

## Structured Output Schema

Replace the module-level `EXTRACTION_RESPONSE_FORMAT` constant with a schema provider such as:

```python
def action_response_format() -> dict[str, object]:
    ...
```

The schema should be passed into `LMStudioClient` or selected by `extract_json()`, instead of being hidden as a single global. This makes the client reusable and makes tests clearer.

Top-level schema:

- object with required `actions`;
- `actions` is an array;
- each action requires:
  - `type`;
  - `target_item_id`;
  - `payload`;
  - `confidence`;
  - `source_message_ids`;
  - `rationale`;
- `additionalProperties=false` where practical.

Payload schema:

- First implementation should provide action-level payload definitions through `oneOf` or equivalent JSON Schema constructs if LM Studio handles them reliably in tests.
- If local model testing shows `oneOf` causes unstable output, fall back to a conservative generic `payload: object` schema and keep parser-level validation. In that case, the schema provider still exists and the limitation is documented in tests/runbook.

The parser remains authoritative. Structured output reduces malformed responses but does not replace validation.

## Error Handling And Safe Diagnostics

Lifecycle failures should raise `LMStudioError` with safe metadata only:

- endpoint scheme, host, and path;
- HTTP status and transport error type when available;
- configured model key;
- desired context length;
- observed instance count;
- mismatched instance count;
- applied context length;
- failure stage.

Do not include:

- raw request body;
- raw response body;
- Telegram message text;
- model prompt content;
- bot token, API hash, database URL, session path.

`/logs` should allowlist any new safe keys needed to diagnose lifecycle errors.

## Runtime Behavior

Worker startup should fail fast if the configured model cannot be ensured. This is preferable to running cycles that repeatedly fail every batch.

Daemon behavior:

- `telegram-ai-assistant run worker`: ensure model once, then enter loop.
- `telegram-ai-assistant run worker --once`: ensure model once, process one cycle, exit.

If LM Studio auto-evicts the model while the daemon runs, a later chat request may fail. That can be handled in a later slice with retry-once and re-ensure; it is not required for the first implementation.

## Test Strategy

Unit tests:

- list request uses `GET /api/v1/models`.
- existing matching loaded instance does not unload or load.
- mismatched loaded instance unloads by `instance_id` before load.
- unrelated loaded model is not unloaded.
- missing configured model raises safe `LMStudioError`.
- newly loaded instance with mismatched echoed context is unloaded before raising.
- chat completion request includes provided structured output schema.
- schema provider includes top-level `actions` and action required fields.
- safe metadata and `/logs` allowlist lifecycle diagnostics.

Integration/smoke tests:

- local LM Studio can be tested with local `gemma-2b4`.
- production smoke can target `192.168.0.10` with `gemma-4-12b-qat` fully on GPU.
- smoke should call the lifecycle method first, then one small structured extraction prompt.

The production smoke should be opt-in and not part of default unit tests.

Verification command:

```bash
env PYTHONPATH=src python3 -m unittest discover -s tests
```

## Operations

Runbook should document:

- `LM_STUDIO_CONTEXT_LENGTH` controls load-time context length.
- Wrong active model parameters are corrected by unload then load.
- The app only unloads instances of `LM_STUDIO_MODEL`.
- For manual repair, use LM Studio's model list/load/unload endpoints or equivalent `lms` commands.
- Rebuild/restart `app-worker` after changing model lifecycle settings.
- Rebuild/restart `app-bot` when `/logs` allowlist changes.

## Rejected Alternatives

Always unload and reload on every worker start:

- simple but disruptive;
- wastes startup time;
- can interfere with a correctly loaded model.

Never unload, only load:

- may leave a wrong active instance in memory;
- does not meet the requirement to unload when parameters are wrong.

Use `/api/v1/chat` instead of `/v1/chat/completions`:

- native chat can specify `context_length` per request, but current extraction relies on OpenAI-compatible structured output and existing response parsing;
- switching inference endpoints is a larger behavior change and should be considered separately if structured output remains unstable.

## Acceptance Criteria

- Worker startup lists LM Studio models before loading.
- A correctly loaded configured model is reused.
- A configured model loaded with wrong `context_length` is unloaded before reloading.
- Unrelated loaded models are not touched.
- A bad load response triggers cleanup unload for the newly loaded instance when possible.
- Chat requests use an explicit provided JSON schema for structured output.
- Parser validation remains in place.
- Lifecycle failures are visible through safe `/logs` metadata.
- Full local test suite passes.
