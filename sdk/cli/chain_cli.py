"""Chain inspection commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sdk.chain.stellar import StellarChainClient, build_stellar_testnet_config
from sdk.config.settings import settings


console = Console()


def _client() -> StellarChainClient:
    return StellarChainClient(build_stellar_testnet_config(settings), timeout=settings.HTTP_TIMEOUT_SECONDS)


@click.group()
def chain_cli():
    """Inspect Stellar Testnet accounts and ledgers."""


@chain_cli.command("ledger")
def ledger_cmd():
    ledger = _client().current_ledger()
    console.print(Panel(f"[bold green]{ledger}[/bold green]", title="Latest Ledger"))


@chain_cli.command("account")
@click.argument("public_key")
def account_cmd(public_key):
    account = _client().get_account(public_key)
    table = Table(title="Account")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("public_key", public_key)
    table.add_row("sequence", str(account.get("sequence", "")))
    for balance in account.get("balances", []):
        table.add_row(str(balance.get("asset_type", "asset")), str(balance.get("balance", "")))
    console.print(table)


@chain_cli.command("fund")
@click.argument("public_key")
def fund_cmd(public_key):
    result = _client().fund_test_account(public_key)
    console.print(Panel(str(result.get("hash", "funded")), title="Friendbot"))


@chain_cli.command("health")
def health_cmd():
    client = _client()
    table = Table(title="Stellar Testnet Health")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green")
    table.add_row("network", settings.STELLAR_NETWORK)
    table.add_row("horizon", settings.STELLAR_HORIZON_URL)
    table.add_row("latest_ledger", str(client.current_ledger()))
    table.add_row("contract", settings.STELLAR_METAGRAPH_CONTRACT_ID or "not configured")
    console.print(table)
