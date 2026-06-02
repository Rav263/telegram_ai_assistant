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
