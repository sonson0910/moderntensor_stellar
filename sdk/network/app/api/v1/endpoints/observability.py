"""Health, readiness, and lightweight validator metrics endpoints."""

from __future__ import annotations

import time
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from sdk.core.datatypes import STATUS_ACTIVE
from sdk.network.app.dependencies import get_optional_validator_node


router = APIRouter(tags=["Observability"])


def _active_count(items) -> int:
    return sum(
        1
        for item in items
        if getattr(item, "status", STATUS_ACTIVE) == STATUS_ACTIVE
    )


def _validator_snapshot(node: Any) -> Dict[str, Any]:
    if hasattr(node, "metrics_snapshot"):
        return node.metrics_snapshot()

    tasks_sent = getattr(node, "tasks_sent", {})
    results_buffer = getattr(node, "results_buffer", {})
    received_scores = getattr(node, "received_validator_scores", {})
    validators_info = getattr(node, "validators_info", {})
    miners_info = getattr(node, "miners_info", {})
    queue_capacity = max(
        1,
        int(getattr(getattr(node, "settings", None), "API_TASK_QUEUE_SIZE", 64)),
    )
    queue_depth = max(len(tasks_sent), len(results_buffer))
    votes_buffered = sum(
        len(validators)
        for tasks in received_scores.values()
        for validators in tasks.values()
    )
    counters = dict(getattr(node, "metrics", {}))
    counters.setdefault("commit_failures", 0)
    counters.setdefault("cycle_commits", 0)
    counters.setdefault("tasks_sent_total", 0)
    counters.setdefault("miner_results_accepted_total", 0)
    counters.setdefault("miner_results_rejected_total", 0)
    counters.setdefault("validator_score_votes_accepted_total", 0)
    counters.setdefault("validator_score_votes_rejected_total", 0)
    return {
        "cycle": getattr(node, "current_cycle", 0),
        "validator_uid": getattr(getattr(node, "info", None), "uid", None),
        "peers": {
            "miners_total": len(miners_info),
            "miners_active": _active_count(miners_info.values()),
            "validators_total": len(validators_info),
            "validators_active": _active_count(validators_info.values()),
        },
        "queues": {
            "capacity": queue_capacity,
            "task_depth": len(tasks_sent),
            "result_depth": len(results_buffer),
            "saturation": round(queue_depth / queue_capacity, 6),
            "saturated": queue_depth >= queue_capacity,
        },
        "buffers": {
            "votes_buffered": votes_buffered,
        },
        "counters": counters,
    }


def _metric_name(name: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in name.lower()).strip("_")


def _prometheus_text(snapshot: Dict[str, Any]) -> str:
    counters = snapshot["counters"]
    peers = snapshot["peers"]
    queues = snapshot["queues"]
    buffers = snapshot["buffers"]
    lines = [
        "# TYPE moderntensor_validator_cycle gauge",
        f"moderntensor_validator_cycle {int(snapshot['cycle'])}",
        "# TYPE moderntensor_validator_peers gauge",
        "moderntensor_validator_peers"
        f"{{role=\"miner\",state=\"total\"}} {peers['miners_total']}",
        "moderntensor_validator_peers"
        f"{{role=\"miner\",state=\"active\"}} {peers['miners_active']}",
        "moderntensor_validator_peers"
        f"{{role=\"validator\",state=\"total\"}} {peers['validators_total']}",
        "moderntensor_validator_peers"
        f"{{role=\"validator\",state=\"active\"}} {peers['validators_active']}",
        "# TYPE moderntensor_validator_queue_depth gauge",
        f"moderntensor_validator_queue_depth{{queue=\"task\"}} {queues['task_depth']}",
        f"moderntensor_validator_queue_depth{{queue=\"result\"}} {queues['result_depth']}",
        "# TYPE moderntensor_validator_queue_saturation gauge",
        f"moderntensor_validator_queue_saturation {queues['saturation']}",
        "# TYPE moderntensor_validator_votes_buffered gauge",
        f"moderntensor_validator_votes_buffered {buffers['votes_buffered']}",
    ]
    for name, value in sorted(counters.items()):
        metric_type = (
            "counter"
            if name.endswith("_total") or name in {"commit_failures", "cycle_commits"}
            else "gauge"
        )
        lines.append(f"# TYPE moderntensor_validator_{_metric_name(name)} {metric_type}")
        lines.append(f"moderntensor_validator_{_metric_name(name)} {value}")
    return "\n".join(lines) + "\n"


@router.get("/health", summary="Validator API health")
async def health(
    node: Annotated[Optional[Any], Depends(get_optional_validator_node)],
):
    return {
        "status": "ok" if node is not None else "degraded",
        "service": "validator-api",
        "node_initialized": node is not None,
        "timestamp": time.time(),
    }


@router.get("/readiness", summary="Validator API readiness")
async def readiness(
    node: Annotated[Optional[Any], Depends(get_optional_validator_node)],
):
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Validator node is not initialized.",
        )
    ready = bool(getattr(getattr(node, "info", None), "uid", None)) and (
        getattr(node, "current_cycle", None) is not None
    )
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Validator node is not ready.",
        )
    return {
        "ready": True,
        "cycle": getattr(node, "current_cycle", 0),
        "validator_uid": getattr(node.info, "uid", None),
    }


@router.get("/metrics", summary="Validator metrics")
async def metrics(
    node: Annotated[Optional[Any], Depends(get_optional_validator_node)],
    output_format: str = Query(
        default="prometheus",
        alias="format",
        pattern="^(prometheus|json)$",
    ),
):
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Validator node is not initialized.",
        )
    snapshot = _validator_snapshot(node)
    if output_format == "json":
        return snapshot
    return PlainTextResponse(
        _prometheus_text(snapshot),
        media_type="text/plain; version=0.0.4",
    )
