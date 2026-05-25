"""Chain-neutral types used by the ModernTensor runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


@dataclass(frozen=True)
class StellarNetworkConfig:
    """Configuration for the official Stellar Testnet services."""

    network_name: str
    network_passphrase: str
    horizon_url: str
    soroban_rpc_url: str
    friendbot_url: str
    metagraph_contract_id: Optional[str] = None
    source_account: Optional[str] = None
    stellar_cli_bin: str = "stellar"
    subnet_id: int = 1
    token_amount_scale: int = 10_000_000
    require_signed_payloads: bool = True
    max_request_bytes: int = 1_000_000
    task_queue_size: int = 64


@dataclass(frozen=True)
class ChainAccount:
    """A chain account identity.

    `secret` is optional so public registry records can use this type without
    accidentally carrying private material.
    """

    public_key: str
    secret: Optional[str] = None


@dataclass
class MetagraphParticipant:
    """Chain-neutral metagraph participant representation."""

    uid: str
    role: str
    public_key: str
    api_endpoint: str
    stake: float
    trust_score: float = 0.0
    performance: float = 0.0
    status: int = 1
    cycle: int = 0
    history_hash: str = ""
    reward_balance: float = 0.0


@dataclass
class MetagraphUpdate:
    uid: str
    role: str
    performance: float
    trust: float
    history_hash: str
    cycle: int


@dataclass
class ChainCycleCommit:
    cycle: int
    score_root: str
    updates_hash: str
    quorum_weight: float
    committed_at_ledger: int = 0
    tx_hash: Optional[str] = None
    subnet_id: int = 1
    distributed_rewards: float = 0.0


@dataclass
class UnbondRequest:
    amount: float
    requested_ledger: int
    unlock_ledger: int
    subnet_id: int = 1


@dataclass(frozen=True)
class SubnetConfig:
    subnet_id: int
    owner: str
    commit_authority: str
    stake_token: str
    treasury: str
    emission_per_cycle: float
    miner_emission_bps: int
    validator_emission_bps: int
    max_miners: int
    max_validators: int
    min_miner_stake: float
    min_validator_stake: float
    registration_fee: float
    status: int
    created_ledger: int = 0


@dataclass(frozen=True)
class SubnetCreationPolicy:
    max_subnets: int
    subnet_count: int
    subnet_registration_fee: float


@dataclass
class MetagraphState:
    miners: List[MetagraphParticipant]
    validators: List[MetagraphParticipant]
    ledger: int


class ChainClient(Protocol):
    """Minimal blockchain operations the SDK runtime needs."""

    def current_ledger(self) -> int:
        """Return the latest ledger sequence."""

    def fund_test_account(self, public_key: str) -> Dict[str, Any]:
        """Fund a testnet account."""

    def get_account(self, public_key: str) -> Dict[str, Any]:
        """Return raw account information."""

    def query_participant(self, uid: str, role: str) -> Optional[MetagraphParticipant]:
        """Read one miner or validator from the metagraph registry."""

    def get_participant_state(self, uid: str, role: str, at_cycle: Optional[int] = None) -> Optional[MetagraphParticipant]:
        """Read participant state. Historical cycles may be served by an indexer."""

    def active_participants(self, role: str, cursor: int = 0, limit: int = 100) -> List[MetagraphParticipant]:
        """Read active participants with pagination."""

    def register_participant(self, participant: MetagraphParticipant, source_account: Optional[str] = None) -> str:
        """Register a miner or validator and return a transaction hash."""

    def set_participant_status(
        self,
        uid: str,
        role: str,
        status: int,
        reason: str,
        source_account: Optional[str] = None,
    ) -> str:
        """Update participant status and return a transaction hash."""

    def update_participant_state(
        self,
        uid: str,
        role: str,
        performance: float,
        trust: float,
        cycle: int,
        history_hash: str = "",
    ) -> str:
        """Update on-chain participant state and return a transaction hash."""

    def commit_cycle(
        self,
        cycle: int,
        updates: List[MetagraphUpdate],
        quorum_validators: List[str],
        score_root: str,
        updates_hash: str,
    ) -> ChainCycleCommit:
        """Commit an aggregated cycle update after validator quorum."""

    def get_cycle_commit(self, cycle: int) -> Optional[ChainCycleCommit]:
        """Read a committed cycle snapshot."""

    def get_unbond_request(self, uid: str, role: str) -> Optional[UnbondRequest]:
        """Read a pending unbond request for a participant."""

    def request_unbond(self, uid: str, role: str, amount: float, source_account: Optional[str] = None) -> UnbondRequest:
        """Request stake unbonding after the contract cooldown."""

    def withdraw_unbonded(self, uid: str, role: str, source_account: Optional[str] = None) -> float:
        """Withdraw stake after a pending unbond request unlocks."""

    def slash_stake(
        self,
        uid: str,
        role: str,
        authority: str,
        amount: float,
        source_account: Optional[str] = None,
    ) -> float:
        """Slash participant stake into the subnet reward reserve."""

    def set_subnet_status(self, status: int, subnet_id: Optional[int] = None, source_account: Optional[str] = None) -> str:
        """Set subnet lifecycle status."""

    def update_subnet_tokenomics(
        self,
        emission_per_cycle: float,
        miner_emission_bps: int,
        validator_emission_bps: int,
        subnet_id: Optional[int] = None,
        source_account: Optional[str] = None,
    ) -> str:
        """Update subnet emission and reward split."""

    def update_subnet_registration(
        self,
        max_miners: int,
        max_validators: int,
        min_miner_stake: float,
        min_validator_stake: float,
        registration_fee: float,
        subnet_id: Optional[int] = None,
        source_account: Optional[str] = None,
    ) -> str:
        """Update subnet registration caps, minimum stake, and fee."""

    def get_subnet_creation_policy(self) -> SubnetCreationPolicy:
        """Read global subnet creation caps and fee."""

    def update_subnet_creation_policy(
        self,
        max_subnets: int,
        subnet_registration_fee: float,
        source_account: Optional[str] = None,
    ) -> str:
        """Update global subnet creation cap and fee."""
