"""Core data types for the Stellar-only ModernTensor runtime."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


STATUS_INACTIVE = 0
STATUS_ACTIVE = 1
STATUS_JAILED = 2


@dataclass
class MinerInfo:
    uid: str
    public_key: str
    api_endpoint: Optional[str] = None
    trust_score: float = 0.0
    weight: float = 0.0
    stake: float = 0.0
    last_selected_time: int = -1
    performance_history: List[float] = field(default_factory=list)
    status: int = STATUS_ACTIVE
    subnet_uid: int = 0
    registration_ledger: int = 0
    history_hash: str = ""


@dataclass
class ValidatorInfo:
    uid: str
    public_key: str
    api_endpoint: Optional[str] = None
    trust_score: float = 0.0
    weight: float = 0.0
    stake: float = 0.0
    last_performance: float = 0.0
    status: int = STATUS_ACTIVE
    subnet_uid: int = 0
    registration_ledger: int = 0
    performance_history: List[float] = field(default_factory=list)
    history_hash: str = ""


@dataclass
class TaskAssignment:
    task_id: str
    task_data: Any
    miner_uid: str
    validator_uid: str
    timestamp_sent: float
    expected_result_format: Any = field(default_factory=dict)
    cycle: Optional[int] = None
    payload_hash: Optional[str] = None
    signature: Optional[str] = None
    validator_public_key: Optional[str] = None


@dataclass
class MinerResult:
    task_id: str
    miner_uid: str
    result_data: Any
    timestamp_received: float
    cycle: Optional[int] = None
    payload_hash: Optional[str] = None
    signature: Optional[str] = None
    miner_public_key: Optional[str] = None


@dataclass
class ValidatorScore:
    task_id: str
    miner_uid: str
    validator_uid: str
    score: float
    deviation: Optional[float] = None
    result_hash: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ParticipantUpdate:
    uid: str
    role: str
    performance: float
    trust: float
    history_hash: str
    cycle: int


@dataclass
class CycleCommit:
    cycle: int
    score_root: str
    updates_hash: str
    quorum_weight: float
    tx_hash: Optional[str] = None


class ScoreSubmissionPayload(BaseModel):
    scores: List[ValidatorScore] = Field(..., description="Validator score entries.")
    submitter_validator_uid: str = Field(..., description="Validator UID.")
    cycle: int = Field(..., description="Consensus cycle.")
    submitter_public_key: Optional[str] = Field(None, description="Stellar public key.")
    payload_hash: Optional[str] = Field(None, description="Canonical payload hash.")
    signature: Optional[str] = Field(None, description="Stellar signature.")


class MinerConsensusResult(BaseModel):
    miner_uid: str
    p_adj: float
    calculated_incentive: float


class CycleConsensusResults(BaseModel):
    cycle: int
    results: Dict[str, MinerConsensusResult]
    publisher_uid: Optional[str] = None
    publish_timestamp: float = Field(default_factory=time.time)
