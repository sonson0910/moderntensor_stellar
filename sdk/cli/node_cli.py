"""Node runtime commands."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sdk.chain.stellar import StellarChainClient, build_stellar_testnet_config
from sdk.config.settings import settings
from sdk.consensus.node import ValidatorNode
from sdk.core.datatypes import ValidatorInfo

console = Console()


@click.group()
def node_cli():
    """Run ModernTensor validator and miner nodes."""


def _ensure_sibling_subnet_path() -> None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "subnet1",
        here.parents[3].parent / "subnet1",
    ]
    for sibling in candidates:
        if sibling.exists() and str(sibling) not in sys.path:
            sys.path.insert(0, str(sibling))
            return


def _load_subnet1_miner():
    _ensure_sibling_subnet_path()
    try:
        from subnet1.miner import Subnet1Miner
    except ImportError:
        try:
            from subnet1.subnet1.miner import Subnet1Miner
        except ImportError as exc:
            raise click.ClickException(
                "Subnet 1 package is not importable. Install it or run from the workspace root."
            ) from exc
    return Subnet1Miner


def _validator_class(subnet: str):
    if subnet != "subnet1":
        return ValidatorNode
    _ensure_sibling_subnet_path()
    try:
        from subnet1.validator import Subnet1Validator
    except ImportError:
        try:
            from subnet1.subnet1.validator import Subnet1Validator
        except ImportError as exc:
            raise click.ClickException(
                "Subnet 1 package is not importable. Install it or run from the workspace root."
            ) from exc
    return Subnet1Validator


@node_cli.command("run-validator")
@click.option("--uid", default=lambda: settings.VALIDATOR_UID or "validator")
@click.option("--public-key", default=lambda: settings.VALIDATOR_STELLAR_PUBLIC_KEY or settings.VALIDATOR_ADDRESS)
@click.option("--endpoint", default=lambda: settings.VALIDATOR_API_ENDPOINT)
@click.option("--subnet", default="subnet1", show_default=True)
def run_validator_cmd(uid, public_key, endpoint, subnet):
    secret = settings.require_validator_secret()
    resolved_public_key = public_key or StellarChainClient.public_key_from_secret(secret)
    info = ValidatorInfo(uid=uid, public_key=resolved_public_key, api_endpoint=endpoint)
    node = _validator_class(subnet)(
        validator_info=info,
        chain_client=StellarChainClient(build_stellar_testnet_config(settings)),
        stellar_secret=secret,
    )
    console.print(Panel(f"[green]{uid}[/green]\n{resolved_public_key}", title="Validator"))
    asyncio.run(node.run_forever())


@node_cli.command("run-cycle")
@click.option("--uid", default=lambda: settings.VALIDATOR_UID or "validator")
@click.option("--subnet", default="subnet1", show_default=True)
def run_cycle_cmd(uid, subnet):
    secret = settings.require_validator_secret()
    public_key = StellarChainClient.public_key_from_secret(secret)
    node = _validator_class(subnet)(
        validator_info=ValidatorInfo(uid=uid, public_key=public_key, api_endpoint=settings.VALIDATOR_API_ENDPOINT),
        chain_client=StellarChainClient(build_stellar_testnet_config(settings)),
        stellar_secret=secret,
    )
    asyncio.run(node.run_cycle())
    table = Table(title=f"Cycle {node.current_cycle} Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("selected_miners", str(len(node.tasks_sent)))
    table.add_row("results_buffered", str(len(node.results_buffer)))
    table.add_row("score_cycles", str(len(node.received_validator_scores)))
    for key, value in sorted(node.metrics.items()):
        table.add_row(key, str(value))
    console.print(table)
    console.print(Panel("[bold green]Cycle complete[/bold green]", title=uid))


@node_cli.command("run-miner")
@click.option("--validator-url", required=True)
@click.option("--uid", required=True)
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
@click.option("--model-id", default=None)
def run_miner_cmd(validator_url, uid, host, port, model_id):
    settings.require_miner_secret()
    Subnet1Miner = _load_subnet1_miner()
    Subnet1Miner(
        validator_url=validator_url,
        uid=uid,
        host=host,
        port=port,
        model_id=model_id,
    ).run()
