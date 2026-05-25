from sdk.chain.signing import (
    MINER_RESULT_DOMAIN,
    TASK_DOMAIN,
    miner_result_payload,
    sign_payload,
    validator_task_payload,
    verify_payload,
)


def test_stellar_signature_round_trip():
    pytest = __import__("pytest")
    stellar_sdk = pytest.importorskip("stellar_sdk")

    keypair = stellar_sdk.Keypair.random()
    payload = miner_result_payload("task-1", "miner-1", {"loss": 0.1})
    signed = sign_payload(keypair.secret, payload, MINER_RESULT_DOMAIN)

    assert signed["public_key"] == keypair.public_key
    assert verify_payload(keypair.public_key, payload, signed["signature"], MINER_RESULT_DOMAIN)
    assert not verify_payload(keypair.public_key, {**payload, "task_id": "task-2"}, signed["signature"], MINER_RESULT_DOMAIN)


def test_validator_task_signature_is_domain_separated():
    pytest = __import__("pytest")
    stellar_sdk = pytest.importorskip("stellar_sdk")

    keypair = stellar_sdk.Keypair.random()
    body = {"description": "draw a small moon", "priority": 1, "task_data": {"miner_uid": "miner-1"}}
    payload = validator_task_payload("task-1", 3, "2030-01-01T00:00:00+00:00", "miner-1", body)
    signed = sign_payload(keypair.secret, payload, TASK_DOMAIN)

    assert verify_payload(keypair.public_key, payload, signed["signature"], TASK_DOMAIN)
    assert not verify_payload(keypair.public_key, payload, signed["signature"], MINER_RESULT_DOMAIN)
