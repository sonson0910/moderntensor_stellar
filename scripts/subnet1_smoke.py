#!/usr/bin/env python3
"""Deterministic Subnet 1 smoke harness.

The default path is fully local: no network, no model download, and no contract
mutation. Set STELLAR_LIVE_TESTNET=1 to additionally try committing the local
aggregate to the configured Stellar metagraph contract.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

SCRIPT_PATH = Path(__file__).resolve()
MODERNTENSOR_ROOT = SCRIPT_PATH.parents[1]
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
SUBNET1_ROOT = WORKSPACE_ROOT / "subnet1"

for path in (MODERNTENSOR_ROOT, SUBNET1_ROOT):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(MODERNTENSOR_ROOT / ".env")
_load_env_file(MODERNTENSOR_ROOT / ".env.local")

from sdk.chain.base import ChainCycleCommit, MetagraphUpdate  # noqa: E402
from sdk.chain.signing import (  # noqa: E402
    MINER_RESULT_DOMAIN,
    TASK_DOMAIN,
    miner_result_payload,
    payload_hash,
    validator_task_payload,
    verify_payload,
)
from sdk.core.datatypes import MinerInfo, MinerResult, TaskAssignment, ValidatorInfo, ValidatorScore  # noqa: E402
from sdk.network.server import ResultModel, TaskModel, sign_result_model, sign_task_model  # noqa: E402


def _deterministic_clip_score(prompt: str, image_bytes: Optional[bytes] = None, **_: Any) -> float:
    if not prompt or not image_bytes:
        return 0.0
    return 0.875


clip_stub = ModuleType("subnet1.scoring.clip_scorer")
clip_stub.calculate_clip_score = lambda prompt, image_bytes=None, **kwargs: _deterministic_clip_score(  # type: ignore[attr-defined] # noqa: E501
    prompt,
    image_bytes=image_bytes,
    **kwargs,
)
sys.modules.setdefault("subnet1.scoring.clip_scorer", clip_stub)

from subnet1 import validator as subnet1_validator_module  # noqa: E402
from subnet1.validator import Subnet1Validator  # noqa: E402


class SmokeFailure(RuntimeError):
    """Raised when a smoke step fails in a user-actionable way."""


@dataclass
class SmokeReport:
    task_id: str
    cycle: int
    score: float
    result_hash: str
    updates: list[MetagraphUpdate]
    quorum_validators: list[str]
    local_commit_tx: Optional[str]
    live_commit_tx: Optional[str] = None
    live_skipped_reason: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "cycle": self.cycle,
            "score": self.score,
            "result_hash": self.result_hash,
            "updates": [update.__dict__ for update in self.updates],
            "quorum_validators": self.quorum_validators,
            "local_commit_tx": self.local_commit_tx,
            "live_commit_tx": self.live_commit_tx,
            "live_skipped_reason": self.live_skipped_reason,
        }


class LocalChain:
    """In-memory chain client used by the smoke harness."""

    def __init__(self) -> None:
        self.commits: list[tuple[int, list[MetagraphUpdate], list[str], str, str]] = []

    def current_ledger(self) -> int:
        return 840

    def active_participants(self, role: str, cursor: int = 0, limit: int = 100) -> list[Any]:
        return []

    def commit_cycle(
        self,
        cycle: int,
        updates: list[MetagraphUpdate],
        quorum_validators: list[str],
        score_root: str,
        updates_hash: str,
    ) -> ChainCycleCommit:
        self.commits.append((cycle, updates, quorum_validators, score_root, updates_hash))
        return ChainCycleCommit(
            cycle=cycle,
            score_root=score_root,
            updates_hash=updates_hash,
            quorum_weight=float(len(quorum_validators)),
            tx_hash=f"local-smoke-{cycle}",
        )


def _make_tiny_png_base64() -> str:
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDATx\x9cc`\xf8\xcf\xc0\x00\x00\x03\x01"
        b"\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return base64.b64encode(tiny_png).decode("ascii")


def _make_keypair():
    try:
        from stellar_sdk import Keypair
    except ImportError as exc:
        raise SmokeFailure("stellar-sdk is required for Subnet 1 signing smoke.") from exc
    return Keypair.random()


def _sign_and_verify_task(task: TaskModel, validator_secret: str, validator_uid: str, cycle: int) -> TaskModel:
    signed_task = sign_task_model(task, secret_seed=validator_secret, validator_uid=validator_uid, cycle=cycle)
    task_body = {
        "description": signed_task.description,
        "priority": signed_task.priority,
        "task_data": signed_task.task_data,
    }
    signed_payload = validator_task_payload(
        signed_task.task_id,
        signed_task.cycle,
        signed_task.deadline,
        signed_task.task_data.get("miner_uid"),
        task_body,
    )
    if not verify_payload(
        signed_task.validator_public_key or "",
        signed_payload,
        signed_task.signature or "",
        TASK_DOMAIN,
    ):
        raise SmokeFailure("signed validator task did not verify.")
    return signed_task


def _sign_and_verify_result(result: ResultModel, miner_secret: str) -> ResultModel:
    signed_result = sign_result_model(result, secret_seed=miner_secret)
    signed_payload = miner_result_payload(
        signed_result.task_id,
        signed_result.miner_uid,
        signed_result.result_data,
    )
    if not verify_payload(
        signed_result.miner_public_key or "",
        signed_payload,
        signed_result.signature or "",
        MINER_RESULT_DOMAIN,
    ):
        raise SmokeFailure("signed miner result did not verify.")
    return signed_result


async def _run_local_smoke() -> SmokeReport:
    validator_uid = "1"
    peer_validator_uids = ["2", "3"]
    miner_uid = "101"
    cycle = int(os.getenv("SUBNET1_SMOKE_CYCLE", "7"))

    validator_key = _make_keypair()
    miner_key = _make_keypair()
    peer_keys = {uid: _make_keypair() for uid in peer_validator_uids}

    chain = LocalChain()
    old_scorer = subnet1_validator_module.calculate_clip_score
    subnet1_validator_module.calculate_clip_score = _deterministic_clip_score
    try:
        with tempfile.TemporaryDirectory(prefix="subnet1-smoke-") as state_dir:
            node = Subnet1Validator(
                validator_info=ValidatorInfo(
                    uid=validator_uid,
                    public_key=validator_key.public_key,
                    api_endpoint="http://127.0.0.1:18001",
                    stake=10.0,
                    trust_score=1.0,
                ),
                chain_client=chain,
                stellar_secret=validator_key.secret,
                state_file=str(Path(state_dir) / "validator_state.json"),
            )
            try:
                node.current_cycle = cycle
                node.miners_info = {
                    miner_uid: MinerInfo(
                        uid=miner_uid,
                        public_key=miner_key.public_key,
                        api_endpoint="http://127.0.0.1:18000",
                        stake=100.0,
                        trust_score=0.5,
                    )
                }
                node.validators_info = {
                    validator_uid: node.info,
                    **{
                        uid: ValidatorInfo(
                            uid=uid,
                            public_key=key.public_key,
                            api_endpoint=f"http://127.0.0.1:1800{uid}",
                            stake=10.0,
                            trust_score=1.0,
                        )
                        for uid, key in peer_keys.items()
                    },
                }

                task_data = {
                    "description": "A tiny blue square for deterministic smoke scoring.",
                    "deadline": "2030-01-01T00:00:00+00:00",
                    "priority": 1,
                    "validator_endpoint": node.info.api_endpoint,
                    "miner_uid": miner_uid,
                }
                task_id = payload_hash(
                    {
                        "cycle": cycle,
                        "validator_uid": validator_uid,
                        "miner_uid": miner_uid,
                        "task_data": task_data,
                    }
                )[:32]
                task = TaskModel(
                    task_id=task_id,
                    description=task_data["description"],
                    deadline=task_data["deadline"],
                    priority=task_data["priority"],
                    validator_endpoint=node.info.api_endpoint,
                    task_data=task_data,
                    validator_uid=validator_uid,
                    cycle=cycle,
                )
                signed_task = _sign_and_verify_task(task, validator_key.secret, validator_uid, cycle)
                node.tasks_sent[task_id] = TaskAssignment(
                    task_id=task_id,
                    task_data=task_data,
                    miner_uid=miner_uid,
                    validator_uid=validator_uid,
                    timestamp_sent=time.time(),
                    cycle=cycle,
                    payload_hash=signed_task.payload_hash,
                    signature=signed_task.signature,
                    validator_public_key=signed_task.validator_public_key,
                )

                result_data = {
                    "output_description": _make_tiny_png_base64(),
                    "processing_time_ms": 1,
                    "model_id_used": "subnet1-smoke-fake",
                    "error_details": None,
                }
                signed_result = _sign_and_verify_result(
                    ResultModel(task_id=task_id, miner_uid=miner_uid, result_data=result_data),
                    miner_key.secret,
                )
                accepted = await node.add_miner_result(
                    MinerResult(
                        task_id=signed_result.task_id,
                        miner_uid=signed_result.miner_uid,
                        result_data=signed_result.result_data,
                        timestamp_received=time.time(),
                        cycle=cycle,
                        payload_hash=signed_result.payload_hash,
                        signature=signed_result.signature,
                        miner_public_key=signed_result.miner_public_key,
                    )
                )
                if not accepted:
                    raise SmokeFailure("validator rejected the signed miner result.")

                local_scores = node.score_miner_results()
                score_entries = local_scores.get(task_id, [])
                if len(score_entries) != 1:
                    raise SmokeFailure("validator scoring did not produce exactly one score.")
                local_score = score_entries[0]
                if local_score.score != 0.875 or not local_score.result_hash:
                    raise SmokeFailure(f"unexpected validator score: {local_score.score}.")

                await node.add_received_score(validator_uid, cycle, [local_score])
                for uid in peer_validator_uids:
                    await node.add_received_score(
                        uid,
                        cycle,
                        [
                            ValidatorScore(
                                task_id=task_id,
                                miner_uid=miner_uid,
                                validator_uid=uid,
                                score=local_score.score,
                                result_hash=local_score.result_hash,
                            )
                        ],
                    )

                updates, quorum_validators = node.aggregate_cycle_updates(cycle)
                if len(updates) != 1 or quorum_validators != [validator_uid, *peer_validator_uids]:
                    raise SmokeFailure("local aggregation did not reach the expected quorum.")
                local_commit_tx = await node.commit_quorum_state()
                if local_commit_tx != f"local-smoke-{cycle}":
                    raise SmokeFailure("local commit path did not return the expected transaction id.")

                return SmokeReport(
                    task_id=task_id,
                    cycle=cycle,
                    score=local_score.score,
                    result_hash=local_score.result_hash,
                    updates=updates,
                    quorum_validators=quorum_validators,
                    local_commit_tx=local_commit_tx,
                )
            finally:
                await node.http_client.aclose()
    finally:
        subnet1_validator_module.calculate_clip_score = old_scorer


def _live_requested(live: Optional[bool]) -> bool:
    if live is not None:
        return live
    return os.getenv("STELLAR_LIVE_TESTNET") == "1"


def _commit_live(report: SmokeReport) -> Optional[str]:
    contract_id = os.getenv("STELLAR_METAGRAPH_CONTRACT_ID")
    source_secret = os.getenv("VALIDATOR_STELLAR_SECRET")
    if not contract_id or not source_secret:
        raise SmokeFailure(
            "live commit requested, but STELLAR_METAGRAPH_CONTRACT_ID and "
            "VALIDATOR_STELLAR_SECRET are both required."
        )

    from sdk.chain.signing import payload_hash as sdk_payload_hash
    from sdk.chain.stellar import StellarChainClient, build_stellar_testnet_config
    from sdk.config.settings import Settings

    runtime_settings = Settings()
    client = StellarChainClient(build_stellar_testnet_config(runtime_settings))
    live_miner_uid = os.getenv("MINER_UID")
    live_validator_uid = os.getenv("VALIDATOR_UID")
    updates = report.updates
    quorum_validators = report.quorum_validators
    if live_miner_uid:
        updates = [
            MetagraphUpdate(
                uid=live_miner_uid,
                role=update.role,
                performance=update.performance,
                trust=update.trust,
                history_hash=update.history_hash,
                cycle=update.cycle,
            )
            for update in updates
        ]
    if live_validator_uid:
        quorum_validators = [live_validator_uid]
    score_root = sdk_payload_hash([update.__dict__ for update in updates])
    updates_hash = sdk_payload_hash({"updates": [update.__dict__ for update in updates], "cycle": report.cycle})
    commit = client.commit_cycle(
        cycle=report.cycle,
        updates=updates,
        quorum_validators=quorum_validators,
        score_root=score_root,
        updates_hash=updates_hash,
    )
    return commit.tx_hash


def run_smoke(live: Optional[bool] = None) -> SmokeReport:
    report = asyncio.run(_run_local_smoke())
    if _live_requested(live):
        report.live_commit_tx = _commit_live(report)
    else:
        report.live_skipped_reason = "STELLAR_LIVE_TESTNET is not set to 1."
    return report


def _print_report(report: SmokeReport, json_output: bool) -> None:
    if json_output:
        print(json.dumps(report.as_dict(), sort_keys=True, indent=2))
        return
    update = report.updates[0]
    print("[subnet1-smoke] PASS local deterministic smoke")
    print(f"  task_id={report.task_id} cycle={report.cycle}")
    print(f"  signed_task=ok signed_result=ok")
    print(f"  validator_score={report.score:.3f} result_hash={report.result_hash[:12]}...")
    print(
        "  aggregation=ok "
        f"updates={len(report.updates)} quorum={','.join(report.quorum_validators)} "
        f"performance={update.performance:.3f} trust={update.trust:.3f}"
    )
    print(f"  local_commit=ok tx={report.local_commit_tx}")
    if report.live_commit_tx:
        print(f"  live_commit=ok tx={report.live_commit_tx}")
    else:
        print(f"  live_commit=skipped reason={report.live_skipped_reason}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Subnet 1 local smoke harness.")
    live_group = parser.add_mutually_exclusive_group()
    live_group.add_argument("--live", action="store_true", help="Force a live Stellar Testnet commit.")
    live_group.add_argument("--no-live", action="store_true", help="Force local-only mode.")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON report.")
    args = parser.parse_args(argv)

    live: Optional[bool] = None
    if args.live:
        live = True
    elif args.no_live:
        live = False

    try:
        report = run_smoke(live=live)
    except SmokeFailure as exc:
        print(f"[subnet1-smoke] FAIL {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[subnet1-smoke] FAIL unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3 if _live_requested(live) else 2

    _print_report(report, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
