#!/usr/bin/env python3
"""Bootstrap ModernTensor accounts on the official Stellar Testnet."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sdk.chain.stellar import StellarChainClient, build_stellar_testnet_config
from sdk.config.settings import settings


def _account_dict(label: str, account):
    return {
        "label": label,
        "public_key": account.public_key,
        "secret_env": f"{label.upper()}_STELLAR_SECRET",
        "secret": account.secret,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate-accounts", action="store_true")
    parser.add_argument("--fund", action="store_true", help="Fund generated accounts with Friendbot")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    config = build_stellar_testnet_config(settings)
    client = StellarChainClient(config)
    result = {
        "network": config.network_name,
        "horizon_url": config.horizon_url,
        "soroban_rpc_url": config.soroban_rpc_url,
        "friendbot_url": config.friendbot_url,
        "accounts": [],
        "contract_id": config.metagraph_contract_id,
    }

    if args.generate_accounts:
        for label in ("validator", "miner"):
            account = client.generate_account()
            info = _account_dict(label, account)
            if args.fund:
                client.fund_test_account(account.public_key)
                info["funded"] = True
            result["accounts"].append(info)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"Network: {result['network']}")
    print(f"Horizon: {result['horizon_url']}")
    print(f"Soroban RPC: {result['soroban_rpc_url']}")
    if result["contract_id"]:
        print(f"Metagraph contract: {result['contract_id']}")
    else:
        print("Metagraph contract: not configured")

    for account in result["accounts"]:
        print()
        print(f"{account['label'].title()} public key: {account['public_key']}")
        print(f"Set {account['secret_env']} to the generated secret seed.")
        if os.getenv("PRINT_STELLAR_SECRETS") == "1":
            print(f"{account['secret_env']}={account['secret']}")
        else:
            print("Secret hidden. Set PRINT_STELLAR_SECRETS=1 for local bootstrap output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
