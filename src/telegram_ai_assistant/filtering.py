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
