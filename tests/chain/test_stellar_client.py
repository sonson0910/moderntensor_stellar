import pytest

from sdk.chain.base import MetagraphParticipant, MetagraphUpdate, StellarNetworkConfig
from sdk.chain.stellar import StellarChainClient


@pytest.fixture()
def config():
    pytest.importorskip("stellar_sdk")
    return StellarNetworkConfig(
        network_name="stellar-testnet",
        network_passphrase="Test SDF Network ; September 2015",
        horizon_url="https://horizon-testnet.stellar.org",
        soroban_rpc_url="https://soroban-testnet.stellar.org",
        friendbot_url="https://friendbot.stellar.org",
        metagraph_contract_id="C" + "A" * 55,
        source_account="source",
    )


def test_register_participant_uses_named_contract_arguments(config, monkeypatch):
    client = StellarChainClient(config)
    captured = {}

    def fake_run(args):
        captured["args"] = args
        return "txhash"

    monkeypatch.setattr(client, "_run_stellar_cli", fake_run)
    tx = client.register_participant(
        MetagraphParticipant(
            uid="7",
            role="miner",
            public_key="G" + "A" * 55,
            api_endpoint="http://127.0.0.1:8000",
            stake=100,
        ),
        source_account="owner",
    )

    assert tx == "txhash"
    assert captured["args"][captured["args"].index("--source-account") + 1] == "owner"
    assert captured["args"][-9:] == [
        "register_miner",
        "--uid",
        "7",
        "--owner",
        "G" + "A" * 55,
        "--endpoint",
        '"http://127.0.0.1:8000"',
        "--stake_amount",
        "1000000000",
    ]


def test_query_participant_parses_scaled_scores(config, monkeypatch):
    client = StellarChainClient(config)
    monkeypatch.setattr(
        client,
        "_run_stellar_cli",
        lambda args: '{"uid": 8, "owner": "GKEY", "endpoint": "http://m", "stake_amount": 5, "trust_scaled": 700000, "performance_scaled": 900000, "status": 1, "cycle": 12}',
    )

    participant = client.query_participant("8", "validator")

    assert participant is not None
    assert participant.role == "validator"
    assert participant.uid == "8"
    assert participant.stake == 0.0000005
    assert participant.trust_score == 0.7
    assert participant.performance == 0.9


def test_active_participants_uses_pagination_arguments(config, monkeypatch):
    client = StellarChainClient(config)
    captured = {}
    monkeypatch.setattr(client, "_run_stellar_cli", lambda args: captured.setdefault("args", args) and "[]")

    assert client.active_participants("miner", cursor=25, limit=50) == []
    assert captured["args"][-7:] == [
        "active_participants",
        "--role",
        "Miner",
        "--cursor",
        "25",
        "--limit",
        "50",
    ]


def test_commit_cycle_serializes_quorum_batch(config, monkeypatch):
    client = StellarChainClient(config)
    captured = {}

    def fake_run(args):
        captured["args"] = args
        return '{"cycle": 9, "score_root": "root", "updates_hash": "hash", "quorum_weight": 2000000, "committed_at_ledger": 123}'

    monkeypatch.setattr(client, "_run_stellar_cli", fake_run)
    commit = client.commit_cycle(
        cycle=9,
        updates=[
            MetagraphUpdate(
                uid="1",
                role="miner",
                performance=0.9,
                trust=0.8,
                history_hash="history",
                cycle=9,
            )
        ],
        quorum_validators=["10", "11"],
        score_root="root",
        updates_hash="hash",
    )

    assert commit.cycle == 9
    assert commit.quorum_weight == 2.0
    assert "commit_cycle" in captured["args"]
    update_index = captured["args"].index("--updates") + 1
    quorum_index = captured["args"].index("--quorum_validators") + 1
    assert captured["args"][captured["args"].index("--score_root") + 1] == '"root"'
    assert captured["args"][captured["args"].index("--updates_hash") + 1] == '"hash"'
    assert captured["args"][update_index] == (
        '[{"uid":1,"role":"Miner","performance_scaled":"900000",'
        '"trust_scaled":"800000","history_hash":"history"}]'
    )
    assert captured["args"][quorum_index] == "[10,11]"


def test_friendbot_funds_expected_address(config, monkeypatch):
    client = StellarChainClient(config)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"successful": True}

    def fake_get(url, params, timeout):
        captured.update({"url": url, "params": params, "timeout": timeout})
        return Response()

    monkeypatch.setattr("requests.get", fake_get)

    assert client.fund_test_account("GTEST") == {"successful": True}
    assert captured["url"] == "https://friendbot.stellar.org"
    assert captured["params"] == {"addr": "GTEST"}


def test_subnet_specific_query_uses_subnet_contract_methods(config, monkeypatch):
    config = StellarNetworkConfig(
        **{**config.__dict__, "subnet_id": 2},
    )
    client = StellarChainClient(config)
    captured = {}
    monkeypatch.setattr(client, "_run_stellar_cli", lambda args: captured.setdefault("args", args) and "[]")

    assert client.active_participants("validator", cursor=0, limit=25) == []
    assert captured["args"][-9:] == [
        "active_participants_for_subnet",
        "--subnet_id",
        "2",
        "--role",
        "Validator",
        "--cursor",
        "0",
        "--limit",
        "25",
    ]


def test_reward_balance_parses_scaled_amount(config, monkeypatch):
    client = StellarChainClient(config)
    monkeypatch.setattr(client, "_run_stellar_cli", lambda args: '"2500000"')

    assert client.reward_balance("1", "miner") == 0.25


