"""Scoring and signed score broadcast helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List

import httpx

from sdk.chain.signing import VALIDATOR_SCORE_DOMAIN, canonical_json_serialize, sign_payload, validator_scores_payload
from sdk.core.datatypes import MinerResult, ScoreSubmissionPayload, TaskAssignment, ValidatorScore


logger = logging.getLogger(__name__)


def _calculate_score_from_result(task_data, result_data) -> float:
    if isinstance(result_data, dict) and not result_data.get("error_details"):
        return 1.0
    return 0.0


def score_results_logic(
    results_received: Dict[str, List[MinerResult]],
    tasks_sent: Dict[str, TaskAssignment],
    validator_uid: str,
) -> Dict[str, List[ValidatorScore]]:
    scores: Dict[str, List[ValidatorScore]] = {}
    for task_id, results in results_received.items():
        assignment = tasks_sent.get(task_id)
        if not assignment:
            continue
        for result in results:
            if result.miner_uid != assignment.miner_uid:
                continue
            value = max(0.0, min(1.0, _calculate_score_from_result(assignment.task_data, result.result_data)))
            scores.setdefault(task_id, []).append(
                ValidatorScore(
                    task_id=task_id,
                    miner_uid=result.miner_uid,
                    validator_uid=validator_uid,
                    score=value,
                )
            )
            break
    return scores


async def broadcast_scores_logic(validator_node, cycle_scores_dict: Dict[str, List[ValidatorScore]]) -> None:
    self_uid = validator_node.info.uid
    local_scores = [
        score
        for scores in cycle_scores_dict.values()
        for score in scores
        if score.validator_uid == self_uid
    ]
    if not local_scores:
        return
    payload_to_sign = validator_scores_payload(local_scores, self_uid, validator_node.current_cycle)
    signed = sign_payload(validator_node.stellar_secret, payload_to_sign, VALIDATOR_SCORE_DOMAIN)
    payload = ScoreSubmissionPayload(
        scores=local_scores,
        submitter_validator_uid=self_uid,
        cycle=validator_node.current_cycle,
        submitter_public_key=signed["public_key"],
        payload_hash=signed["payload_hash"],
        signature=signed["signature"],
    )
    payload_dict = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload.dict()
    tasks = []
    for peer in await validator_node._get_active_validators():
        if peer.uid == self_uid or not peer.api_endpoint:
            continue
        endpoint = f"{peer.api_endpoint.rstrip('/')}/v1/consensus/receive_scores"
        tasks.append(_send_score(validator_node.http_client, endpoint, payload_dict))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _send_score(client: httpx.AsyncClient, endpoint: str, payload: dict) -> None:
    response = await client.post(endpoint, json=payload, headers={"Content-Type": "application/json"})
    if response.status_code >= 300:
        logger.warning("Score broadcast failed at %s: %s", endpoint, response.status_code)
