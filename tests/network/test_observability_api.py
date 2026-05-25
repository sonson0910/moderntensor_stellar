from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sdk.core.datatypes import STATUS_ACTIVE, STATUS_INACTIVE
from sdk.network.app.dependencies import set_validator_node_instance
from sdk.network.app.main import _rate_buckets, app


class FakeValidatorNode:
    def __init__(self):
        self.info = SimpleNamespace(uid="validator-1")
        self.current_cycle = 42
        self.miners_info = {
            "miner-1": SimpleNamespace(status=STATUS_ACTIVE),
            "miner-2": SimpleNamespace(status=STATUS_INACTIVE),
        }
        self.validators_info = {
            "validator-1": SimpleNamespace(status=STATUS_ACTIVE),
            "validator-2": SimpleNamespace(status=STATUS_ACTIVE),
        }
        self.tasks_sent = {"task-1": object(), "task-2": object()}
        self.results_buffer = {"task-1": object()}
        self.received_validator_scores = {
            42: {
                "task-1": {"validator-1": object(), "validator-2": object()},
            },
        }
        self.metrics = {
            "tasks_sent_total": 7,
            "miner_results_accepted_total": 3,
            "validator_score_votes_accepted_total": 2,
            "commit_failures": 1,
        }
        self.settings = SimpleNamespace(API_TASK_QUEUE_SIZE=4)


@pytest.fixture(autouse=True)
def reset_validator_node():
    set_validator_node_instance(None)
    _rate_buckets.clear()
    yield
    set_validator_node_instance(None)
    _rate_buckets.clear()


def test_health_is_available_without_validator_node():
    client = TestClient(app)
    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["node_initialized"] is False


def test_readiness_requires_validator_node():
    client = TestClient(app)
    response = client.get("/v1/readiness")

    assert response.status_code == 503
    assert response.json()["detail"] == "Validator node is not initialized."


def test_readiness_reports_fake_validator_node():
    set_validator_node_instance(FakeValidatorNode())

    client = TestClient(app)
    response = client.get("/v1/readiness")

    assert response.status_code == 200
    assert response.json() == {
        "ready": True,
        "cycle": 42,
        "validator_uid": "validator-1",
    }


def test_metrics_json_uses_validator_state_without_network():
    set_validator_node_instance(FakeValidatorNode())

    client = TestClient(app)
    response = client.get("/v1/metrics?format=json")

    assert response.status_code == 200
    body = response.json()
    assert body["cycle"] == 42
    assert body["peers"] == {
        "miners_total": 2,
        "miners_active": 1,
        "validators_total": 2,
        "validators_active": 2,
    }
    assert body["queues"] == {
        "capacity": 4,
        "task_depth": 2,
        "result_depth": 1,
        "saturation": 0.5,
        "saturated": False,
    }
    assert body["buffers"]["votes_buffered"] == 2
    assert body["counters"]["tasks_sent_total"] == 7
    assert body["counters"]["commit_failures"] == 1


def test_metrics_prometheus_exposes_core_observability_fields():
    set_validator_node_instance(FakeValidatorNode())

    client = TestClient(app)
    response = client.get("/v1/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert "moderntensor_validator_cycle 42" in text
    assert 'moderntensor_validator_peers{role="miner",state="active"} 1' in text
    assert "moderntensor_validator_queue_saturation 0.5" in text
    assert "moderntensor_validator_commit_failures 1" in text
