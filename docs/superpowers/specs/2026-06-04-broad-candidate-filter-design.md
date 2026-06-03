# Broad Candidate Filter Design

## Goal

Make the candidate filter broad enough that task-like Russian messages reliably reach LM Studio, even when they are phrased as casual notes rather than explicit commands.

The primary example for this slice is:

```text
Завтра нужно заехать на озон, забрать ирригатор
```

This message should be sent to the LLM with a strong score because it contains a time expression, task intent, and errand actions. The filter should prefer recall over precision: a few extra LLM calls are acceptable if they reduce missed tasks.

## Current State

The worker already queues every message with `score > 0` for LLM extraction. The weak point is the scoring layer:

- `score_message(message)` only receives a `Message`.
- The filter currently recognizes time expressions, owner commitments, implied requests, waiting states, and self-notes.
- The example message scores only `0.25` because only `Завтра` matches.
- `chat_type` exists in the chat storage layer, but it is not available to `score_message`.

## Scope

In scope:

- Broaden lexical rules for Russian personal tasks, errands, purchases, pickup, calls, payments, checks, notes, and reminders.
- Apply task-like markers to both incoming and outgoing messages.
- Add higher score and a dedicated reason for private chats.
- Keep group messages eligible for LLM extraction, but without private-chat priority.
- Preserve the existing worker behavior: positive score means queued candidate.
- Keep the implementation deterministic and unit-tested.

Out of scope:

- LLM-based pre-filtering.
- Reordering worker candidate processing by chat type.
- Per-chat custom scoring weights.
- Bot UI for changing filter settings.
- Non-text media analysis.

## Design

Introduce a lightweight scoring context:

```python
@dataclass(frozen=True)
class CandidateScoringContext:
    chat_type: str = ""
```

`score_message` becomes:

```python
def score_message(
    message: Message,
    context: CandidateScoringContext | None = None,
) -> CandidateScore:
    ...
```

Existing callers remain compatible because the context is optional.

The database-backed message source should join `chats` when reading pending messages for candidate filtering and attach chat context to the scoring call. The cleanest implementation is to keep `Message` unchanged and let the worker ask the source for optional scoring context:

```python
context = message_source.scoring_context_for(message)
candidate = scorer(message, context)
```

For tests and simple fake sources, the worker falls back to `None` when the method is absent.

## Reasons And Scores

Add new candidate reasons:

- `task_intent`: generic task markers such as `нужно`, `надо`, `не забыть`, `стоит`, `нужно бы`.
- `errand_action`: action verbs such as `заехать`, `забрать`, `купить`, `оплатить`, `позвонить`, `написать`, `проверить`, `отправить`, `записаться`, `заказать`.
- `logistics_context`: nouns or places that often indicate errands, such as `озон`, `пвз`, `доставка`, `аптека`, `магазин`, `документы`, `посылка`.
- `private_chat_priority`: score bonus when the message comes from a private chat.

Suggested weights:

- `time_expression`: `+0.25`
- `task_intent`: `+0.35`
- `errand_action`: `+0.35`
- `logistics_context`: `+0.15`
- `private_chat_priority`: `+0.15`
- existing reasons keep their current weights unless a test exposes a regression.

The example message in a private chat should score at least `0.8`:

```text
time_expression + task_intent + errand_action + logistics_context + private_chat_priority
```

The same message in a group should still score at least `0.6`, but lower than the private-chat version.

## Matching Rules

The filter remains regex-based and deterministic. Patterns should be broad but not single-word noisy when possible.

Task intent markers can match alone because user preference is recall-first, so abstract messages with `нужно` may still be sent to the LLM. Strong task scores, however, should come from combinations:

- task intent + errand action;
- time expression + errand action;
- errand action + logistics context;
- task intent + logistics context.

Weak examples should remain low, and clearly empty chatter should remain zero:

- `Нужно понимать контекст` can be a low-score candidate, but it should not get `errand_action`, `logistics_context`, or `private_chat_priority` unless those signals are actually present.
- `Привет` remains `0.0`.
- Group chatter with only weak abstract wording should not get private priority.

## Data Flow

1. Listener or backfill saves messages and chat metadata as today.
2. Worker reads pending messages.
3. Message source returns a `CandidateScoringContext` for each message when chat metadata is available.
4. Worker calls `score_message(message, context)`.
5. Positive scores are queued exactly as today, including the new reason strings.
6. LM Studio extraction decides whether the queued candidate becomes a task, reminder, thought, or no item.

## Testing

Follow TDD:

- Add failing filter tests for the Ozon pickup message in a private chat.
- Add a test that the same message in a group passes but has lower score and lacks `private_chat_priority`.
- Add a negative test for weak abstract `нужно` usage.
- Add worker tests proving the worker can pass scoring context when the message source provides it and remains compatible when it does not.
- Add repository tests proving pending message reads can provide chat type context without exposing raw private text in logs.

Run the full suite after implementation:

```bash
env PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

## Privacy And Safety

The filter must not log raw message text. New reason strings are safe to store because they describe rule categories, not private content.

The design does not change Telegram read-only behavior. It only affects which already-saved messages are queued for LLM processing.
