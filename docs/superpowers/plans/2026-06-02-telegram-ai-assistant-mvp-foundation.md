# Telegram AI Assistant MVP Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first tested foundation for the Telegram AI assistant: domain types, semantic candidate filtering, status updates, LLM JSON validation, owner-only bot access, and read-only Telegram guard.

**Architecture:** Implement a small Python package with pure, dependency-free core modules first. External Telegram, Bot API, Postgres, and LM Studio adapters will be added in later plans on top of these tested interfaces.

**Tech Stack:** Python 3.11+, standard library `dataclasses`, `enum`, `datetime`, `json`, `unittest`, `pyproject.toml` with `src/` layout.

---

## File Structure

- Create `pyproject.toml`: package metadata for the `src/` layout.
- Create `src/telegram_ai_assistant/__init__.py`: package marker and version.
- Create `src/telegram_ai_assistant/domain.py`: message, item, status, and source reference dataclasses/enums.
- Create `src/telegram_ai_assistant/filtering.py`: broad semantic candidate filter for text messages.
- Create `src/telegram_ai_assistant/status.py`: pure status transition helpers and confidence policy.
- Create `src/telegram_ai_assistant/llm.py`: strict JSON parser/validator for LM Studio extraction output.
- Create `src/telegram_ai_assistant/security.py`: owner-only bot access control.
- Create `src/telegram_ai_assistant/telegram_readonly.py`: read-only Telegram adapter guard.
- Create `tests/test_domain.py`: domain model tests.
- Create `tests/test_filtering.py`: candidate filter tests.
- Create `tests/test_status.py`: status transition tests.
- Create `tests/test_llm.py`: LLM JSON validation tests.
- Create `tests/test_security.py`: bot access tests.
- Create `tests/test_telegram_readonly.py`: read-only guard tests.

## Task 1: Project Scaffold And Domain Types

**Files:**
- Create: `pyproject.toml`
- Create: `src/telegram_ai_assistant/__init__.py`
- Create: `src/telegram_ai_assistant/domain.py`
- Test: `tests/test_domain.py`

- [ ] **Step 1: Write the failing domain tests**

Create `tests/test_domain.py`:

```python
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import (
    ExtractedItem,
    ItemStatus,
    ItemType,
    Message,
    MessageDirection,
    SourceRef,
)


class DomainTests(unittest.TestCase):
    def test_message_requires_text_or_caption_for_text_content(self):
        message = Message(
            account_id="main",
            chat_id=100,
            telegram_message_id=200,
            sender_id=300,
            direction=MessageDirection.INCOMING,
            sent_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
            text="",
            caption="Перезвоню через 30 минут",
        )

        self.assertEqual(message.content_text, "Перезвоню через 30 минут")

    def test_extracted_item_keeps_source_refs_and_default_open_status(self):
        source = SourceRef(chat_id=100, telegram_message_id=200)
        item = ExtractedItem(
            item_id="item-1",
            item_type=ItemType.COMMITMENT,
            title="Перезвонить",
            description="Автор обещал перезвонить через 30 минут.",
            confidence=0.9,
            sources=(source,),
        )

        self.assertEqual(item.status, ItemStatus.OPEN)
        self.assertEqual(item.sources, (source,))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the domain tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_domain -v
```

Expected: FAIL because `telegram_ai_assistant.domain` does not exist.

- [ ] **Step 3: Write the minimal project scaffold and domain implementation**

Create `pyproject.toml`:

```toml
[project]
name = "telegram-ai-assistant"
version = "0.1.0"
description = "Local-first Telegram AI assistant"
requires-python = ">=3.11"
dependencies = []

[tool.setuptools.packages.find]
where = ["src"]
```

Create `src/telegram_ai_assistant/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `src/telegram_ai_assistant/domain.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class ItemType(StrEnum):
    TASK = "task"
    THOUGHT = "thought"
    COMMITMENT = "commitment"
    REMINDER = "reminder"
    WAITING_FOR = "waiting_for"
    USEFUL_CONTEXT = "useful_context"


class ItemStatus(StrEnum):
    CANDIDATE = "candidate"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OBSOLETE = "obsolete"
    WAITING_FOR = "waiting_for"


@dataclass(frozen=True)
class SourceRef:
    chat_id: int
    telegram_message_id: int


