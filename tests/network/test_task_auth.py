import datetime as dt

import pytest
from fastapi.testclient import TestClient

from sdk.config.settings import settings
from sdk.network.server import BaseMiner, TaskModel, sign_task_model


class NoopMiner(BaseMiner):
    def handle_task(self, task):
        return None


def _signed_task(secret: str) -> TaskModel:
    deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
    task = TaskModel(
        task_id="task-1",
        description="draw a comet",
        deadline=deadline.isoformat(),
        priority=1,
        task_data={"miner_uid": "miner-1"},
        cycle=1,
    )
    return sign_task_model(task, secret_seed=secret, validator_uid="validator-1", cycle=1)


def test_miner_rejects_duplicate_task(monkeypatch):
    stellar_sdk = pytest.importorskip("stellar_sdk")
    keypair = stellar_sdk.Keypair.random()
    monkeypatch.setattr(settings, "VALIDATOR_STELLAR_PUBLIC_KEY", keypair.public_key)
    monkeypatch.setattr(settings, "VALIDATOR_ADDRESS", None)
    miner = NoopMiner(validator_url="http://validator", miner_uid="miner-1")
    client = TestClient(miner.app)
    payload = _signed_task(keypair.secret).model_dump(mode="json")

    assert client.post("/receive-task", json=payload).status_code == 200
    assert client.post("/receive-task", json=payload).status_code == 409


def test_miner_rejects_tampered_task_signature(monkeypatch):
    stellar_sdk = pytest.importorskip("stellar_sdk")
    keypair = stellar_sdk.Keypair.random()
    monkeypatch.setattr(settings, "VALIDATOR_STELLAR_PUBLIC_KEY", keypair.public_key)
    monkeypatch.setattr(settings, "VALIDATOR_ADDRESS", None)
    miner = NoopMiner(validator_url="http://validator", miner_uid="miner-1")
    client = TestClient(miner.app)
    payload = _signed_task(keypair.secret).model_dump(mode="json")
    payload["description"] = "tampered"

    assert client.post("/receive-task", json=payload).status_code == 401
