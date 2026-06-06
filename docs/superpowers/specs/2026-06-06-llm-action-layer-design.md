# LLM Action Layer Design

## Goal

Replace direct LLM persistence decisions with an audited proposal layer. The LLM proposes typed actions, the application validates and stores them, policy decides whether to auto-apply or review, and the bot lets the owner approve or reject non-auto actions.

This design keeps the current worker and bot behavior compatible while creating a safer foundation for item edits, reminders, duplicate handling, and future proactive notifications.

## Decisions

- Use a hybrid cutover.
- Route `create_item` through the new action layer.
- Auto-apply only high-confidence `create_item` actions.
- Send all other action types to review first.
- Add `llm_actions` as the action ledger.
- Keep `review_queue` as the owner-facing review queue and add an optional action reference.
- Give the LLM global open-item context across chats, bounded by a configurable cap.
- Use deterministic idempotency keys based on action type, source ids, optional target item id, and normalized payload hash.
- Include `create_item`, `update_item_status`, `update_item_field`, `merge_duplicate`, `schedule_notification`, and `link_source` in the first action set.
- Group `/review` output by source message.
- Require all LLM-produced user-facing text to be in Russian.

## Architecture

Current path:

```text
messages -> candidate filter -> LLM JSON -> items/status_changes -> item_repository/review_queue
```

New path:

```text
messages + global open items
-> LLM action proposals
-> llm_actions
-> action policy
-> item_repository or review_queue
-> bot approval/rejection
```

Core components:

- `LLMAction`: typed proposal from the model.
- `LLMActionSource`: source message reference for audit and bot grouping.
- `LLMActionDecision`: policy result such as auto-apply, review, or reject.
- `LLMActionPolicy`: deterministic application policy.
- `LLMActionRepository`: storage and state transitions for proposals.

The LLM never mutates application state directly. It only produces proposed actions. Application code validates every action before storage and again before approval-time application.

## Database Model

Add `llm_actions`.

Required fields:

- `llm_action_id`: primary key.
- `action_key`: unique deterministic idempotency key.
- `action_type`: enum-like text.
- `state`: pending, review, applied, rejected, failed, ignored.
- `confidence`: numeric 0..1.
- `target_item_id`: nullable item id.
- `payload`: JSONB normalized action payload.
- `source_refs`: JSONB bounded source references.
- `rationale`: text.
- `created_at`, `updated_at`, `applied_at`, `rejected_at`: timestamps where applicable.

Extend `review_queue`:

- Add nullable `llm_action_id` or equivalent action reference.
- Keep existing `payload`, `review_type`, and legacy item-review fields for compatibility.

Retries must not create duplicate actions. A repeated LLM batch with equivalent proposal data must upsert or reuse the existing `action_key`.

## Action Schemas

### `create_item`

Payload:

- `type`
- `title`
- `description`
- `due_at`
- `metadata`
- source refs
- rationale

Policy:

- Auto-apply when confidence is at or above the item threshold.
- Otherwise create a review entry.

### `update_item_status`

Payload:

- `target_item_id`
- `new_status`
- optional `completed_at`
- rationale

Policy:

- Always review in the first release.

### `update_item_field`

Payload:

- `target_item_id`
- `field`
- `new_value`
- rationale

Allowed fields:

- `title`
- `description`
- `due_at`
- `item_type`

Policy:

- Always review in the first release.

### `merge_duplicate`

Payload:

- `target_item_id`
- `duplicate_item_id`
- optional `merged_title`
- rationale

Policy:

- Always review in the first release.

### `schedule_notification`

Payload:

- optional `target_item_id`
- `due_at`
- `notification_type`
- rationale

Policy:

- Always review in the first release.
- Store proposals now. Dispatch waits for the future notification runtime.

### `link_source`

Payload:

- `target_item_id`
- source refs
- rationale

Policy:

- Always review in the first release.

## Validation

Validation must reject malformed or unsafe actions before policy evaluation.

Rules:

- `action_type` must be known.
- `confidence` must be between 0 and 1.
- Source refs must come from the candidate batch.
- Target item ids must exist in the provided open-item context, except for `create_item`.
- Due dates must be timezone-aware ISO timestamps or null.
- Status values must match `ItemStatus`.
- Item types must match `ItemType`.
- Field updates must target an allowed field.
- Payload must be normalized before action key hashing.

Malformed actions produce a sanitized runtime event. Runtime events must not include raw Telegram text, prompts, secrets, tracebacks, bot tokens, API hashes, database URLs, or Telegram session content.

## LLM Context

The prompt includes candidate messages and global open items.

Candidate message fields:

- `account_id`
- `chat_id`
- `telegram_message_id`
- `direction`
- `sent_at`
- `text` or `caption`
- `reply_to_message_id`

Open item fields:

- `item_id`
- `type`
- `title`
- `status`
- `due_at`
- source refs
- created or updated recency where available

Limits:

- Candidate message count uses the current worker batch size.
- Open-item count is configurable, defaulting to 200.
- Long text and snippets are truncated.
- No full chat history is sent.
- No secrets, environment values, Telegram session data, or raw database URLs are sent.

Prompt rules:

