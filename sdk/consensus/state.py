"""Pure in-memory consensus state helpers."""

from __future__ import annotations

from typing import Dict, List

from sdk.core.datatypes import ValidatorScore


def average_scores(scores: Dict[str, List[ValidatorScore]]) -> Dict[str, float]:
    totals: Dict[str, List[float]] = {}
    for entries in scores.values():
        for score in entries:
            totals.setdefault(score.miner_uid, []).append(score.score)
    return {uid: sum(values) / len(values) for uid, values in totals.items() if values}


def weighted_median(values: List[tuple[float, float]]) -> float:
    """Return the weighted median for `(value, weight)` entries."""

    filtered = [(max(0.0, min(1.0, value)), max(0.0, weight)) for value, weight in values if weight > 0]
    if not filtered:
        return 0.0
    ordered = sorted(filtered, key=lambda item: item[0])
    total_weight = sum(weight for _, weight in ordered)
    midpoint = total_weight / 2.0
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= midpoint:
            return value
    return ordered[-1][0]


def validator_weight(stake: float, trust_score: float) -> float:
    """Compute validator vote weight from stake and trust with a bootstrap floor."""

    trust_floor = 0.1
    return max(0.0, stake) * max(trust_floor, max(0.0, min(1.0, trust_score)))
