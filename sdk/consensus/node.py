"""Stellar-backed validator node."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from sdk.chain.base import ChainClient, MetagraphUpdate
from sdk.chain.signing import canonical_json_serialize, payload_hash
from sdk.config.settings import settings
from sdk.core.datatypes import (
    MinerInfo,
    MinerResult,
    STATUS_ACTIVE,
    TaskAssignment,
    ValidatorInfo,
    ValidatorScore,
)
from sdk.network.server import TaskModel, sign_task_model

from .selection import select_miners_logic
from .state import validator_weight, weighted_median


logger = logging.getLogger(__name__)


def _active_count(items) -> int:
    return sum(
        1
        for item in items
        if getattr(item, "status", STATUS_ACTIVE) == STATUS_ACTIVE
    )


class ValidatorNode:
    def __init__(
        self,
        validator_info: ValidatorInfo,
        chain_client: ChainClient,
        stellar_secret: str,
        state_file: str = "validator_state.json",
    ):
        if not validator_info.uid:
            raise ValueError("Validator UID is required.")
        if not validator_info.public_key:
            raise ValueError("Validator public key is required.")
        self.info = validator_info
        self.chain_client = chain_client
        self.stellar_secret = stellar_secret
        self.state_file = state_file
        self.settings = settings
        self.current_cycle = self._ledger_to_cycle(self.chain_client.current_ledger())
        self.miners_info: Dict[str, MinerInfo] = {}
        self.validators_info: Dict[str, ValidatorInfo] = {validator_info.uid: validator_info}
        self.tasks_sent: Dict[str, TaskAssignment] = {}
        self.results_buffer: Dict[str, MinerResult] = {}
        self.results_buffer_lock = asyncio.Lock()
        self.received_validator_scores: Dict[int, Dict[str, Dict[str, ValidatorScore]]] = defaultdict(lambda: defaultdict(dict))
        self.received_scores_lock = asyncio.Lock()
        self.http_client = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS)
        self.metrics: Dict[str, int] = defaultdict(int)
        self._load_cycle_state()
        logger.info("ValidatorNode initialized: %s", self.info.uid)

    async def run_forever(self) -> None:
        while True:
            started = time.time()
            await self.run_cycle()
            elapsed = time.time() - started
            await asyncio.sleep(max(5.0, settings.CONSENSUS_MINI_BATCH_WAIT_SECONDS - elapsed))

    async def run_cycle(self) -> None:
        cycle_started = time.time()
        latest_ledger = self.chain_client.current_ledger()
        self.current_cycle = self._ledger_to_cycle(latest_ledger)
        self._log_cycle_event(
            logging.INFO,
            "cycle_start",
            latest_ledger=latest_ledger,
        )
        await self.load_metagraph_state()
        selected = self.select_miners()
        await self.send_tasks_to_miners(selected)
        await asyncio.sleep(settings.CONSENSUS_MINI_BATCH_WAIT_SECONDS)
        scores = self.score_miner_results()
        await self.add_received_score(
            self.info.uid,
            self.current_cycle,
            [score for entries in scores.values() for score in entries],
        )
        await self.broadcast_scores(scores)
        await self.commit_quorum_state()
        self.prune_cycle_state()
        self._persist_cycle_state()
        self.metrics["cycles_completed"] += 1
        self._log_cycle_event(
            logging.INFO,
            "cycle_end",
            duration_ms=int((time.time() - cycle_started) * 1000),
            tasks_sent=len(self.tasks_sent),
            results_buffered=len(self.results_buffer),
            local_scores=sum(len(entries) for entries in scores.values()),
        )

    async def load_metagraph_state(self) -> None:
        miners = getattr(self.chain_client, "active_participants", lambda role: [])("miner")
        validators = getattr(self.chain_client, "active_participants", lambda role: [])("validator")
        self.miners_info = {
            item.uid: MinerInfo(
                uid=item.uid,
                public_key=item.public_key,
                api_endpoint=item.api_endpoint,
                stake=item.stake,
                trust_score=item.trust_score,
                status=item.status,
                performance_history=[item.performance],
                history_hash=item.history_hash,
            )
            for item in miners
        }
        self.validators_info.update(
            {
                item.uid: ValidatorInfo(
                    uid=item.uid,
                    public_key=item.public_key,
                    api_endpoint=item.api_endpoint,
                    stake=item.stake,
                    trust_score=item.trust_score,
                    status=item.status,
                    last_performance=item.performance,
                    history_hash=item.history_hash,
                )
                for item in validators
            }
        )

    def select_miners(self) -> List[MinerInfo]:
        return select_miners_logic(
            miners_info=self.miners_info,
            current_cycle=self.current_cycle,
            num_to_select=settings.CONSENSUS_NUM_MINERS_TO_SELECT,
            beta=0.2,
            max_time_bonus=10,
        )

    async def send_tasks_to_miners(self, miners: List[MinerInfo]) -> Dict[str, TaskAssignment]:
        assignments: Dict[str, TaskAssignment] = {}
        tasks = []
        for miner in miners:
            if miner.status != STATUS_ACTIVE or not miner.api_endpoint:
                continue
            task_data = self._create_task_data(miner.uid)
            task_body_hash = payload_hash(
                {
                    "cycle": self.current_cycle,
                    "validator_uid": self.info.uid,
                    "miner_uid": miner.uid,
                    "task_data": task_data,
                }
            )
            task_id = payload_hash(
                {
                    "cycle": self.current_cycle,
                    "validator_uid": self.info.uid,
                    "miner_uid": miner.uid,
                    "payload_hash": task_body_hash,
                }
            )[:32]
            task = TaskModel(
                task_id=task_id,
                description=task_data["description"],
                validator_endpoint=self.info.api_endpoint,
                task_data={"miner_uid": miner.uid, **task_data},
                validator_uid=self.info.uid,
                cycle=self.current_cycle,
            )
            sign_task_model(task, self.stellar_secret, self.info.uid, self.current_cycle)
            assignment = TaskAssignment(
                task_id=task_id,
                task_data=task_data,
                miner_uid=miner.uid,
                validator_uid=self.info.uid,
                timestamp_sent=time.time(),
                cycle=self.current_cycle,
                payload_hash=task.payload_hash,
                signature=task.signature,
                validator_public_key=task.validator_public_key,
            )
            self.tasks_sent[task_id] = assignment
            assignments[task_id] = assignment
            tasks.append(self._send_task(miner.api_endpoint, task))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.metrics["tasks_sent_total"] += len(tasks)
            self.metrics["task_send_success_total"] += sum(
                1 for result in results if result is True
            )
            self.metrics["task_send_failures"] += sum(
                1 for result in results if result is not True
            )
        return assignments

    async def add_miner_result(self, result: MinerResult) -> bool:
        assignment = self.tasks_sent.get(result.task_id)
        if not assignment or assignment.miner_uid != result.miner_uid:
            self.metrics["miner_results_rejected_total"] += 1
            return False
        async with self.results_buffer_lock:
            if result.task_id in self.results_buffer:
                self.metrics["miner_results_rejected_total"] += 1
                return False
            self.results_buffer[result.task_id] = result
            self.metrics["miner_results_accepted_total"] += 1
        return True

    def score_miner_results(self) -> Dict[str, List[ValidatorScore]]:
        scores: Dict[str, List[ValidatorScore]] = defaultdict(list)
        for task_id, result in list(self.results_buffer.items()):
            assignment = self.tasks_sent.get(task_id)
            if not assignment:
                continue
            score_value = self._score_individual_result(assignment.task_data, result.result_data)
            result_hash = payload_hash(result.result_data)
            scores[task_id].append(
                ValidatorScore(
                    task_id=task_id,
                    miner_uid=result.miner_uid,
                    validator_uid=self.info.uid,
                    score=max(0.0, min(1.0, score_value)),
                    result_hash=result_hash,
                )
            )
        return dict(scores)

    async def add_received_score(self, submitter_uid: str, cycle: int, scores: List[ValidatorScore]) -> None:
        if cycle < self.current_cycle - 1 or cycle > self.current_cycle:
            self.metrics["stale_score_votes"] += 1
            self.metrics["validator_score_votes_rejected_total"] += 1
            return
        submitter = self.validators_info.get(submitter_uid)
        if not submitter or submitter.status != STATUS_ACTIVE:
            self.metrics["unknown_or_inactive_score_votes"] += 1
            self.metrics["validator_score_votes_rejected_total"] += 1
            return
        async with self.received_scores_lock:
            for score in scores:
                if score.validator_uid != submitter_uid:
                    self.metrics["mismatched_score_votes"] += 1
                    self.metrics["validator_score_votes_rejected_total"] += 1
                    continue
                if not (0.0 <= score.score <= 1.0):
                    self.metrics["invalid_score_votes"] += 1
                    self.metrics["validator_score_votes_rejected_total"] += 1
                    continue
                if score.validator_uid in self.received_validator_scores[cycle][score.task_id]:
                    self.metrics["duplicate_score_votes"] += 1
                    self.metrics["validator_score_votes_rejected_total"] += 1
                    continue
                self.received_validator_scores[cycle][score.task_id][score.validator_uid] = score
                self.metrics["validator_score_votes_accepted_total"] += 1

    async def broadcast_scores(self, scores: Dict[str, List[ValidatorScore]]) -> None:
        from .scoring import broadcast_scores_logic

        await broadcast_scores_logic(self, scores)

    async def commit_quorum_state(self) -> Optional[str]:
        updates, quorum_validators = self.aggregate_cycle_updates(self.current_cycle)
        self._log_cycle_event(
            logging.INFO,
            "quorum_evaluated",
            updates=len(updates),
            quorum_validators=len(quorum_validators),
            quorum_weight=self._validator_weight_sum(quorum_validators),
            threshold=self._quorum_threshold(),
        )
        if not updates:
            self.metrics["commit_skipped_no_quorum"] += 1
            logger.info("Cycle %s skipped commit: no quorum-ready miner updates.", self.current_cycle)
            return None
        score_root = payload_hash([update.__dict__ for update in updates])
        updates_hash = payload_hash({"updates": [update.__dict__ for update in updates], "cycle": self.current_cycle})
        try:
            commit = self.chain_client.commit_cycle(
                cycle=self.current_cycle,
                updates=updates,
                quorum_validators=quorum_validators,
                score_root=score_root,
                updates_hash=updates_hash,
            )
            self.metrics["cycle_commits"] += 1
            logger.info(
                "Cycle %s committed: updates=%s quorum_validators=%s tx=%s",
                self.current_cycle,
                len(updates),
                len(quorum_validators),
                getattr(commit, "tx_hash", None),
            )
            return getattr(commit, "tx_hash", None)
        except Exception as exc:
            self.metrics["commit_failures"] += 1
            logger.warning("Cycle %s commit failed: %s", self.current_cycle, exc)
            return None

    def aggregate_cycle_updates(self, cycle: int) -> tuple[List[MetagraphUpdate], List[str]]:
        cycle_scores = self.received_validator_scores.get(cycle, {})
        miner_votes: Dict[str, Dict[str, ValidatorScore]] = defaultdict(dict)
        for task_scores in cycle_scores.values():
            for validator_uid, score in task_scores.items():
                miner_votes[score.miner_uid][validator_uid] = score

        updates: List[MetagraphUpdate] = []
        quorum_validators: set[str] = set()
        threshold = self._quorum_threshold()
        alpha = settings.CONSENSUS_TRUST_EMA_ALPHA
        for miner_uid, votes in miner_votes.items():
            weighted_values = []
            vote_weight = 0.0
            for validator_uid, score in votes.items():
                validator = self.validators_info.get(validator_uid)
                if not validator or validator.status != STATUS_ACTIVE:
                    continue
                weight = validator_weight(validator.stake, validator.trust_score)
                if weight <= 0:
                    continue
                vote_weight += weight
                weighted_values.append((score.score, weight))
            if vote_weight < threshold:
                continue
            aggregate_score = weighted_median(weighted_values)
            miner = self.miners_info.get(miner_uid)
            old_trust = miner.trust_score if miner else 0.0
            new_trust = max(0.0, min(1.0, old_trust * (1.0 - alpha) + aggregate_score * alpha))
            updates.append(
                MetagraphUpdate(
                    uid=miner_uid,
                    role="miner",
                    performance=aggregate_score,
                    trust=new_trust,
                    history_hash=payload_hash(
                        {
                            "cycle": cycle,
                            "miner_uid": miner_uid,
                            "votes": [score.__dict__ for score in votes.values()],
                        }
                    ),
                    cycle=cycle,
                )
            )
            quorum_validators.update(votes.keys())
        return updates, sorted(quorum_validators)

    def _quorum_threshold(self) -> float:
        active_validators = [v for v in self.validators_info.values() if v.status == STATUS_ACTIVE]
        total = sum(validator_weight(v.stake, v.trust_score) for v in active_validators)
        return total * settings.CONSENSUS_QUORUM_RATIO

    def _validator_weight_sum(self, validator_uids: List[str]) -> float:
        total = 0.0
        for validator_uid in validator_uids:
            validator = self.validators_info.get(validator_uid)
            if validator and validator.status == STATUS_ACTIVE:
                total += validator_weight(validator.stake, validator.trust_score)
        return total

    def metrics_snapshot(self) -> Dict[str, object]:
        queue_capacity = max(1, settings.API_TASK_QUEUE_SIZE)
        task_queue_depth = len(self.tasks_sent)
        result_queue_depth = len(self.results_buffer)
        queue_depth = max(task_queue_depth, result_queue_depth)
        votes_buffered = sum(
            len(validators)
            for tasks in self.received_validator_scores.values()
            for validators in tasks.values()
        )
        snapshot: Dict[str, object] = {
            "cycle": self.current_cycle,
            "validator_uid": self.info.uid,
            "peers": {
                "miners_total": len(self.miners_info),
                "miners_active": _active_count(self.miners_info.values()),
                "validators_total": len(self.validators_info),
                "validators_active": _active_count(self.validators_info.values()),
            },
            "queues": {
                "capacity": queue_capacity,
                "task_depth": task_queue_depth,
                "result_depth": result_queue_depth,
                "saturation": round(queue_depth / queue_capacity, 6),
                "saturated": queue_depth >= queue_capacity,
            },
            "buffers": {
                "votes_buffered": votes_buffered,
            },
            "counters": dict(self.metrics),
        }
        snapshot["counters"].setdefault("commit_failures", 0)
        snapshot["counters"].setdefault("cycle_commits", 0)
        snapshot["counters"].setdefault("tasks_sent_total", 0)
        snapshot["counters"].setdefault("miner_results_accepted_total", 0)
        snapshot["counters"].setdefault("miner_results_rejected_total", 0)
        snapshot["counters"].setdefault("validator_score_votes_accepted_total", 0)
        snapshot["counters"].setdefault("validator_score_votes_rejected_total", 0)
        return snapshot

    def _log_cycle_event(self, level: int, event: str, **fields) -> None:
        structured_fields = {
            "event": event,
            "cycle": self.current_cycle,
            "validator_uid": self.info.uid,
            **fields,
        }
        field_text = " ".join(
            f"{key}={value}" for key, value in sorted(structured_fields.items())
        )
        logger.log(level, "validator_cycle_event %s", field_text, extra=structured_fields)

    async def _send_task(self, endpoint: str, task: TaskModel) -> bool:
        url = f"{endpoint.rstrip('/')}/receive-task"
        payload = task.model_dump(mode="json") if hasattr(task, "model_dump") else task.dict()
        response = await self.http_client.post(url, json=payload, timeout=settings.CONSENSUS_NETWORK_TIMEOUT_SECONDS)
        return 200 <= response.status_code < 300

    def prune_cycle_state(self) -> None:
        min_cycle = self.current_cycle - settings.CONSENSUS_STATE_RETENTION_CYCLES
        self.tasks_sent = {
            task_id: assignment
            for task_id, assignment in self.tasks_sent.items()
            if assignment.cycle is None or assignment.cycle >= min_cycle
        }
        self.results_buffer = {
            task_id: result
            for task_id, result in self.results_buffer.items()
            if result.cycle is None or result.cycle >= min_cycle
        }
        for cycle in list(self.received_validator_scores.keys()):
            if cycle < min_cycle:
                del self.received_validator_scores[cycle]

    def _persist_cycle_state(self) -> None:
        path = Path(self.state_file)
        payload = {
            "current_cycle": self.current_cycle,
            "metrics": dict(self.metrics),
            "received_validator_scores": {
                str(cycle): {
                    task_id: {validator_uid: score.__dict__ for validator_uid, score in validators.items()}
                    for task_id, validators in tasks.items()
                }
                for cycle, tasks in self.received_validator_scores.items()
            },
        }
        path.write_text(canonical_json_serialize(payload) + "\n")

    def _load_cycle_state(self) -> None:
        path = Path(self.state_file)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        self.metrics.update(data.get("metrics", {}))
        for cycle_text, tasks in data.get("received_validator_scores", {}).items():
            try:
                cycle = int(cycle_text)
            except ValueError:
                continue
            for task_id, validators in tasks.items():
                for validator_uid, score_data in validators.items():
                    try:
                        self.received_validator_scores[cycle][task_id][validator_uid] = ValidatorScore(**score_data)
                    except TypeError:
                        continue

    async def _get_active_validators(self) -> List[ValidatorInfo]:
        return [item for item in self.validators_info.values() if item.status == STATUS_ACTIVE and item.api_endpoint]

    def _create_task_data(self, miner_uid: str) -> Dict[str, str]:
        return {"description": f"Generate a concise training artifact for miner {miner_uid}"}

    def _score_individual_result(self, task_data, result_data) -> float:
        if isinstance(result_data, dict) and not result_data.get("error_details"):
            return 1.0
        return 0.0

    @staticmethod
    def _ledger_to_cycle(ledger: int) -> int:
        return max(0, ledger // settings.CONSENSUS_CYCLE_LEDGER_LENGTH)
