from fastapi import APIRouter

from .endpoints import consensus, miner_comms, observability

api_router = APIRouter(prefix="/v1")
api_router.include_router(observability.router)
api_router.include_router(consensus.router)
api_router.include_router(miner_comms.router)