def test_unbond_request_serializes_amount_and_parses_cooldown(config, monkeypatch):
    client = StellarChainClient(config)
    captured = {}

    def fake_run(args):
        captured["args"] = args
        return '{"amount":"12500000","requested_ledger":100,"unlock_ledger":110}'

    monkeypatch.setattr(client, "_run_stellar_cli", fake_run)

    request = client.request_unbond("1", "miner", 1.25, source_account="owner")

    assert request.amount == 1.25
    assert request.requested_ledger == 100
    assert request.unlock_ledger == 110
    assert captured["args"][-7:] == [
        "request_unbond",
        "--uid",
        "1",
        "--role",
        "Miner",
        "--amount",
        "12500000",
    ]
    assert captured["args"][captured["args"].index("--source-account") + 1] == "owner"


def test_get_unbond_request_uses_subnet_variant(config, monkeypatch):
    config = StellarNetworkConfig(
        **{**config.__dict__, "subnet_id": 9},
    )
    client = StellarChainClient(config)
    captured = {}

    def fake_run(args):
        captured["args"] = args
        return '{"amount": "5000000", "requested_ledger": 200, "unlock_ledger": 210}'

    monkeypatch.setattr(client, "_run_stellar_cli", fake_run)

    request = client.get_unbond_request("2", "validator")

    assert request is not None
    assert request.amount == 0.5
    assert captured["args"][-7:] == [
        "get_unbond_request_for_subnet",
        "--subnet_id",
        "9",
        "--uid",
        "2",
        "--role",
        "Validator",
    ]


def test_withdraw_unbonded_and_slash_stake_parse_scaled_amounts(config, monkeypatch):
    client = StellarChainClient(config)
    calls = []

    def fake_run(args):
        calls.append(args)
        return '"2500000"'

    monkeypatch.setattr(client, "_run_stellar_cli", fake_run)

    assert client.withdraw_unbonded("1", "miner", source_account="owner") == 0.25
    assert client.slash_stake("1", "miner", "GAUTH", 0.25, source_account="owner") == 0.25
    assert calls[0][-5:] == ["withdraw_unbonded", "--uid", "1", "--role", "Miner"]
    assert calls[1][-9:] == [
        "slash_stake",
        "--uid",
        "1",
        "--role",
        "Miner",
        "--authority",
        "GAUTH",
        "--amount",
        "2500000",
    ]


def test_subnet_status_commands_use_subnet_owner_source(config, monkeypatch):
    client = StellarChainClient(config)
    captured = []
    monkeypatch.setattr(client, "_run_stellar_cli", lambda args: captured.append(args) or "txhash")

    assert client.set_subnet_status(0, subnet_id=3, source_account="owner") == "txhash"
    assert client.pause_subnet(subnet_id=3, source_account="owner") == "txhash"
    assert client.resume_subnet(subnet_id=3, source_account="owner") == "txhash"

    assert captured[0][-5:] == ["set_subnet_status", "--subnet_id", "3", "--status", "0"]
    assert captured[1][-3:] == ["pause_subnet", "--subnet_id", "3"]
    assert captured[2][-3:] == ["resume_subnet", "--subnet_id", "3"]


def test_update_subnet_tokenomics_serializes_scaled_emission(config, monkeypatch):
    client = StellarChainClient(config)
    captured = {}
    monkeypatch.setattr(client, "_run_stellar_cli", lambda args: captured.setdefault("args", args) and "txhash")

    assert client.update_subnet_tokenomics(1.5, 8000, 2000, subnet_id=4, source_account="admin") == "txhash"

    assert captured["args"][-9:] == [
        "update_subnet_tokenomics",
        "--subnet_id",
        "4",
        "--emission_per_cycle",
        "15000000",
        "--miner_emission_bps",
        "8000",
        "--validator_emission_bps",
        "2000",
    ]
    assert captured["args"][captured["args"].index("--source-account") + 1] == "admin"


def test_update_subnet_registration_serializes_caps_stakes_and_fee(config, monkeypatch):
    client = StellarChainClient(config)
    captured = {}
    monkeypatch.setattr(client, "_run_stellar_cli", lambda args: captured.setdefault("args", args) and "txhash")

    assert client.update_subnet_registration(100, 25, 2.0, 10.0, 0.1, subnet_id=4, source_account="admin") == "txhash"

    assert captured["args"][-13:] == [
        "update_subnet_registration",
        "--subnet_id",
        "4",
        "--max_miners",
        "100",
        "--max_validators",
        "25",
        "--min_miner_stake",
        "20000000",
        "--min_validator_stake",
        "100000000",
        "--registration_fee",
        "1000000",
    ]


def test_get_subnet_parses_registration_policy(config, monkeypatch):
    client = StellarChainClient(config)
    monkeypatch.setattr(
        client,
        "_run_stellar_cli",
        lambda args: (
            '{"subnet_id":1,"owner":"GOWNER","commit_authority":"GOWNER","stake_token":"CTOKEN",'
            '"treasury":"GTREASURY","emission_per_cycle":"10000000","miner_emission_bps":8000,'
            '"validator_emission_bps":2000,"max_miners":100,"max_validators":25,'
            '"min_miner_stake":"20000000","min_validator_stake":"100000000",'
            '"registration_fee":"1000000","status":1,"created_ledger":7}'
        ),
    )

    subnet = client.get_subnet()

    assert subnet is not None
    assert subnet.max_miners == 100
    assert subnet.max_validators == 25
    assert subnet.min_miner_stake == 2.0
    assert subnet.min_validator_stake == 10.0
    assert subnet.registration_fee == 0.1
