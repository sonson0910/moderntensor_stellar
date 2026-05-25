from fastapi import FastAPI
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
import uvicorn
import requests
import time
import asyncio
from datetime import datetime, timezone
import json
from typing import Optional
import logging
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict, deque

from sdk.chain.signing import (
    MINER_RESULT_DOMAIN,
    TASK_DOMAIN,
    miner_result_payload,
    payload_hash,
    sign_payload,
    validator_task_payload,
    verify_payload,
)
from sdk.config.settings import settings

# Get logger instance
logger = logging.getLogger(__name__)


# Define common data models
class TaskModel(BaseModel):
    """
    Pydantic model for task data sent from validator to miner.
    """

    task_id: str = Field(..., description="Unique ID of the task")
    description: str = Field(..., description="Detailed description of the task")
    deadline: Optional[str] = Field(
        None, description="Optional deadline for task completion"
    )
    priority: Optional[int] = Field(
        None, description="Optional priority of the task (1-5)"
    )
    validator_endpoint: Optional[str] = Field(
        None,
        description="API endpoint of the originating validator to send the result back to",
    )
    task_data: dict = Field(default_factory=dict, description="The actual task payload")
    validator_uid: Optional[str] = Field(None, description="UID of the validator")
    validator_public_key: Optional[str] = Field(None, description="Stellar public key")
    payload_hash: Optional[str] = Field(None, description="Canonical task payload hash")
    signature: Optional[str] = Field(None, description="Stellar task signature")
    cycle: Optional[int] = Field(None, description="Consensus cycle/ledger window")


class ResultModel(BaseModel):
    """
    Pydantic model for result data sent from miner to validator.
    """

    task_id: str = Field(..., description="Unique ID of the task this result is for")
    miner_uid: str = Field(..., description="UID of the miner who processed the task")
    result_data: dict = Field(
        default_factory=dict, description="The actual result payload"
    )
    miner_public_key: Optional[str] = Field(None, description="Stellar public key")
    payload_hash: Optional[str] = Field(None, description="Canonical result payload hash")
    signature: Optional[str] = Field(None, description="Stellar result signature")


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def sign_task_model(
    task: TaskModel,
    secret_seed: Optional[str] = None,
    validator_uid: Optional[str] = None,
    cycle: Optional[int] = None,
) -> TaskModel:
    """Attach a Stellar signature to a validator task when a secret is configured."""

    secret = secret_seed or settings.VALIDATOR_STELLAR_SECRET
    if validator_uid and not task.validator_uid:
        task.validator_uid = validator_uid
    if cycle is not None and task.cycle is None:
        task.cycle = cycle
    task_payload = {
        "description": task.description,
        "priority": task.priority,
        "task_data": task.task_data,
    }
    payload = validator_task_payload(
        task.task_id,
        task.cycle,
        task.deadline,
        task.task_data.get("miner_uid"),
        task_payload,
    )
    if not secret:
        if settings.REQUIRE_SIGNED_PAYLOADS:
            raise RuntimeError("VALIDATOR_STELLAR_SECRET is required to sign miner tasks.")
        return task
    signed = sign_payload(secret, payload, TASK_DOMAIN)
    task.validator_public_key = signed["public_key"]
    task.payload_hash = signed["payload_hash"]
    task.signature = signed["signature"]
    return task


def sign_result_model(
    result: ResultModel,
    secret_seed: Optional[str] = None,
) -> ResultModel:
    """Attach a Stellar signature to a miner result."""

    secret = secret_seed or settings.MINER_STELLAR_SECRET
    payload = miner_result_payload(result.task_id, result.miner_uid, result.result_data)
    result.payload_hash = payload_hash(payload, MINER_RESULT_DOMAIN)
    if not secret:
        if settings.REQUIRE_SIGNED_MINER_RESULTS:
            raise RuntimeError("MINER_STELLAR_SECRET is required to sign miner results.")
        return result
    signed = sign_payload(secret, payload, MINER_RESULT_DOMAIN)
    result.miner_public_key = signed["public_key"]
    result.payload_hash = signed["payload_hash"]
    result.signature = signed["signature"]
    return result