@dataclass(frozen=True)
class Message:
    account_id: str
    chat_id: int
    telegram_message_id: int
    sender_id: int
    direction: MessageDirection
    sent_at: datetime
    text: str = ""
    caption: str = ""
    reply_to_message_id: int | None = None

    @property
    def content_text(self) -> str:
        return self.text.strip() or self.caption.strip()


@dataclass(frozen=True)
class ExtractedItem:
    item_id: str
    item_type: ItemType
    title: str
    description: str
    confidence: float
    sources: tuple[SourceRef, ...]
    status: ItemStatus = ItemStatus.OPEN
    rationale: str = ""
    due_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)
```

- [ ] **Step 4: Run the domain tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_domain -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add pyproject.toml src/telegram_ai_assistant/__init__.py src/telegram_ai_assistant/domain.py tests/test_domain.py
git commit -m "feat: add core domain types"
```

## Task 2: Broad Candidate Filter

**Files:**
- Create: `src/telegram_ai_assistant/filtering.py`
- Test: `tests/test_filtering.py`

- [ ] **Step 1: Write the failing candidate filter tests**

Create `tests/test_filtering.py`:

```python
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.filtering import CandidateReason, score_message


def make_message(text: str, direction: MessageDirection = MessageDirection.OUTGOING) -> Message:
    return Message(
        account_id="main",
        chat_id=100,
        telegram_message_id=200,
        sender_id=300,
        direction=direction,
        sent_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
        text=text,
    )


class CandidateFilterTests(unittest.TestCase):
    def test_flags_implicit_copy_task_without_direct_task_word(self):
        result = score_message(make_message("Если там сейчас есть что-то важное, то скопируйте это оттуда."))

        self.assertGreaterEqual(result.score, 0.6)
        self.assertIn(CandidateReason.IMPLIED_REQUEST, result.reasons)

    def test_flags_owner_time_commitment(self):
        result = score_message(make_message("Через минут 30-40 перезвоню"))

        self.assertGreaterEqual(result.score, 0.7)
        self.assertIn(CandidateReason.TIME_EXPRESSION, result.reasons)
        self.assertIn(CandidateReason.OWNER_COMMITMENT, result.reasons)

    def test_ignores_empty_text(self):
        result = score_message(make_message("   "))

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.reasons, ())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the candidate filter tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_filtering -v
```

Expected: FAIL because `telegram_ai_assistant.filtering` does not exist.

- [ ] **Step 3: Write the minimal candidate filter implementation**

Create `src/telegram_ai_assistant/filtering.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .domain import Message, MessageDirection


class CandidateReason(StrEnum):
    TIME_EXPRESSION = "time_expression"
    OWNER_COMMITMENT = "owner_commitment"
    IMPLIED_REQUEST = "implied_request"
    WAITING_STATE = "waiting_state"
    SELF_NOTE = "self_note"


@dataclass(frozen=True)
class CandidateScore:
    score: float
    reasons: tuple[CandidateReason, ...]


TIME_RE = re.compile(r"\b(через|завтра|сегодня|потом|на неделе|минут|час|дней|дня)\b", re.IGNORECASE)
COMMITMENT_RE = re.compile(r"\b(перезвоню|посмотрю|отправлю|сделаю|разберу|проверю|напишу)\b", re.IGNORECASE)
IMPLIED_REQUEST_RE = re.compile(r"\b(скопируйте|скопировать|заберите|передайте|если там|важное)\b", re.IGNORECASE)
WAITING_RE = re.compile(r"\b(жду|ожидаю|дождаться|пока от них|когда пришлют)\b", re.IGNORECASE)
SELF_NOTE_RE = re.compile(r"\b(надо бы|нужно будет|идея|мысль|заметка)\b", re.IGNORECASE)


def score_message(message: Message) -> CandidateScore:
    text = message.content_text
    if not text:
        return CandidateScore(score=0.0, reasons=())

    reasons: list[CandidateReason] = []
    score = 0.0

    if TIME_RE.search(text):
        reasons.append(CandidateReason.TIME_EXPRESSION)
        score += 0.25
    if message.direction == MessageDirection.OUTGOING and COMMITMENT_RE.search(text):
        reasons.append(CandidateReason.OWNER_COMMITMENT)
        score += 0.45
    if IMPLIED_REQUEST_RE.search(text):
        reasons.append(CandidateReason.IMPLIED_REQUEST)
        score += 0.6
    if WAITING_RE.search(text):
        reasons.append(CandidateReason.WAITING_STATE)
        score += 0.4
    if SELF_NOTE_RE.search(text):
        reasons.append(CandidateReason.SELF_NOTE)
        score += 0.35

    return CandidateScore(score=min(score, 1.0), reasons=tuple(dict.fromkeys(reasons)))
```

