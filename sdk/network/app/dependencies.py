"""FastAPI dependency hooks for the active validator node."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from sdk.consensus.node import ValidatorNode


_validator_node_instance: Optional[ValidatorNode] = None


def set_validator_node_instance(node: Optional[ValidatorNode]) -> None:
    global _validator_node_instance
    _validator_node_instance = node


def get_optional_validator_node() -> Optional[ValidatorNode]:
    return _validator_node_instance


def get_validator_node() -> ValidatorNode:
    if _validator_node_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Validator node is not initialized.",
        )
    return _validator_node_instance
