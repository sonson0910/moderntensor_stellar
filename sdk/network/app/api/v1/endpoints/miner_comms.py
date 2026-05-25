import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from sdk.chain.signing import MINER_RESULT_DOMAIN, miner_result_payload, verify_payload
from sdk.consensus.node import ValidatorNode
from sdk.core.datatypes import MinerResult
from sdk.network.app.dependencies import get_validator_node
from sdk.network.server import ResultModel
from sdk.config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _expected_miner_public_key(node: ValidatorNode, miner_uid: str) -> str | None:
    miner_info = node.miners_info.get(miner_uid)
    if not miner_info:
        return None
    return miner_info.public_key


async def _verify_result_signature(
    result_payload: ResultModel,
    node: ValidatorNode,
) -> None:
    if not settings.REQUIRE_SIGNED_MINER_RESULTS:
        return

    assignment = node.tasks_sent.get(result_payload.task_id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown or expired task_id.",
        )
    if assignment.miner_uid != result_payload.miner_uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Miner UID does not match the task assignment.",
        )

    expected_public_key = _expected_miner_public_key(node, result_payload.miner_uid)
    if not expected_public_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Miner public key is not registered in the local metagraph state.",
        )
    if result_payload.miner_public_key != expected_public_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Miner public key does not match registry.",
        )
    if not result_payload.signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing miner result signature.",
        )

    payload = miner_result_payload(
        result_payload.task_id,
        result_payload.miner_uid,
        result_payload.result_data,
    )
    if not verify_payload(
        expected_public_key,
        payload,
        result_payload.signature,
        MINER_RESULT_DOMAIN,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid miner result signature.",
        )


@router.post(
    "/miner/submit_result",
    summary="Miner submits a signed task result",
    description="Endpoint for miners to submit signed task results.",
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_miner_result(
    result_payload: ResultModel,
    node: Annotated[ValidatorNode, Depends(get_validator_node)],
):
    log_task_id = result_payload.task_id
    log_miner_uid = result_payload.miner_uid
    log_result_data_summary = str(result_payload.result_data)[:100]

    logger.info(
        f"API: Received result submission for task [yellow]{log_task_id}[/yellow] from miner [cyan]{log_miner_uid}[/cyan]"
    )
    logger.debug(f"   Result Data Received: {log_result_data_summary}...")
    await _verify_result_signature(result_payload, node)

    try:
        assignment = node.tasks_sent.get(log_task_id)
        internal_result = MinerResult(
            task_id=log_task_id,
            miner_uid=log_miner_uid,
            result_data=result_payload.result_data,
            timestamp_received=time.time(),
            cycle=assignment.cycle if assignment else None,
            payload_hash=result_payload.payload_hash,
            signature=result_payload.signature,
            miner_public_key=result_payload.miner_public_key,
        )
        logger.debug(f"Converted to internal MinerResult: {internal_result}")

        success = await node.add_miner_result(internal_result)

        if success:
            logger.info(
                f"✅ Result for task [yellow]{internal_result.task_id}[/yellow] successfully added by node."
            )
            return {"message": f"Result for task {internal_result.task_id} accepted."}
        else:
            logger.warning(
                f"⚠️ Result for task [yellow]{internal_result.task_id}[/yellow] rejected by node."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Result rejected by validator node (e.g., duplicate, wrong cycle, invalid data).",
            )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.exception(
            f"💥 API: Internal error processing result submission for task [yellow]{log_task_id}[/yellow]: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error processing result.",
        )
