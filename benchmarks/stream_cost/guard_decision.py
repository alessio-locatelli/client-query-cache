from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import StrEnum

MATERIAL_SLOWDOWN = 1.30
BLOCK_PAIRS = 15
MINIMUM_BLOCK_SECONDS = 0.005


class Decision(StrEnum):
    WITHIN_BOUNDARY = "within_boundary"
    REGRESSION = "regression"
    INCONCLUSIVE = "inconclusive"
    MEASUREMENT_ERROR = "measurement_error"


@dataclass(frozen=True, slots=True)
class CaseDecision:
    decision: Decision
    base_median_seconds: float
    head_median_seconds: float
    median_ratio: float
    lower_ratio: float
    upper_ratio: float
    reason: str


def evaluate_case(base: tuple[float, ...], head: tuple[float, ...]) -> CaseDecision:
    if len(base) != BLOCK_PAIRS or len(head) != BLOCK_PAIRS:
        message = f"expected {BLOCK_PAIRS} paired blocks"
        raise ValueError(message)
    if any(
        not math.isfinite(value) or value < MINIMUM_BLOCK_SECONDS
        for value in (*base, *head)
    ):
        raise ValueError("missing, invalid, or too-short paired block")
    ratios = tuple(
        proposed / baseline for baseline, proposed in zip(base, head, strict=True)
    )
    median_ratio = statistics.median(ratios)
    deviation = statistics.median(abs(value - median_ratio) for value in ratios)
    standard_error = 1.4826 * deviation / math.sqrt(len(ratios))
    allowance = 3 * standard_error
    lower = max(0.0, median_ratio - allowance)
    upper = median_ratio + allowance
    if lower > MATERIAL_SLOWDOWN:
        decision = Decision.REGRESSION
        reason = "stable slowdown exceeds the 30% boundary"
    elif upper <= MATERIAL_SLOWDOWN:
        decision = Decision.WITHIN_BOUNDARY
        reason = "upper stability bound stays within the 30% boundary"
    else:
        decision = Decision.INCONCLUSIVE
        reason = "variation overlaps the 30% boundary"
    return CaseDecision(
        decision=decision,
        base_median_seconds=statistics.median(base),
        head_median_seconds=statistics.median(head),
        median_ratio=median_ratio,
        lower_ratio=lower,
        upper_ratio=upper,
        reason=reason,
    )
