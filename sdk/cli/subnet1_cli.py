"""Subnet 1 convenience commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from sdk.chain.stellar import StellarChainClient, build_stellar_testnet_config
from sdk.config.settings import settings


console = Console()


@click.group()
def subnet1_cli():
    """Subnet 1 bootstrap and status helpers."""


@subnet1_cli.command("bootstrap")
def bootstrap_cmd():
    client = StellarChainClient(build_stellar_testnet_config(settings), timeout=settings.HTTP_TIMEOUT_SECONDS)
    validator = client.generate_account()
    miner = client.generate_account()
    client.fund_test_account(validator.public_key)
    client.fund_test_account(miner.public_key)
    console.print(
        Panel(
            "\n".join(
                [
                    f"VALIDATOR_PUBLIC_KEY={validator.public_key}",
                    "VALIDATOR_STELLAR_SECRET=<hidden>",
                    f"MINER_PUBLIC_KEY={miner.public_key}",
                    "MINER_STELLAR_SECRET=<hidden>",
                ]
            ),
            title="Subnet 1 Bootstrap",
        )
    )


@subnet1_cli.command("status")
def status_cmd():
    console.print(Panel(f"network={settings.STELLAR_NETWORK}\ncontract={settings.STELLAR_METAGRAPH_CONTRACT_ID or 'not configured'}", title="Subnet 1"))


@subnet1_cli.command("task-cycle")
def task_cycle_cmd():
    from .node_cli import run_cycle_cmd

    run_cycle_cmd.callback(settings.VALIDATOR_UID or "validator", "subnet1")
