"""Production settings for the Stellar Testnet runtime."""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        env_prefix="MODERNTENSOR_",
        populate_by_name=True,
    )

    CHAIN_BACKEND: str = Field(default="stellar", alias="CHAIN_BACKEND")
    STELLAR_NETWORK: str = Field(default="stellar-testnet", alias="STELLAR_NETWORK")
    STELLAR_NETWORK_PASSPHRASE: str = Field(
        default="Test SDF Network ; September 2015",
        alias="STELLAR_NETWORK_PASSPHRASE",
    )
    STELLAR_HORIZON_URL: str = Field(
        default="https://horizon-testnet.stellar.org",
        alias="STELLAR_HORIZON_URL",
    )
    STELLAR_RPC_URL: str = Field(
        default="https://soroban-testnet.stellar.org",
        alias="STELLAR_RPC_URL",
    )
    STELLAR_FRIENDBOT_URL: str = Field(
        default="https://friendbot.stellar.org",
        alias="STELLAR_FRIENDBOT_URL",
    )
    STELLAR_METAGRAPH_CONTRACT_ID: Optional[str] = Field(
        default=None,
        alias="STELLAR_METAGRAPH_CONTRACT_ID",
    )
    STELLAR_CLI_BIN: str = Field(default="stellar", alias="STELLAR_CLI_BIN")
    SUBNET_ID: int = Field(default=1, alias="SUBNET_ID")
    ALLOW_STELLAR_PUBLIC_NETWORK: bool = Field(
        default=False,
        alias="ALLOW_STELLAR_PUBLIC_NETWORK",
    )

    HOTKEY_BASE_DIR: str = Field(default="moderntensor", alias="HOTKEY_BASE_DIR")
    COLDKEY_NAME: str = Field(default="default", alias="COLDKEY_NAME")
    HOTKEY_NAME: str = Field(default="validator", alias="HOTKEY_NAME")
    MINER_STELLAR_SECRET: Optional[str] = Field(default=None, alias="MINER_STELLAR_SECRET")
    VALIDATOR_STELLAR_SECRET: Optional[str] = Field(default=None, alias="VALIDATOR_STELLAR_SECRET")
    VALIDATOR_STELLAR_PUBLIC_KEY: Optional[str] = Field(default=None, alias="VALIDATOR_STELLAR_PUBLIC_KEY")
    VALIDATOR_UID: Optional[str] = Field(default=None, alias="VALIDATOR_UID")
    VALIDATOR_ADDRESS: Optional[str] = Field(default=None, alias="VALIDATOR_ADDRESS")
    VALIDATOR_API_ENDPOINT: Optional[str] = Field(default=None, alias="VALIDATOR_API_ENDPOINT")
    API_PORT: int = Field(default=8001, alias="API_PORT")

    REQUIRE_SIGNED_PAYLOADS: bool = Field(default=True, alias="REQUIRE_SIGNED_PAYLOADS")
    REQUIRE_SIGNED_MINER_RESULTS: bool = Field(default=True, alias="REQUIRE_SIGNED_MINER_RESULTS")
    REQUIRE_SIGNED_VALIDATOR_SCORES: bool = Field(default=True, alias="REQUIRE_SIGNED_VALIDATOR_SCORES")
    API_MAX_REQUEST_BYTES: int = Field(default=1_000_000, alias="API_MAX_REQUEST_BYTES")
    API_TASK_QUEUE_SIZE: int = Field(default=64, alias="API_TASK_QUEUE_SIZE")
    API_RATE_LIMIT_PER_MINUTE: int = Field(default=120, alias="API_RATE_LIMIT_PER_MINUTE")
    HTTP_TIMEOUT_SECONDS: float = Field(default=15.0, alias="HTTP_TIMEOUT_SECONDS")

    CONSENSUS_CYCLE_LEDGER_LENGTH: int = Field(default=120, alias="CONSENSUS_CYCLE_LEDGER_LENGTH")
    CONSENSUS_NETWORK_TIMEOUT_SECONDS: int = Field(default=10, alias="CONSENSUS_NETWORK_TIMEOUT_SECONDS")
    CONSENSUS_MINI_BATCH_WAIT_SECONDS: int = Field(default=30, alias="CONSENSUS_MINI_BATCH_WAIT_SECONDS")
    CONSENSUS_NUM_MINERS_TO_SELECT: int = Field(default=5, alias="CONSENSUS_NUM_MINERS_TO_SELECT")
    CONSENSUS_QUORUM_RATIO: float = Field(default=2 / 3, alias="CONSENSUS_QUORUM_RATIO")
    CONSENSUS_TRUST_EMA_ALPHA: float = Field(default=0.2, alias="CONSENSUS_TRUST_EMA_ALPHA")
    CONSENSUS_STATE_RETENTION_CYCLES: int = Field(default=3, alias="CONSENSUS_STATE_RETENTION_CYCLES")
    CONSENSUS_MAX_PERFORMANCE_HISTORY_LEN: int = Field(
        default=100,
        alias="CONSENSUS_MAX_PERFORMANCE_HISTORY_LEN",
    )
    METAGRAPH_SCORE_SCALE: int = Field(default=1_000_000, alias="METAGRAPH_SCORE_SCALE")
    STELLAR_TOKEN_AMOUNT_SCALE: int = Field(default=10_000_000, alias="STELLAR_TOKEN_AMOUNT_SCALE")

    MODEL_ALLOWLIST: str = Field(default="segmind/tiny-sd", alias="MODEL_ALLOWLIST")
    MODEL_USE_SAFETENSORS: bool = Field(default=True, alias="MODEL_USE_SAFETENSORS")
    MODEL_TRUST_REMOTE_CODE: bool = Field(default=False, alias="MODEL_TRUST_REMOTE_CODE")
    MODEL_MAX_RESULT_BYTES: int = Field(default=2_000_000, alias="MODEL_MAX_RESULT_BYTES")

    LOG_LEVEL: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("CHAIN_BACKEND")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized != "stellar":
            raise ValueError("Only the Stellar backend is supported.")
        return normalized

    @field_validator("STELLAR_NETWORK")
    @classmethod
    def validate_network(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized != "stellar-testnet":
            raise ValueError("Only stellar-testnet is enabled by default.")
        return normalized

    def require_validator_secret(self) -> str:
        if not self.VALIDATOR_STELLAR_SECRET:
            raise RuntimeError("VALIDATOR_STELLAR_SECRET is required for validator runtime.")
        return self.VALIDATOR_STELLAR_SECRET

    def require_miner_secret(self) -> str:
        if not self.MINER_STELLAR_SECRET:
            raise RuntimeError("MINER_STELLAR_SECRET is required for miner runtime.")
        return self.MINER_STELLAR_SECRET

    def require_contract_id(self) -> str:
        if not self.STELLAR_METAGRAPH_CONTRACT_ID:
            raise RuntimeError("STELLAR_METAGRAPH_CONTRACT_ID is required for metagraph operations.")
        return self.STELLAR_METAGRAPH_CONTRACT_ID


settings = Settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("moderntensor")
