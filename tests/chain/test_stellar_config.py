from sdk.chain.stellar import build_stellar_testnet_config


class DummySettings:
    STELLAR_NETWORK = "stellar-testnet"
    STELLAR_NETWORK_PASSPHRASE = "Test SDF Network ; September 2015"
    STELLAR_HORIZON_URL = "https://horizon-testnet.stellar.org"
    STELLAR_RPC_URL = "https://soroban-testnet.stellar.org"
    STELLAR_FRIENDBOT_URL = "https://friendbot.stellar.org"
    STELLAR_METAGRAPH_CONTRACT_ID = None
    REQUIRE_SIGNED_PAYLOADS = True
    API_MAX_REQUEST_BYTES = 1_000_000
    API_TASK_QUEUE_SIZE = 64


def test_stellar_testnet_defaults():
    config = build_stellar_testnet_config(DummySettings())

    assert config.network_name == "stellar-testnet"
    assert config.network_passphrase == "Test SDF Network ; September 2015"
    assert config.horizon_url == "https://horizon-testnet.stellar.org"
    assert config.soroban_rpc_url == "https://soroban-testnet.stellar.org"
    assert config.friendbot_url == "https://friendbot.stellar.org"
    assert config.require_signed_payloads is True