- [ ] **Step 4: Run the candidate filter tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_filtering -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/telegram_ai_assistant/filtering.py tests/test_filtering.py
git commit -m "feat: add broad candidate filter"
```

## Task 3: Status Transition Policy

**Files:**
- Create: `src/telegram_ai_assistant/status.py`
- Test: `tests/test_status.py`

- [ ] **Step 1: Write the failing status tests**

Create `tests/test_status.py`:

```python
import unittest

from telegram_ai_assistant.domain import ItemStatus
from telegram_ai_assistant.status import ProposedStatusChange, ReviewDecision, apply_status_policy


class StatusPolicyTests(unittest.TestCase):
    def test_high_confidence_status_change_is_applied(self):
        change = ProposedStatusChange(
            item_id="task-1",
            new_status=ItemStatus.COMPLETED,
            confidence=0.91,
            rationale="Owner wrote that payment was sent.",
        )

        decision = apply_status_policy(change, auto_apply_threshold=0.85)

        self.assertEqual(decision, ReviewDecision.APPLY)

    def test_low_confidence_status_change_goes_to_review(self):
        change = ProposedStatusChange(
            item_id="task-1",
            new_status=ItemStatus.PARTIALLY_COMPLETED,
            confidence=0.62,
            rationale="Owner may have completed one part.",
        )

        decision = apply_status_policy(change, auto_apply_threshold=0.85)

        self.assertEqual(decision, ReviewDecision.REVIEW)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the status tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_status -v
```

Expected: FAIL because `telegram_ai_assistant.status` does not exist.

- [ ] **Step 3: Write the minimal status policy implementation**

Create `src/telegram_ai_assistant/status.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .domain import ItemStatus


class ReviewDecision(StrEnum):
    APPLY = "apply"
    REVIEW = "review"


@dataclass(frozen=True)
class ProposedStatusChange:
    item_id: str
    new_status: ItemStatus
    confidence: float
    rationale: str


def apply_status_policy(
    change: ProposedStatusChange,
    *,
    auto_apply_threshold: float,
) -> ReviewDecision:
    if change.confidence >= auto_apply_threshold:
        return ReviewDecision.APPLY
    return ReviewDecision.REVIEW
```

- [ ] **Step 4: Run the status tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_status -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/telegram_ai_assistant/status.py tests/test_status.py
git commit -m "feat: add status review policy"
```

## Task 4: LM Studio Extraction JSON Validation

**Files:**
- Create: `src/telegram_ai_assistant/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing LLM parsing tests**

Create `tests/test_llm.py`:

```python
import json
import unittest

from telegram_ai_assistant.domain import ItemType
from telegram_ai_assistant.llm import LLMValidationError, parse_extraction_response


class LLMParsingTests(unittest.TestCase):
    def test_parse_valid_extraction_response(self):
        payload = json.dumps({
            "items": [
                {
                    "type": "commitment",
                    "title": "Перезвонить",
                    "description": "Автор обещал перезвонить через 30-40 минут.",
                    "confidence": 0.93,
                    "source_message_ids": [200],
                    "rationale": "Фраза содержит личное обещание и время.",
                }
            ],
            "status_changes": [],
        })

        result = parse_extraction_response(payload)

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].item_type, ItemType.COMMITMENT)
        self.assertEqual(result.items[0].source_message_ids, (200,))

    def test_rejects_invalid_confidence(self):
        payload = json.dumps({
            "items": [
                {
                    "type": "task",
                    "title": "Bad",
                    "description": "Bad",
                    "confidence": 2.0,
                    "source_message_ids": [200],
                    "rationale": "Bad",
                }
            ],
            "status_changes": [],
        })

        with self.assertRaises(LLMValidationError):
            parse_extraction_response(payload)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the LLM tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_llm -v
