"""Miner selection for a consensus cycle."""

from __future__ import annotations

import random
from typing import Dict, List

from sdk.core.datatypes import MinerInfo, STATUS_ACTIVE
from sdk.formulas.trust_score import calculate_selection_probability


def select_miners_logic(
    miners_info: Dict[str, MinerInfo],
    current_cycle: int,
    num_to_select: int,
    beta: float,
    max_time_bonus: int,
) -> List[MinerInfo]:
    active_miners = [m for m in miners_info.values() if m.status == STATUS_ACTIVE and m.api_endpoint]
    if not active_miners:
        return []
    weights = []
    total = 0.0
    for miner in active_miners:
        time_since = max(0, current_cycle - miner.last_selected_time)
        weight = max(
            0.0,
            calculate_selection_probability(
                trust_score=miner.trust_score,
                time_since_last_selection=time_since,
                beta=beta,
                max_time_bonus_effect=max_time_bonus,
            ),
        )
        weights.append((miner, weight))
        total += weight
    if total <= 0:
        return random.sample(active_miners, min(num_to_select, len(active_miners)))
    selected: List[MinerInfo] = []
    attempts = 0
    while len(selected) < min(num_to_select, len(active_miners)) and attempts < len(active_miners) * 10:
        attempts += 1
        pick = random.choices([m for m, _ in weights], weights=[w for _, w in weights], k=1)[0]
        if pick not in selected:
            selected.append(pick)
    return selected
