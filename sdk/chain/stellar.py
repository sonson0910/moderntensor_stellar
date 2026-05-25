"""Stellar Testnet client and metagraph contract helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    ChainAccount,
    ChainCycleCommit,
    MetagraphParticipant,
    MetagraphUpdate,
    StellarNetworkConfig,
    SubnetConfig,
    UnbondRequest,
)

TOKEN_AMOUNT_SCALE = 10_000_000


def _stellar_sdk():
    try:
        import stellar_sdk
    except ImportError as exc:
        raise RuntimeError("stellar-sdk is required for the Stellar runtime.") from exc
    return stellar_sdk


def build_stellar_testnet_config(settings: Any) -> StellarNetworkConfig:
    return StellarNetworkConfig(
        network_name=settings.STELLAR_NETWORK,
        network_passphrase=settings.STELLAR_NETWORK_PASSPHRASE,
        horizon_url=settings.STELLAR_HORIZON_URL,
        soroban_rpc_url=settings.STELLAR_RPC_URL,
        friendbot_url=settings.STELLAR_FRIENDBOT_URL,
        metagraph_contract_id=getattr(settings, "STELLAR_METAGRAPH_CONTRACT_ID", None),
        source_account=getattr(settings, "VALIDATOR_STELLAR_SECRET", None),
        stellar_cli_bin=getattr(settings, "STELLAR_CLI_BIN", "stellar"),
        subnet_id=getattr(settings, "SUBNET_ID", 1),
        token_amount_scale=getattr(settings, "STELLAR_TOKEN_AMOUNT_SCALE", 10_000_000),
        require_signed_payloads=settings.REQUIRE_SIGNED_PAYLOADS,
        max_request_bytes=settings.API_MAX_REQUEST_BYTES,
        task_queue_size=settings.API_TASK_QUEUE_SIZE,
    )


class StellarChainClient:
    """Horizon, Friendbot, and Stellar CLI backed Soroban operations."""

    def __init__(self, config: StellarNetworkConfig, timeout: float = 15.0):
        self.config = config
        self.timeout = timeout
        self._server = _stellar_sdk().Server(horizon_url=config.horizon_url)

    @staticmethod
    def generate_account() -> ChainAccount:
        keypair = _stellar_sdk().Keypair.random()
        return ChainAccount(public_key=keypair.public_key, secret=keypair.secret)

    @staticmethod
    def public_key_from_secret(secret_seed: str) -> str:
        return _stellar_sdk().Keypair.from_secret(secret_seed).public_key

    def get_account(self, public_key: str) -> Dict[str, Any]:
        return self._server.accounts().account_id(public_key).call()

    def current_ledger(self) -> int:
        response = self._server.ledgers().order(desc=True).limit(1).call()
        records = response.get("_embedded", {}).get("records", [])
        if not records:
            raise RuntimeError("Horizon returned no ledgers.")
        return int(records[0]["sequence"])

    def fund_test_account(self, public_key: str) -> Dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is required to call Friendbot.") from exc
        response = requests.get(
            self.config.friendbot_url,
            params={"addr": public_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def deploy_contract(self, wasm_path: str, source_account: Optional[str] = None) -> str:
        path = Path(wasm_path)
        if not path.exists():
            raise FileNotFoundError(f"Contract wasm not found: {wasm_path}")
        output = self._run_stellar_cli(
            [
                "contract",
                "deploy",
                "--wasm",
                str(path),
                "--network",
                "testnet",
                "--source-account",
                self._source(source_account),
            ]
        )
        return output.strip().splitlines()[-1].strip()

    def invoke_contract(
        self,
        function: str,
        args: Optional[List[str]] = None,
        source_account: Optional[str] = None,
        contract_id: Optional[str] = None,
    ) -> str:
        target = contract_id or self._contract_id()
        command = [
            "contract",
            "invoke",
            "--id",
            target,
            "--network",
            "testnet",
            "--source-account",
            self._source(source_account),
            "--",
            function,
        ]
        command.extend(args or [])
        return self._run_stellar_cli(command).strip()

    def query_participant(self, uid: str, role: str) -> Optional[MetagraphParticipant]:
        raw = self.invoke_contract(
            self._subnet_function("get_participant", "get_participant_for_subnet"),
            [*self._subnet_args(), "--role", self._role_variant(role), "--uid", str(uid)],
        )
        return self._parse_participant(raw, role)

    def active_participants(self, role: str, cursor: int = 0, limit: int = 100) -> List[MetagraphParticipant]:
        raw = self.invoke_contract(
            self._subnet_function("active_participants", "active_participants_for_subnet"),
            [
                *self._subnet_args(),
                "--role",
                self._role_variant(role),
                "--cursor",
                str(cursor),
                "--limit",
                str(limit),
            ],
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [item for item in (self._participant_from_mapping(x, role) for x in data) if item]

    def register_participant(self, participant: MetagraphParticipant, source_account: Optional[str] = None) -> str:
        if participant.role == "miner":
            function = self._subnet_function("register_miner", "register_miner_for_subnet")
        else:
            function = self._subnet_function("register_validator", "register_validator_for_subnet")
        return self.invoke_contract(
            function,
            [
                *self._subnet_args(),
                "--uid",
                str(participant.uid),
                "--owner",
                participant.public_key,
                "--endpoint",
                self._json_string(participant.api_endpoint),
                "--stake_amount",
                str(int(round(participant.stake * self.config.token_amount_scale))),
            ],
            source_account=source_account,
        )

    def update_participant_state(
        self,
        uid: str,
        role: str,
        performance: float,
        trust: float,
        cycle: int,
        history_hash: str = "",
    ) -> str:
        raise RuntimeError("Direct participant state updates are disabled; use commit_cycle with validator quorum.")

    def commit_cycle(
        self,
        cycle: int,
        updates: List[MetagraphUpdate],
        quorum_validators: List[str],
        score_root: str,
        updates_hash: str,
    ) -> ChainCycleCommit:
        raw = self.invoke_contract(
            self._subnet_function("commit_cycle", "commit_cycle_for_subnet"),
            [
                *self._subnet_args(),
                "--cycle",
                str(cycle),
                "--score_root",
                self._json_string(score_root),
                "--updates_hash",
                self._json_string(updates_hash),
                "--updates",
                json.dumps([self._contract_update(item) for item in updates], separators=(",", ":")),
                "--quorum_validators",
                json.dumps([int(uid) for uid in quorum_validators], separators=(",", ":")),
            ],
        )
        parsed = self._parse_cycle_commit(raw)
        if parsed:
            parsed.tx_hash = raw if raw and not raw.lstrip().startswith("{") else None
            return parsed
        return ChainCycleCommit(
            cycle=cycle,
            score_root=score_root,
            updates_hash=updates_hash,
            quorum_weight=0.0,
            tx_hash=raw,
        )

    def get_cycle_commit(self, cycle: int) -> Optional[ChainCycleCommit]:
        raw = self.invoke_contract(
            self._subnet_function("get_cycle_commit", "get_cycle_commit_for_subnet"),
            [*self._subnet_args(), "--cycle", str(cycle)],
        )
        return self._parse_cycle_commit(raw)

    def get_participant_state(
        self,
        uid: str,
        role: str,
        at_cycle: Optional[int] = None,
    ) -> Optional[MetagraphParticipant]:
        if at_cycle is not None:
            raise RuntimeError("Historical participant state requires the local indexer cache.")
        raw = self.invoke_contract(
            self._subnet_function("get_participant_state", "get_participant_state_for_subnet"),
            [*self._subnet_args(), "--role", self._role_variant(role), "--uid", str(uid)],
        )
        return self._parse_participant(raw, role)

    def set_participant_status(
        self,
        uid: str,
        role: str,
        status: int,
        reason: str,
        source_account: Optional[str] = None,
    ) -> str:
        return self.invoke_contract(
            self._subnet_function("set_status", "set_status_for_subnet"),
            [
                *self._subnet_args(),
                "--uid",
                uid,
                "--role",
                self._role_variant(role),
                "--status",
                str(status),
                "--reason",
                self._json_string(reason),
            ],
            source_account=source_account,
        )

    def get_unbond_request(self, uid: str, role: str) -> Optional[UnbondRequest]:
        raw = self.invoke_contract(
            self._subnet_function("get_unbond_request", "get_unbond_request_for_subnet"),
            [*self._subnet_args(), "--uid", str(uid), "--role", self._role_variant(role)],
        )
        return self._parse_unbond_request(raw)

    def request_unbond(
        self,
        uid: str,
        role: str,
        amount: float,
        source_account: Optional[str] = None,
    ) -> UnbondRequest:
        raw = self.invoke_contract(
            self._subnet_function("request_unbond", "request_unbond_for_subnet"),
            [
                *self._subnet_args(),
                "--uid",
                str(uid),
                "--role",
                self._role_variant(role),
                "--amount",
                self._amount_to_contract_units(amount),
            ],
            source_account=source_account,
        )
        parsed = self._parse_unbond_request(raw)
        if parsed is None:
            raise RuntimeError(f"Contract did not return a valid unbond request: {raw}")
        return parsed

    def withdraw_unbonded(
        self,
        uid: str,
        role: str,
        source_account: Optional[str] = None,
    ) -> float:
        raw = self.invoke_contract(
            self._subnet_function("withdraw_unbonded", "withdraw_unbonded_for_subnet"),
            [*self._subnet_args(), "--uid", str(uid), "--role", self._role_variant(role)],
            source_account=source_account,
        )
        return self._amount_from_raw(raw)

    def slash_stake(
        self,
        uid: str,
        role: str,
        authority: str,
        amount: float,
        source_account: Optional[str] = None,
    ) -> float:
        raw = self.invoke_contract(
            self._subnet_function("slash_stake", "slash_stake_for_subnet"),
            [
                *self._subnet_args(),
                "--uid",
                str(uid),
                "--role",
                self._role_variant(role),
                "--authority",
                authority,
                "--amount",
                self._amount_to_contract_units(amount),
            ],
            source_account=source_account,
        )
        return self._amount_from_raw(raw)

    def set_subnet_status(
        self,
        status: int,
        subnet_id: Optional[int] = None,
        source_account: Optional[str] = None,
    ) -> str:
        return self.invoke_contract(
            "set_subnet_status",
            ["--subnet_id", str(subnet_id or self.config.subnet_id), "--status", str(status)],
            source_account=source_account,
        )

    def pause_subnet(self, subnet_id: Optional[int] = None, source_account: Optional[str] = None) -> str:
        return self.invoke_contract(
            "pause_subnet",
            ["--subnet_id", str(subnet_id or self.config.subnet_id)],
            source_account=source_account,
        )

    def resume_subnet(self, subnet_id: Optional[int] = None, source_account: Optional[str] = None) -> str:
        return self.invoke_contract(
            "resume_subnet",
            ["--subnet_id", str(subnet_id or self.config.subnet_id)],
            source_account=source_account,
        )

    def update_subnet_tokenomics(
        self,
        emission_per_cycle: float,
        miner_emission_bps: int,
        validator_emission_bps: int,
        subnet_id: Optional[int] = None,
        source_account: Optional[str] = None,
    ) -> str:
        return self.invoke_contract(
            "update_subnet_tokenomics",
            [
                "--subnet_id",
                str(subnet_id or self.config.subnet_id),
                "--emission_per_cycle",
                self._amount_to_contract_units(emission_per_cycle),
                "--miner_emission_bps",
                str(miner_emission_bps),
                "--validator_emission_bps",
                str(validator_emission_bps),
            ],
            source_account=source_account,
        )

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
        return self.invoke_contract(
            "update_subnet_registration",
            [
                "--subnet_id",
                str(subnet_id or self.config.subnet_id),
                "--max_miners",
                str(max_miners),
                "--max_validators",
                str(max_validators),
                "--min_miner_stake",
                self._amount_to_contract_units(min_miner_stake),
                "--min_validator_stake",
                self._amount_to_contract_units(min_validator_stake),
                "--registration_fee",
                str(int(round(registration_fee * self.config.token_amount_scale))),
            ],
            source_account=source_account,
        )

    def get_subnet(self, subnet_id: Optional[int] = None) -> Optional[SubnetConfig]:
        raw = self.invoke_contract(
            "get_subnet",
            ["--subnet_id", str(subnet_id or self.config.subnet_id)],
        )
        return self._parse_subnet(raw)

    def reward_balance(self, uid: str, role: str, subnet_id: Optional[int] = None) -> float:
        raw = self.invoke_contract(
            "reward_balance",
            [
                "--subnet_id",
                str(subnet_id or self.config.subnet_id),
                "--role",
                self._role_variant(role),
                "--uid",
                str(uid),
            ],
        )
        try:
            return float(json.loads(raw)) / self.config.token_amount_scale
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0.0

    def reward_reserve(self, subnet_id: Optional[int] = None) -> float:
        raw = self.invoke_contract(
            "reward_reserve",
            ["--subnet_id", str(subnet_id or self.config.subnet_id)],
        )
        try:
            return float(json.loads(raw)) / self.config.token_amount_scale
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0.0

    def fund_rewards(self, from_account: str, amount: float, source_account: Optional[str] = None, subnet_id: Optional[int] = None) -> str:
        return self.invoke_contract(
            "fund_rewards",
            [
                "--subnet_id",
                str(subnet_id or self.config.subnet_id),
                "--from",
                from_account,
                "--amount",
                self._amount_to_contract_units(amount),
            ],
            source_account=source_account,
        )

    def claim_rewards(self, uid: str, role: str, source_account: Optional[str] = None, subnet_id: Optional[int] = None) -> str:
        return self.invoke_contract(
            "claim_rewards",
            [
                "--subnet_id",
                str(subnet_id or self.config.subnet_id),
                "--role",
                self._role_variant(role),
                "--uid",
                str(uid),
            ],
            source_account=source_account,
        )

    def _subnet_function(self, default_function: str, subnet_function: str) -> str:
        return default_function if self.config.subnet_id == 1 else subnet_function

    def _subnet_args(self) -> List[str]:
        return [] if self.config.subnet_id == 1 else ["--subnet_id", str(self.config.subnet_id)]

    @staticmethod
    def _json_string(value: str) -> str:
        return json.dumps(value)

    @staticmethod
    def _score_to_scaled(score: float) -> str:
        scale = 1_000_000
        bounded = max(0.0, min(1.0, float(score)))
        return str(int(round(bounded * scale)))

    def _amount_to_contract_units(self, amount: float) -> str:
        if amount <= 0:
            raise ValueError("Amount must be positive.")
        return str(int(round(amount * self.config.token_amount_scale)))

    def _amount_from_raw(self, raw: str) -> float:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw
        try:
            return float(data) / self.config.token_amount_scale
        except (TypeError, ValueError):
            return 0.0

    def _contract_update(self, update: MetagraphUpdate) -> Dict[str, Any]:
        return {
            "uid": int(update.uid),
            "role": self._role_variant(update.role),
            "performance_scaled": self._score_to_scaled(update.performance),
            "trust_scaled": self._score_to_scaled(update.trust),
            "history_hash": update.history_hash,
        }

    @staticmethod
    def _role_variant(role: str) -> str:
        normalized = role.strip().lower()
        if normalized == "miner":
            return "Miner"
        if normalized == "validator":
            return "Validator"
        raise ValueError("Role must be miner or validator.")

    def _source(self, source_account: Optional[str]) -> str:
        source = source_account or self.config.source_account
        if not source:
            raise RuntimeError("A Stellar source account secret or CLI identity is required.")
        return source

    def _contract_id(self) -> str:
        if not self.config.metagraph_contract_id:
            raise RuntimeError("STELLAR_METAGRAPH_CONTRACT_ID is required.")
        return self.config.metagraph_contract_id

    def _run_stellar_cli(self, args: List[str]) -> str:
        try:
            result = subprocess.run(
                [self.config.stellar_cli_bin, *args],
                check=True,
                text=True,
                capture_output=True,
                timeout=max(self.timeout, 30.0),
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Stellar CLI is required for Soroban contract operations.") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip()
            raise RuntimeError(f"Stellar CLI failed: {detail}") from exc
        return result.stdout

    def _parse_participant(self, raw: str, role: str) -> Optional[MetagraphParticipant]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if data in (None, "null"):
            return None
        return self._participant_from_mapping(data, role)

    def _parse_cycle_commit(self, raw: str) -> Optional[ChainCycleCommit]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return ChainCycleCommit(
            cycle=int(data.get("cycle", 0)),
            score_root=str(data.get("score_root", "")),
            updates_hash=str(data.get("updates_hash", "")),
            quorum_weight=float(data.get("quorum_weight", 0)) / 1_000_000,
            committed_at_ledger=int(data.get("committed_at_ledger", 0)),
            subnet_id=int(data.get("subnet_id", 1)),
            distributed_rewards=float(data.get("distributed_rewards", 0)) / self.config.token_amount_scale,
        )

    def _parse_unbond_request(self, raw: str) -> Optional[UnbondRequest]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if data in (None, "null") or not isinstance(data, dict):
            return None
        try:
            amount = float(data.get("amount", 0)) / self.config.token_amount_scale
            return UnbondRequest(
                amount=amount,
                requested_ledger=int(data.get("requested_ledger", 0)),
                unlock_ledger=int(data.get("unlock_ledger", 0)),
                subnet_id=self.config.subnet_id,
            )
        except (TypeError, ValueError):
            return None

    def _parse_subnet(self, raw: str) -> Optional[SubnetConfig]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return SubnetConfig(
            subnet_id=int(data.get("subnet_id", 0)),
            owner=str(data.get("owner", "")),
            commit_authority=str(data.get("commit_authority", "")),
            stake_token=str(data.get("stake_token", "")),
            treasury=str(data.get("treasury", "")),
            emission_per_cycle=float(data.get("emission_per_cycle", 0)) / self.config.token_amount_scale,
            miner_emission_bps=int(data.get("miner_emission_bps", 0)),
            validator_emission_bps=int(data.get("validator_emission_bps", 0)),
            max_miners=int(data.get("max_miners", 0)),
            max_validators=int(data.get("max_validators", 0)),
            min_miner_stake=float(data.get("min_miner_stake", 0)) / self.config.token_amount_scale,
            min_validator_stake=float(data.get("min_validator_stake", 0)) / self.config.token_amount_scale,
            registration_fee=float(data.get("registration_fee", 0)) / self.config.token_amount_scale,
            status=int(data.get("status", 0)),
            created_ledger=int(data.get("created_ledger", 0)),
        )

    def _participant_from_mapping(self, data: Any, role: str) -> Optional[MetagraphParticipant]:
        if not isinstance(data, dict):
            return None
        owner = data.get("owner") or data.get("public_key") or data.get("address")
        endpoint = data.get("endpoint") or data.get("api_endpoint")
        uid = data.get("uid")
        if owner is None or endpoint is None or uid is None:
            return None
        return MetagraphParticipant(
            uid=str(uid),
            role=role,
            public_key=str(owner),
            api_endpoint=str(endpoint),
            stake=float(data.get("stake_amount", data.get("stake", 0))) / self.config.token_amount_scale,
            trust_score=float(data.get("trust_scaled", data.get("trust_score", 0))) / 1_000_000,
            performance=float(data.get("performance_scaled", data.get("performance", 0))) / 1_000_000,
            status=int(data.get("status", 1)),
            cycle=int(data.get("cycle", 0)),
            history_hash=str(data.get("history_hash", "")),
            reward_balance=float(data.get("reward_balance", 0)) / self.config.token_amount_scale,
        )