```

Expected: FAIL because `telegram_ai_assistant.llm` does not exist.

- [ ] **Step 3: Write the minimal LLM validation implementation**

Create `src/telegram_ai_assistant/llm.py`:

```python
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
```

- [ ] **Step 4: Run the LLM tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_llm -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add src/telegram_ai_assistant/llm.py tests/test_llm.py
git commit -m "feat: validate LLM extraction output"
```

## Task 5: Owner-Only Bot Access Control

**Files:**
- Create: `src/telegram_ai_assistant/security.py`
- Test: `tests/test_security.py`

- [ ] **Step 1: Write the failing access control tests**

Create `tests/test_security.py`:

```python
import unittest

from telegram_ai_assistant.security import BotAccessController


class BotAccessTests(unittest.TestCase):
    def test_allows_configured_owner(self):
        controller = BotAccessController(allowed_user_id=123)

        self.assertTrue(controller.is_allowed(123))

    def test_rejects_other_users(self):
        controller = BotAccessController(allowed_user_id=123)

        self.assertFalse(controller.is_allowed(456))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the access control tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_security -v
```

Expected: FAIL because `telegram_ai_assistant.security` does not exist.

- [ ] **Step 3: Write the minimal access control implementation**

Create `src/telegram_ai_assistant/security.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class BotAccessController:
    allowed_user_id: int

    def is_allowed(self, telegram_user_id: int) -> bool:
        return telegram_user_id == self.allowed_user_id
```

- [ ] **Step 4: Run the access control tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_security -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add src/telegram_ai_assistant/security.py tests/test_security.py
git commit -m "feat: add owner-only bot access control"
```

## Task 6: Read-Only Telegram Adapter Guard

**Files:**
- Create: `src/telegram_ai_assistant/telegram_readonly.py`
- Test: `tests/test_telegram_readonly.py`

- [ ] **Step 1: Write the failing read-only guard tests**

Create `tests/test_telegram_readonly.py`:

```python
import unittest

from telegram_ai_assistant.telegram_readonly import MutatingTelegramMethodError, ReadOnlyTelegramGuard


class ReadOnlyTelegramGuardTests(unittest.TestCase):
    def test_allows_non_mutating_methods(self):
        guard = ReadOnlyTelegramGuard()

        guard.assert_allowed("iter_messages")
        guard.assert_allowed("get_dialogs")

    def test_rejects_mark_read_and_send_methods(self):
        guard = ReadOnlyTelegramGuard()

        with self.assertRaises(MutatingTelegramMethodError):
            guard.assert_allowed("send_message")

        with self.assertRaises(MutatingTelegramMethodError):
            guard.assert_allowed("send_read_acknowledge")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the read-only guard tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_telegram_readonly -v
```

Expected: FAIL because `telegram_ai_assistant.telegram_readonly` does not exist.

- [ ] **Step 3: Write the minimal read-only guard implementation**

Create `src/telegram_ai_assistant/telegram_readonly.py`:

```python
class MutatingTelegramMethodError(RuntimeError):
    pass


class ReadOnlyTelegramGuard:
    MUTATING_METHODS = frozenset(
        {
            "send_message",
            "send_file",
            "edit_message",
            "delete_messages",
            "send_read_acknowledge",
            "mark_read",
            "pin_message",
            "unpin_message",
            "forward_messages",
        }
    )

    def assert_allowed(self, method_name: str) -> None:
        if method_name in self.MUTATING_METHODS:
            raise MutatingTelegramMethodError(f"Telegram method is not allowed in read-only mode: {method_name}")
```

- [ ] **Step 4: Run the read-only guard tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_telegram_readonly -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add src/telegram_ai_assistant/telegram_readonly.py tests/test_telegram_readonly.py
git commit -m "feat: add read-only Telegram guard"
```

## Final Verification

- [ ] **Step 1: Run the full test suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests PASS.

- [ ] **Step 2: Check git status**

Run:

```bash
git status --short
```

Expected: only intentional untracked local tooling directories may remain, such as `.codegraph/` and `.cursor/`.

- [ ] **Step 3: Commit any missed implementation files**

If any intended source or test files are uncommitted, add and commit them with a focused message before finishing.
