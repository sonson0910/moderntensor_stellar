"""Shared pytest fixtures for the Stellar runtime."""

import pytest


@pytest.fixture()
def sample_password() -> str:
    return "correct horse battery staple"
