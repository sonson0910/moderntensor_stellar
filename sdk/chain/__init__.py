"""Chain-neutral interfaces and Stellar Testnet runtime helpers."""

from .base import (
    ChainAccount,
    ChainClient,
    ChainCycleCommit,
    MetagraphParticipant,
    MetagraphUpdate,
    StellarNetworkConfig,
)

__all__ = [
    "ChainAccount",
    "ChainClient",
    "ChainCycleCommit",
    "MetagraphParticipant",
    "MetagraphUpdate",
    "StellarChainClient",
    "StellarNetworkConfig",
    "build_stellar_testnet_config",
]


def __getattr__(name):
    if name in {"StellarChainClient", "build_stellar_testnet_config"}:
        from .stellar import StellarChainClient, build_stellar_testnet_config

        return {
            "StellarChainClient": StellarChainClient,
            "build_stellar_testnet_config": build_stellar_testnet_config,
        }[name]
    raise AttributeError(name)
