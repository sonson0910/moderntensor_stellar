"""Encrypted Stellar coldkey/hotkey storage."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from sdk.chain.stellar import StellarChainClient


class WalletManager:
    def __init__(self, base_dir: str = "moderntensor", iterations: int = 390_000):
        self.base_dir = Path(base_dir)
        self.iterations = iterations
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_coldkey(self, name: str, password: str, force: bool = False) -> Path:
        coldkey_dir = self._coldkey_dir(name)
        if coldkey_dir.exists() and not force:
            raise FileExistsError(f"Coldkey '{name}' already exists.")
        coldkey_dir.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        (coldkey_dir / "salt.bin").write_bytes(salt)
        verifier = self._password_verifier(password, salt)
        self._write_json(
            coldkey_dir / "coldkey.json",
            {
                "name": name,
                "created_at": int(time.time()),
                "verifier": verifier,
                "version": 1,
            },
        )
        self._write_json(coldkey_dir / "hotkeys.json", {})
        return coldkey_dir

    def import_hotkey(
        self,
        coldkey: str,
        hotkey_name: str,
        secret_seed: str,
        password: str,
        overwrite: bool = False,
    ) -> Dict[str, str]:
        self._ensure_coldkey(coldkey)
        public_key = StellarChainClient.public_key_from_secret(secret_seed)
        hotkeys = self._load_hotkeys(coldkey)
        if hotkey_name in hotkeys and not overwrite:
            raise FileExistsError(f"Hotkey '{hotkey_name}' already exists.")
        token = self._fernet(coldkey, password).encrypt(secret_seed.encode("utf-8")).decode("utf-8")
        hotkeys[hotkey_name] = {
            "name": hotkey_name,
            "public_key": public_key,
            "encrypted_secret": token,
            "created_at": int(time.time()),
            "version": 1,
        }
        self._save_hotkeys(coldkey, hotkeys)
        return {"name": hotkey_name, "public_key": public_key}

    def generate_hotkey(self, coldkey: str, hotkey_name: str, password: str, overwrite: bool = False) -> Dict[str, str]:
        account = StellarChainClient.generate_account()
        if not account.secret:
            raise RuntimeError("Generated account did not include a secret seed.")
        return self.import_hotkey(coldkey, hotkey_name, account.secret, password, overwrite=overwrite)

    def decrypt_hotkey_secret(self, coldkey: str, hotkey_name: str, password: str) -> str:
        hotkeys = self._load_hotkeys(coldkey)
        if hotkey_name not in hotkeys:
            raise KeyError(f"Hotkey '{hotkey_name}' not found.")
        token = hotkeys[hotkey_name]["encrypted_secret"].encode("utf-8")
        return self._fernet(coldkey, password).decrypt(token).decode("utf-8")

    def show_hotkey(self, coldkey: str, hotkey_name: str) -> Dict[str, str]:
        hotkeys = self._load_hotkeys(coldkey)
        if hotkey_name not in hotkeys:
            raise KeyError(f"Hotkey '{hotkey_name}' not found.")
        item = dict(hotkeys[hotkey_name])
        item.pop("encrypted_secret", None)
        return item

    def list_coldkeys(self) -> List[str]:
        return sorted(path.name for path in self.base_dir.iterdir() if path.is_dir() and (path / "coldkey.json").exists())

    def list_hotkeys(self, coldkey: str) -> List[Dict[str, str]]:
        hotkeys = self._load_hotkeys(coldkey)
        rows = []
        for name, item in sorted(hotkeys.items()):
            rows.append({"name": name, "public_key": item["public_key"], "created_at": str(item.get("created_at", ""))})
        return rows

    def _coldkey_dir(self, name: str) -> Path:
        safe_name = name.strip()
        if not safe_name or "/" in safe_name or "\\" in safe_name:
            raise ValueError("Invalid coldkey name.")
        return self.base_dir / safe_name

    def _ensure_coldkey(self, name: str) -> None:
        coldkey_dir = self._coldkey_dir(name)
        if not (coldkey_dir / "coldkey.json").exists():
            raise FileNotFoundError(f"Coldkey '{name}' not found.")

    def _load_hotkeys(self, coldkey: str) -> Dict[str, Dict[str, str]]:
        self._ensure_coldkey(coldkey)
        path = self._coldkey_dir(coldkey) / "hotkeys.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def _save_hotkeys(self, coldkey: str, hotkeys: Dict[str, Dict[str, str]]) -> None:
        self._write_json(self._coldkey_dir(coldkey) / "hotkeys.json", hotkeys)

    def _fernet(self, coldkey: str, password: str) -> Fernet:
        salt = (self._coldkey_dir(coldkey) / "salt.bin").read_bytes()
        expected = json.loads((self._coldkey_dir(coldkey) / "coldkey.json").read_text())["verifier"]
        if self._password_verifier(password, salt) != expected:
            raise PermissionError("Invalid coldkey password.")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.iterations,
        )
        return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8"))))

    @staticmethod
    def _password_verifier(password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000).hex()

    @staticmethod
    def _write_json(path: Path, value: Dict) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