# Base class for Miner
class BaseMiner:
    def __init__(
        self, validator_url, host="0.0.0.0", port=8000, miner_uid="miner_default_001"
    ):
        """
        Initialize BaseMiner.

        Args:
            validator_url (str): Default URL of the validator to send results to.
            host (str): Host address for the miner server.
            port (int): Port for the miner server.
            miner_uid (str): Unique identifier for this miner.
        """
        self.app = FastAPI()
        self.validator_url = validator_url
        self.host = host
        self.port = port
        self.miner_uid = miner_uid
        self._task_executor = ThreadPoolExecutor(
            max_workers=max(1, min(settings.API_TASK_QUEUE_SIZE, 32))
        )
        self._task_semaphore = asyncio.Semaphore(settings.API_TASK_QUEUE_SIZE)
        self._rate_buckets = defaultdict(deque)
        self._seen_task_ids: set[str] = set()
        self._install_request_limits()
        self.setup_routes()
        logger.info(
            f":robot: [Miner:{self.miner_uid}] Initialized. Default Validator target: [link={self.validator_url}]{self.validator_url}[/link]"
        )

    def _install_request_limits(self):
        @self.app.middleware("http")
        async def limit_request_body(request: Request, call_next):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > settings.API_MAX_REQUEST_BYTES:
                raise HTTPException(status_code=413, detail="Request body too large.")
            peer = request.client.host if request.client else "unknown"
            now = time.time()
            bucket = self._rate_buckets[peer]
            while bucket and now - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= settings.API_RATE_LIMIT_PER_MINUTE:
                raise HTTPException(status_code=429, detail="Rate limit exceeded.")
            bucket.append(now)
            return await call_next(request)

    def setup_routes(self):
        """Set up routes for the miner server."""

        @self.app.post("/receive-task")
        async def receive_task(task: TaskModel):
            logger.info(
                f":inbox_tray: [Miner:{self.miner_uid}] Received task [yellow]{task.task_id}[/yellow] - Desc: '{task.description}' - Prio: {task.priority}"
            )
            if self._task_semaphore.locked():
                raise HTTPException(status_code=429, detail="Task queue is full.")
            self._verify_incoming_task(task)

            async def run_bounded():
                async with self._task_semaphore:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(self._task_executor, self.handle_task, task)

            asyncio.create_task(run_bounded())
            return {"message": f"Task {task.task_id} received and processing"}

    def process_task(self, task: TaskModel) -> dict:
        """
        Process the task data (can be overridden for customization).

        Args:
            task (TaskModel): Task containing task_id and task_data.

        Returns:
            dict: Result data dictionary.
        """
        logger.info(
            f":hourglass_flowing_sand: [Miner:{self.miner_uid}] Starting task [yellow]{task.task_id}[/yellow] (Priority: {task.priority}) - Data: {str(task.task_data)[:50]}..."
        )
        processing_time = 3 + (task.priority % 3) if task.priority else 4
        time.sleep(processing_time)
        result_payload = {
            "output": f"processed_output_for_{task.task_id}",
            "loss": round(1.0 / (processing_time + 1), 4),
            "processing_time_ms": int(processing_time * 1000),
        }
        logger.info(
            f":white_check_mark: [Miner:{self.miner_uid}] Completed task [yellow]{task.task_id}[/yellow] - Processing time: {processing_time:.2f}s"
        )
        return result_payload

    def _verify_incoming_task(self, task: TaskModel) -> None:
        if task.task_id in self._seen_task_ids:
            raise HTTPException(status_code=409, detail="Duplicate task.")
        if task.task_data.get("miner_uid") not in (None, self.miner_uid):
            raise HTTPException(status_code=400, detail="Task miner UID mismatch.")
        if task.deadline:
            try:
                deadline = datetime.fromisoformat(task.deadline.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid task deadline.") from exc
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if deadline < datetime.now(timezone.utc):
                raise HTTPException(status_code=400, detail="Task deadline has expired.")
        if settings.REQUIRE_SIGNED_PAYLOADS:
            if not task.validator_public_key or not task.signature:
                raise HTTPException(status_code=401, detail="Missing validator task signature.")
            expected_public_key = settings.VALIDATOR_STELLAR_PUBLIC_KEY or settings.VALIDATOR_ADDRESS
            if expected_public_key and task.validator_public_key != expected_public_key:
                raise HTTPException(status_code=401, detail="Validator public key mismatch.")
            task_body = {
                "description": task.description,
                "priority": task.priority,
                "task_data": task.task_data,
            }
            signed_payload = validator_task_payload(
                task.task_id,
                task.cycle,
                task.deadline,
                task.task_data.get("miner_uid"),
                task_body,
            )
            if not verify_payload(task.validator_public_key, signed_payload, task.signature, TASK_DOMAIN):
                raise HTTPException(status_code=401, detail="Invalid validator task signature.")
        self._seen_task_ids.add(task.task_id)

    def handle_task(self, task: TaskModel):
        """Processes the task and sends the ResultModel back to the validator."""
        result_data_payload = self.process_task(task)

        result_to_send = ResultModel(
            task_id=task.task_id,
            miner_uid=self.miner_uid,
            result_data=result_data_payload,
        )
        self._sign_result_model(result_to_send)

        target_validator_url = task.validator_endpoint or self.validator_url
        if not target_validator_url:
            logger.error(
                f":x: [Miner:{self.miner_uid}] No validator URL found for task [yellow]{task.task_id}[/yellow]. Cannot send result."
            )
            return

        result_submit_url = f"{target_validator_url.rstrip('/')}/v1/miner/submit_result"

        try:
            logger.debug(
                f":outbox_tray: [Miner:{self.miner_uid}] Sending result for task [yellow]{task.task_id}[/yellow] to [link={result_submit_url}]{result_submit_url}[/link]"
                + f" Payload: {str(_model_to_dict(result_to_send))[:100]}..."
            )
            response = requests.post(
                result_submit_url, json=_model_to_dict(result_to_send), timeout=10
            )
            response.raise_for_status()
            try:
                response_data = response.json()
                logger.info(
                    f":mailbox_with_mail: [Miner:{self.miner_uid}] Result sent. Validator response for task [yellow]{task.task_id}[/yellow]: {response_data}"
                )
            except json.JSONDecodeError:
                logger.info(
                    f":mailbox_with_mail: [Miner:{self.miner_uid}] Result sent. Validator response for task [yellow]{task.task_id}[/yellow]: Status {response.status_code} (Non-JSON)"
                )

        except requests.exceptions.RequestException as e:
            logger.error(
                f":x: [Miner:{self.miner_uid}] Error sending result for task [yellow]{task.task_id}[/yellow] to {result_submit_url}: {e}"
            )
        except Exception as e:
            logger.exception(
                f":rotating_light: [Miner:{self.miner_uid}] Unexpected error handling task [yellow]{task.task_id}[/yellow]: {e}"
            )

    def _sign_result_model(self, result: ResultModel) -> ResultModel:
        return sign_result_model(result)

    def run(self):
        """Start the miner server."""
        logger.info(
            f":rocket: [Miner:{self.miner_uid}] Starting server at [link=http://{self.host}:{self.port}]http://{self.host}:{self.port}[/link]"
        )
        uvicorn.run(self.app, host=self.host, port=self.port, log_config=None)


# Base class for Validator
class BaseValidator:
    def __init__(
        self, host="0.0.0.0", port=8001, validator_uid="validator_default_001"
    ):
        """
        Initialize BaseValidator.

        Args:
            host (str): Host address for the validator server.
            port (int): Port for the validator server.
            validator_uid (str): Unique identifier for this validator.
        """
        self.app = FastAPI()
        self.host = host
        self.port = port
        self.validator_uid = validator_uid
        self.miner_clients = {}
        self.setup_routes()
        logger.info(f":shield: [Validator:{self.validator_uid}] Initialized.")

    def setup_routes(self):
        """Set up routes for the validator server."""

        @self.app.post("/v1/miner/submit_result")
        async def submit_result(result: ResultModel):
            logger.info(
                f":inbox_tray: [Validator:{self.validator_uid}] Received result for task [yellow]{result.task_id}[/yellow] from Miner [cyan]{result.miner_uid}[/cyan] - Data: {str(result.result_data)[:50]}..."
            )
            return {"message": f"Result for task {result.task_id} received"}

    def send_task_to_miner(self, miner_endpoint: str, task_model: TaskModel):
        """
        Example function to send a single task to a miner.
        Note: Uses blocking requests, should be async or run in thread in real usage.
        """
        target_url = f"{miner_endpoint.rstrip('/')}/receive-task"
        try:
            logger.info(
                f":outbox_tray: [Validator:{self.validator_uid}] Sending task [yellow]{task_model.task_id}[/yellow] to Miner at [link={target_url}]{target_url}[/link]"
            )
            sign_task_model(task_model, validator_uid=self.validator_uid)
            response = requests.post(target_url, json=_model_to_dict(task_model), timeout=5)
            response.raise_for_status()
            logger.info(
                f":mailbox_with_mail: [Validator:{self.validator_uid}] Miner response for task [yellow]{task_model.task_id}[/yellow]: {response.json()}"
            )
            return True
        except requests.exceptions.RequestException as e:
            logger.error(
                f":x: [Validator:{self.validator_uid}] Error sending task [yellow]{task_model.task_id}[/yellow] to {target_url}: {e}"
            )
            return False
        except Exception as e:
            logger.exception(
                f":rotating_light: [Validator:{self.validator_uid}] Unexpected error sending task [yellow]{task_model.task_id}[/yellow]: {e}"
            )
            return False

    def run_server_only(self):
        """Starts only the validator FastAPI server."""
        logger.info(
            f":rocket: [Validator:{self.validator_uid}] Starting server at [link=http://{self.host}:{self.port}]http://{self.host}:{self.port}[/link]"
        )
        uvicorn.run(self.app, host=self.host, port=self.port, log_config=None)
