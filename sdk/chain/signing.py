"""Canonical payload signing for Stellar-backed ModernTensor nodes."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
from typing import Any, Dict, Optional


TASK_DOMAIN = "moderntensor.validator_task.v1"
MINER_RESULT_DOMAIN = "moderntensor.miner_result.v1"
VALIDATOR_SCORE_DOMAIN = "moderntensor.validator_scores.v1"
CYCLE_COMMIT_DOMAIN = "moderntensor.cycle_commit.v1"


def _stellar_keypair_class():
    try:
        from stellar_sdk import Keypair
    except ImportError as exc:
        raise RuntimeError(
            "stellar-sdk is required for Stellar signing. Install the project "
            "dependencies or run `pip install stellar-sdk`."
        ) from exc
    return Keypair


def to_jsonable(value: Any) -> Any:
    """Convert dataclasses, pydantic models and bytes into stable JSON values."""

    if dataclasses.is_dataclass(value):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if hasattr(value, "model_dump"):
        return to_jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): to_jsonable(val) for key, val in value.items() if val is not None}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def canonical_json_serialize(data: Any) -> str:
    """Serialize payloads deterministically for hashing and signatures."""

    return json.dumps(to_jsonable(data), sort_keys=True, separators=(",", ":"))


def domain_payload(domain: str, payload: Any) -> Dict[str, Any]:
    return {"domain": domain, "payload": to_jsonable(payload)}


def payload_hash(payload: Any, domain: Optional[str] = None) -> str:
    material = domain_payload(domain, payload) if domain else to_jsonable(payload)
    return hashlib.sha256(canonical_json_serialize(material).encode("utf-8")).hexdigest()


def sign_payload(secret_seed: str, payload: Any, domain: str) -> Dict[str, str]:
    """Sign a domain-separated payload with a Stellar secret seed."""

    Keypair = _stellar_keypair_class()
    keypair = Keypair.from_secret(secret_seed)
    envelope = domain_payload(domain, payload)
    message = canonical_json_serialize(envelope).encode("utf-8")
    signature = keypair.sign(message)
    return {
        "public_key": keypair.public_key,
        "payload_hash": hashlib.sha256(message).hexdigest(),
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def verify_payload(public_key: str, payload: Any, signature: str, domain: str) -> bool:
    """Verify a base64 Stellar signature against a domain-separated payload."""

    if not public_key or not signature:
        return False
    Keypair = _stellar_keypair_class()
    message = canonical_json_serialize(domain_payload(domain, payload)).encode("utf-8")
    try:
        Keypair.from_public_key(public_key).verify(
            message,
            base64.b64decode(signature.encode("ascii"), validate=True),
        )
        return True
    except Exception:
        return False


def miner_result_payload(task_id: str, miner_uid: str, result_data: Any) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "miner_uid": miner_uid,
        "result_data": to_jsonable(result_data),
    }


def validator_task_payload(
    task_id: str,
    cycle: Optional[int],
    deadline: Optional[str],
    miner_uid: Optional[str],
    task_body: Any,
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "cycle": cycle,
        "deadline": deadline,
        "miner_uid": miner_uid,
        "payload_hash": payload_hash(task_body),
    }


def validator_scores_payload(scores: Any, submitter_validator_uid: str, cycle: int) -> Dict[str, Any]:
    return {
        "scores": to_jsonable(scores),
        "submitter_validator_uid": submitter_validator_uid,
        "cycle": cycle,
    }


def score_vote_payload(
    cycle: int,
    task_id: str,
    miner_uid: str,
    score_scaled: int,
    result_hash: str,
    validator_uid: str,
) -> Dict[str, Any]:
    return {
        "cycle": cycle,
        "task_id": task_id,
        "miner_uid": miner_uid,
        "score_scaled": score_scaled,
        "result_hash": result_hash,
        "validator_uid": validator_uid,
    }


def cycle_commit_payload(
    cycle: int,
    score_root: str,
    updates_hash: str,
    quorum_weight: int,
) -> Dict[str, Any]:
    return {
        "cycle": cycle,
        "score_root": score_root,
        "updates_hash": updates_hash,
        "quorum_weight": quorum_weight,
    }