- Propose actions only.
- Never claim that a database update has already happened.
- Prefer updating or linking an existing item over creating a duplicate.
- Status updates require explicit evidence from owner messages or clear context.
- Reminders and time commitments may produce both `create_item` and `schedule_notification`.
- Include rationale and confidence for every action.
- All user-facing generated text must be in Russian.
- Internal enum values, action types, and JSON keys remain English.
- Output must match the strict JSON schema.

Required example behavior:

- `Завтра нужно заехать на озон, забрать ирригатор` produces a Russian `create_item` and a `schedule_notification`.
- `Сделал`, `забрал`, or `отправил` near an existing item produces `update_item_status`.
- Repeated mention of the same task produces `link_source` or `merge_duplicate`, not a duplicate `create_item`.

## Worker Policy

The worker changes from direct item/status persistence to action persistence and policy application.

Processing steps:

1. Read queued candidate messages.
2. Load bounded global open-item context.
3. Call LM Studio for action proposals.
4. Parse typed actions.
5. Validate sources, targets, payloads, and dates.
6. Persist actions with deterministic `action_key`.
7. Apply policy.
8. Auto-apply high-confidence `create_item`.
9. Queue reviews for all other action types and low-confidence create actions.
10. Mark candidates processed only after all persistence and policy handling succeeds.

Failure behavior:

- LLM request or response failure keeps candidates queued for retry.
- Invalid whole-response structure fails the batch and records a safe event.
- Individual malformed actions may initially fail the batch for simpler retry semantics; later versions can reject individual actions.

## Bot Review Behavior

`/review` reads pending `review_queue` entries backed by `llm_actions` and groups them by primary source message.

Each group shows:

- bounded source snippet;
- action type;
- target item or new item title;
- proposed status or field value where relevant;
- confidence;
- rationale.

Buttons:

- Approve action.
- Reject action.
- Open target item where relevant.
- Later: approve all and reject all for a group.

Approve flow:

1. Load the `llm_actions` row.
2. Revalidate action state and payload.
3. Apply through service-layer code.
4. Mark action `applied`.
5. Mark review `approved`.
6. Write item status/audit events where relevant.

Reject flow:

1. Mark action `rejected`.
2. Mark review `rejected`.
3. Do not mutate items.

Compatibility:

- Legacy item reviews still render and work.
- Existing `review:*` callback namespace remains supported.
- `/tasks` owner status buttons continue to apply direct owner-driven status changes.

## Rollout Plan

Slice 1: schema/domain/repository.

- Add `llm_actions`.
- Add `review_queue` action reference.
- Add deterministic action key helper.
- Add repository CRUD and state transitions.

Slice 2: typed parser/schema.

- Add `ParsedLLMAction`.
- Add strict LM Studio JSON schema.
- Add Russian-output prompt rule.
- Add validation for source refs, target ids, statuses, fields, and dates.

Slice 3: worker policy cutover.

- Build prompt from candidates plus global open items.
- Persist actions.
- Auto-apply only high-confidence `create_item`.
- Review all other actions.
- Disable legacy raw `status_changes` persistence path.

Slice 4: bot review rendering.

- Group action reviews by source message.
- Add approve/reject action callbacks.
- Keep legacy review compatibility.

Slice 5: evaluation corpus.

- Add synthetic or anonymized Russian fixtures for tasks, reminders, commitments, completions, duplicates, and source linking.
- Add golden expected action types and key fields.
- Do not commit private real Telegram text unless anonymized.

## Testing

Required tests:

- Parser accepts valid action JSON and rejects malformed action JSON.
- Parser enforces Russian user-facing output rule where practical with synthetic fixtures.
- Repository upserts by deterministic action key.
- Repository transitions states safely.
- Worker retry does not duplicate actions.
- Worker auto-applies only high-confidence `create_item`.
- Worker reviews status updates, field updates, duplicate merges, notifications, and links.
- Bot renders action reviews grouped by source message.
- Bot approve/reject callbacks apply or reject actions safely.
- Legacy review entries remain usable.
- Runtime event sanitization does not leak message text or secrets.

## Pass Criteria

- Example `Завтра нужно заехать на озон, забрать ирригатор` yields a Russian `create_item` and a `schedule_notification`.
- Repeated worker retry does not duplicate actions.
- Status updates require review.
- High-confidence create item still appears in `/tasks`.
- `/review` can approve and reject action proposals.
- Existing `/summary`, `/tasks`, `/logs`, `/health`, `/backfill`, `/blacklist`, and shell navigation remain stable.
- Full test suite passes.

## Out Of Scope

- Dispatching scheduled notifications.
- Free-form conversational editing.
- Arbitrary LLM tool calls.
- Remote LLM providers.
- Bot-driven secret configuration.
- Database restore or destructive ops actions.

## Self-Review

- Placeholder scan: no unfinished markers remain.
- Scope check: this spec is one medium feature with five implementation slices.
- Safety check: the LLM cannot directly mutate state; every mutation passes through validation and policy.
- Compatibility check: legacy review entries and current bot commands remain supported.
- Language check: all LLM-produced user-facing content is required to be Russian, while internal enum keys remain English.
