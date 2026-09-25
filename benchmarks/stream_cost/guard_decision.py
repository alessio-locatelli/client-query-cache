"""Fixed, conservative decision policy for paired PR measurements."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import StrEnum

MATERIAL_SLOWDOWN = 1.30
BLOCK_PAIRS = 7
MINIMUM_BLOCK_SECONDS = 0.02


class Decision(StrEnum):
    WITHIN_BOUNDARY = "within_boundary"
    REGRESSION = "regression"
    INCONCLUSIVE = "inconclusive"


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
    """Use paired ratios and their median absolute deviation as a stability bound.

    Returns:
        The conservative decision and bounded timing summary.

    Raises:
        ValueError: The fixed paired sample budget or duration is invalid.
    """
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
    # A generous, fixed dispersion allowance makes a red status require a stable effect.
    deviation = statistics.median(abs(value - median_ratio) for value in ratios)
    allowance = 3 * 1.4826 * deviation
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
