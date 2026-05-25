"""ModernTensor CLI with the original Rich visual style and Stellar runtime."""

from __future__ import annotations

import importlib.metadata
import logging

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .chain_cli import chain_cli
from .metagraph_cli import metagraph_cli
from .node_cli import node_cli
from .subnet1_cli import subnet1_cli
from .wallet_cli import wallet_cli

logging.basicConfig(level=logging.INFO)

ASCII_ART = r"""
 __  __           _                _____
|  \/  | ___   __| | ___ _ __ _ _|_   _|__ _ __  ___  ___  _ __
| |\/| |/ _ \ / _` |/ _ \ '__| '_ \| |/ _ \ '_ \/ __|/ _ \| '__|
| |  | | (_) | (_| |  __/ |  | | | | |  __/ | | \__ \ (_) | |
|_|  |_|\___/ \__,_|\___|_|  |_| |_|_|\___|_| |_|___/\___/|_|
"""

PROJECT_DESCRIPTION = """[bright_yellow]ModernTensor is a decentralized model training project running on Stellar Testnet.
Built by Vietnamese engineers from the ModernTensor Foundation.[/bright_yellow]"""
REPO_URL = "https://github.com/sonson0910/moderntensor.git"
DOCS_URL = "https://github.com/sonson0910/moderntensor/blob/main/README.md"
CHAT_URL = "https://t.me/+pDRlNXTi1wY2NTY1"
CONTRIBUTE_URL = "https://github.com/sonson0910/moderntensor"


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """ModernTensor CLI - Stellar Testnet wallets, chain, metagraph, and nodes."""

    if ctx.invoked_subcommand is None:
        console = Console()
        try:
            version = importlib.metadata.version("moderntensor")
        except importlib.metadata.PackageNotFoundError:
            version = "[yellow]unknown[/yellow]"

        info_text = Text.assemble(
            ("repo:       ", "bold blue"),
            (REPO_URL, "link " + REPO_URL),
            "\n",
            ("docs:       ", "bold green"),
            (DOCS_URL, "link " + DOCS_URL),
            "\n",
            ("chat:       ", "bold magenta"),
            (CHAT_URL, "link " + CHAT_URL),
            "\n",
            ("contribute: ", "bold yellow"),
            (CONTRIBUTE_URL, "link " + CONTRIBUTE_URL),
            "\n",
            ("version:    ", "bold cyan"),
            (version, "yellow"),
        )

        console.print(f"[bold bright_white]{ASCII_ART}[/bold bright_white]", justify="center")
        console.print(PROJECT_DESCRIPTION, justify="center")
        console.print()
        console.print(
            Panel(
                info_text,
                title="[bold bright_yellow on bright_red] Project Links [/]",
                border_style="bright_yellow",
                box=box.HEAVY,
                padding=(1, 2),
            )
        )
        console.print()
        ctx.exit()


cli.add_command(wallet_cli, name="w")
cli.add_command(chain_cli, name="chain")
cli.add_command(metagraph_cli, name="metagraph")
cli.add_command(node_cli, name="node")
cli.add_command(subnet1_cli, name="subnet1")
