"""FastAPI app for ModernTensor P2P traffic."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI, HTTPException, Request

from .api.v1.routes import api_router
from .dependencies import set_validator_node_instance
from sdk.chain.stellar import StellarChainClient, build_stellar_testnet_config
from sdk.config.settings import settings
from sdk.consensus.node import ValidatorNode
from sdk.core.datatypes import ValidatorInfo


logger = logging.getLogger(__name__)

app = FastAPI(
    title="ModernTensor Network API",
    description="Signed P2P endpoints for ModernTensor Stellar Testnet nodes.",
    version="1.0.0",
)

main_validator_node_instance: Optional[ValidatorNode] = None
main_loop_task: Optional[asyncio.Task] = None
_rate_buckets = defaultdict(deque)


@app.middleware("http")
async def request_limits(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.API_MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large.")
    peer = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _rate_buckets[peer]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= settings.API_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")
    bucket.append(now)
    return await call_next(request)


@app.on_event("startup")
async def startup_event():
    global main_validator_node_instance
    secret = settings.VALIDATOR_STELLAR_SECRET
    if not secret:
        logger.warning("Validator secret not set; API starts without a node instance.")
        return
    public_key = StellarChainClient.public_key_from_secret(secret)
    host = os.getenv("HOST", "127.0.0.1")
    endpoint = settings.VALIDATOR_API_ENDPOINT or f"http://{host}:{settings.API_PORT}"
    uid = settings.VALIDATOR_UID or public_key[-12:]
    node = ValidatorNode(
        validator_info=ValidatorInfo(uid=uid, public_key=public_key, api_endpoint=endpoint),
        chain_client=StellarChainClient(build_stellar_testnet_config(settings)),
        stellar_secret=secret,
    )
    main_validator_node_instance = node
    set_validator_node_instance(node)
    logger.info("Validator node initialized for API: %s", uid)


@app.on_event("shutdown")
async def shutdown_event():
    if main_loop_task and not main_loop_task.done():
        main_loop_task.cancel()
    if main_validator_node_instance:
        await main_validator_node_instance.http_client.aclose()


app.include_router(api_router)
