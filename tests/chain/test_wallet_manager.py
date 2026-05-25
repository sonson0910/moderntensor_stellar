import json

import pytest

from sdk.keymanager.wallet_manager import WalletManager


def test_wallet_import_encrypts_secret(tmp_path, sample_password):
    stellar_sdk = pytest.importorskip("stellar_sdk")
    keypair = stellar_sdk.Keypair.random()
    manager = WalletManager(base_dir=str(tmp_path), iterations=1_000)

    manager.create_coldkey("operator", sample_password)
    info = manager.import_hotkey("operator", "validator", keypair.secret, sample_password)

    assert info["public_key"] == keypair.public_key
    hotkeys_raw = json.loads((tmp_path / "operator" / "hotkeys.json").read_text())
    assert keypair.secret not in json.dumps(hotkeys_raw)
    assert manager.decrypt_hotkey_secret("operator", "validator", sample_password) == keypair.secret
    assert manager.show_hotkey("operator", "validator")["public_key"] == keypair.public_key


def test_wallet_rejects_wrong_password(tmp_path, sample_password):
    stellar_sdk = pytest.importorskip("stellar_sdk")
    keypair = stellar_sdk.Keypair.random()
    manager = WalletManager(base_dir=str(tmp_path), iterations=1_000)

    manager.create_coldkey("operator", sample_password)
    manager.import_hotkey("operator", "miner", keypair.secret, sample_password)

    with pytest.raises(PermissionError):
        manager.decrypt_hotkey_secret("operator", "miner", "wrong-password")
