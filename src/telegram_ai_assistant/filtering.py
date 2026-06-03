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
    TASK_INTENT = "task_intent"
    ERRAND_ACTION = "errand_action"
    LOGISTICS_CONTEXT = "logistics_context"
    PRIVATE_CHAT_PRIORITY = "private_chat_priority"


@dataclass(frozen=True)
class CandidateScoringContext:
    chat_type: str = ""


@dataclass(frozen=True)
class CandidateScore:
    score: float
    reasons: tuple[CandidateReason, ...]


TIME_RE = re.compile(
    r"\b(через|завтра|сегодня|потом|на неделе|следующей неделе|утром|вечером|после работы|"
    r"на выходных|до завтра|минут|час|дней|дня|пятниц[уы]|понедельник[ау]?|вторник[ау]?|"
    r"сред[уы]|четверг[ау]?|суббот[уы]|воскресень[ея])\b",
    re.IGNORECASE,
)
COMMITMENT_RE = re.compile(
    r"\b(перезвоню|посмотрю|отправлю|отправить|сделаю|разберу|проверю|напишу|подготовлю)\b",
    re.IGNORECASE,
)
IMPLIED_REQUEST_RE = re.compile(r"\b(скопируйте|скопировать|заберите|передайте|если там|важное)\b", re.IGNORECASE)
WAITING_RE = re.compile(r"\b(жду|ожидаю|дождаться|пока от них|когда пришлют)\b", re.IGNORECASE)
SELF_NOTE_RE = re.compile(r"\b(идея|мысль|заметка)\b", re.IGNORECASE)
TASK_INTENT_RE = re.compile(r"\b(нужно|надо|не забыть|стоит|нужно бы|надо бы|нужно будет)\b", re.IGNORECASE)
ERRAND_ACTION_RE = re.compile(
    r"\b(заехать|забрать|купить|оплатить|позвонить|написать|проверить|проверь|"
    r"отправить|записаться|заказать|подготовить|подготовлю)\b",
    re.IGNORECASE,
)
LOGISTICS_CONTEXT_RE = re.compile(
    r"\b(озон|ozon|пвз|доставка|аптека|магазин|документы|посылка|ирригатор|счет|договор)\b",
    re.IGNORECASE,
)

TIME_EXPRESSION_WEIGHT = 0.25
OWNER_COMMITMENT_WEIGHT = 0.45
IMPLIED_REQUEST_WEIGHT = 0.6
WAITING_STATE_WEIGHT = 0.4
SELF_NOTE_WEIGHT = 0.35
TASK_INTENT_WEIGHT = 0.25
ERRAND_ACTION_WEIGHT = 0.25
LOGISTICS_CONTEXT_WEIGHT = 0.1
PRIVATE_CHAT_PRIORITY_WEIGHT = 0.15


def score_message(message: Message, context: CandidateScoringContext | None = None) -> CandidateScore:
    text = message.content_text
    if not text:
        return CandidateScore(score=0.0, reasons=())

    context = context or CandidateScoringContext()
    reasons: list[CandidateReason] = []
    score = 0.0
    has_content_reason = False

    if TIME_RE.search(text):
        reasons.append(CandidateReason.TIME_EXPRESSION)
        score += TIME_EXPRESSION_WEIGHT
    if message.direction == MessageDirection.OUTGOING and COMMITMENT_RE.search(text):
        reasons.append(CandidateReason.OWNER_COMMITMENT)
        score += OWNER_COMMITMENT_WEIGHT
        has_content_reason = True
    if IMPLIED_REQUEST_RE.search(text):
        reasons.append(CandidateReason.IMPLIED_REQUEST)
        score += IMPLIED_REQUEST_WEIGHT
        has_content_reason = True
    if WAITING_RE.search(text):
        reasons.append(CandidateReason.WAITING_STATE)
        score += WAITING_STATE_WEIGHT
        has_content_reason = True
    if SELF_NOTE_RE.search(text):
        reasons.append(CandidateReason.SELF_NOTE)
        score += SELF_NOTE_WEIGHT
        has_content_reason = True
    if TASK_INTENT_RE.search(text):
        reasons.append(CandidateReason.TASK_INTENT)
        score += TASK_INTENT_WEIGHT
        has_content_reason = True
    if ERRAND_ACTION_RE.search(text):
        reasons.append(CandidateReason.ERRAND_ACTION)
        score += ERRAND_ACTION_WEIGHT
        has_content_reason = True
    if LOGISTICS_CONTEXT_RE.search(text):
        reasons.append(CandidateReason.LOGISTICS_CONTEXT)
        score += LOGISTICS_CONTEXT_WEIGHT
        has_content_reason = True
    if not has_content_reason:
        return CandidateScore(score=0.0, reasons=())
    if context.chat_type == "private":
        reasons.append(CandidateReason.PRIVATE_CHAT_PRIORITY)
        score += PRIVATE_CHAT_PRIORITY_WEIGHT

    return CandidateScore(score=min(score, 1.0), reasons=tuple(dict.fromkeys(reasons)))
