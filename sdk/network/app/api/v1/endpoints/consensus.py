import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from sdk.chain.signing import (
    VALIDATOR_SCORE_DOMAIN,
    validator_scores_payload,
    verify_payload,
)
from sdk.consensus.node import ValidatorNode
from sdk.core.datatypes import ScoreSubmissionPayload
from sdk.network.app.dependencies import get_validator_node

router = APIRouter(prefix="/consensus", tags=["Consensus P2P"])
logger = logging.getLogger(__name__)


async def verify_payload_signature(
    receiver_node: "ValidatorNode",
    payload: ScoreSubmissionPayload,
) -> bool:
    """Verify a signed validator score payload."""
    signature = payload.signature
    submitter_public_key = payload.submitter_public_key
    submitter_uid = payload.submitter_validator_uid

    if not signature or not submitter_public_key:
        logger.warning(
            f"SigVerifyFail (Receiver: {receiver_node.info.uid}, Sender: {submitter_uid}): Missing signature or Stellar public key."
        )
        return False

    logger.debug(f"Verifying signature for payload from validator {submitter_uid}...")

    submitter_info = receiver_node.validators_info.get(submitter_uid)
    if not submitter_info:
        logger.warning(
            f"SigVerifyFail (Receiver: {receiver_node.info.uid}): Submitter validator {submitter_uid} not found in local state."
        )
        return False

    expected_public_key = submitter_info.public_key
    if not expected_public_key:
        logger.warning(
            f"SigVerifyFail (Sender: {submitter_uid}): no Stellar public key in registry state."
        )
        return False
    if submitter_public_key != expected_public_key:
        logger.warning(
            f"SigVerifyFail (Sender: {submitter_uid}): Stellar public key mismatch."
        )
        return False

    signed_payload = validator_scores_payload(
        payload.scores,
        submitter_uid,
        payload.cycle,
    )
    if verify_payload(expected_public_key, signed_payload, signature, VALIDATOR_SCORE_DOMAIN):
        logger.info(f"Signature verification SUCCESSFUL for payload from {submitter_uid}")
        return True
    logger.warning(f"SigVerifyFail (Sender: {submitter_uid}): invalid Stellar signature.")
    return False


def _reject_duplicate_scores(node: ValidatorNode, payload: ScoreSubmissionPayload) -> None:
    cycle_scores = node.received_validator_scores.get(payload.cycle, {})
    for score in payload.scores:
        task_scores = cycle_scores.get(score.task_id, {})
        if score.validator_uid in task_scores:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Duplicate score for task {score.task_id} from validator "
                    f"{score.validator_uid}."
                ),
            )


@router.post(
    "/receive_scores",
    summary="Receive signed scores from a validator peer",
    description="Accepts validator score payloads after signature and cycle validation.",
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_scores(
    payload: ScoreSubmissionPayload,
    node: Annotated[ValidatorNode, Depends(get_validator_node)],
):
    submitter_uid = payload.submitter_validator_uid
    current_cycle = node.current_cycle
    payload_cycle = payload.cycle

    logger.info(
        f"API: Received scores submission from V:{submitter_uid} for cycle {payload_cycle} (Node cycle: {current_cycle})"
    )

    if submitter_uid == node.info.uid:
        logger.debug(f"API: Received scores from self ({submitter_uid}). Ignoring.")
        return {"message": "Accepted scores from self (ignored)."}

    if not (current_cycle - 1 <= payload_cycle <= current_cycle):
        logger.warning(
            f"API: Received scores for invalid cycle {payload_cycle} from {submitter_uid}. Current: {current_cycle}. Rejecting."
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cycle: {payload_cycle}. Current: {current_cycle}.",
        )

    if not await verify_payload_signature(node, payload):
        logger.warning(
            f"API: Rejected scores from {submitter_uid} for cycle {payload_cycle} due to invalid signature/VKey."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature or verification key.",
        )
    logger.debug(
        f"API: Signature verified for scores from {submitter_uid} for cycle {payload_cycle}"
    )
    _reject_duplicate_scores(node, payload)

    try:
        scores_objects = payload.scores

        if not scores_objects:
            logger.info(
                f"API: No valid score entries parsed from payload from {submitter_uid} to add."
            )
            return {
                "message": f"Accepted payload from {submitter_uid} (no scores found/parsed)."
            }

        await node.add_received_score(submitter_uid, payload_cycle, scores_objects)
        logger.info(
            f"API: Successfully processed and stored {len(scores_objects)} scores from {submitter_uid} for cycle {payload_cycle}"
        )
        return {
            "message": f"Accepted {len(scores_objects)} scores from {submitter_uid} for cycle {payload_cycle}."
        }
    except Exception as e:
        logger.exception(
            f"API Error processing scores from {submitter_uid} after verification: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error processing scores: {e}",
        )
