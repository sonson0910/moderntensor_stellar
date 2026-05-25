"""Wallet commands for encrypted Stellar hotkeys."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from sdk.config.settings import settings
from sdk.keymanager import WalletManager


console = Console()


@click.group()
def wallet_cli():
    """✨ Manage ModernTensor coldkeys and Stellar hotkeys. ✨"""


@wallet_cli.command("create-coldkey")
@click.option("--name", required=True, help="Coldkey namespace name.")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--base-dir", default=lambda: settings.HOTKEY_BASE_DIR)
@click.option("--force", is_flag=True, help="Overwrite an existing coldkey namespace.")
def create_coldkey_cmd(name, password, base_dir, force):
    manager = WalletManager(base_dir=base_dir)
    path = manager.create_coldkey(name, password, force=force)
    console.print(Panel(f"[bold green]Coldkey created[/bold green]\n[cyan]{path}[/cyan]", title="Wallet"))


@wallet_cli.command("generate-hotkey")
@click.option("--coldkey", required=True)
@click.option("--hotkey-name", required=True)
@click.option("--password", prompt=True, hide_input=True)
@click.option("--base-dir", default=lambda: settings.HOTKEY_BASE_DIR)
@click.option("--overwrite", is_flag=True)
def generate_hotkey_cmd(coldkey, hotkey_name, password, base_dir, overwrite):
    manager = WalletManager(base_dir=base_dir)
    item = manager.generate_hotkey(coldkey, hotkey_name, password, overwrite=overwrite)
    console.print(Panel(f"[bold green]Hotkey generated[/bold green]\n{item['public_key']}", title=hotkey_name))


@wallet_cli.command("import-hotkey")
@click.option("--coldkey", required=True)
@click.option("--hotkey-name", required=True)
@click.option("--secret-seed", required=True, prompt=True, hide_input=True)
@click.option("--password", prompt=True, hide_input=True)
@click.option("--base-dir", default=lambda: settings.HOTKEY_BASE_DIR)
@click.option("--overwrite", is_flag=True)
def import_hotkey_cmd(coldkey, hotkey_name, secret_seed, password, base_dir, overwrite):
    manager = WalletManager(base_dir=base_dir)
    item = manager.import_hotkey(coldkey, hotkey_name, secret_seed, password, overwrite=overwrite)
    console.print(Panel(f"[bold green]Hotkey imported[/bold green]\n{item['public_key']}", title=hotkey_name))


@wallet_cli.command("list")
@click.option("--base-dir", default=lambda: settings.HOTKEY_BASE_DIR)
def list_coldkeys_cmd(base_dir):
    manager = WalletManager(base_dir=base_dir)
    tree = Tree("[bold bright_yellow]ModernTensor Wallets[/bold bright_yellow]")
    for name in manager.list_coldkeys():
        branch = tree.add(f"[magenta]{name}[/magenta]")
        for hotkey in manager.list_hotkeys(name):
            branch.add(f"[cyan]{hotkey['name']}[/cyan] [dim]{hotkey['public_key']}[/dim]")
    console.print(tree)


@wallet_cli.command("list-hotkeys")
@click.option("--coldkey", required=True)
@click.option("--base-dir", default=lambda: settings.HOTKEY_BASE_DIR)
def list_hotkeys_cmd(coldkey, base_dir):
    manager = WalletManager(base_dir=base_dir)
    table = Table(title=f"Hotkeys for {coldkey}")
    table.add_column("Name", style="cyan")
    table.add_column("Public Key", style="green")
    table.add_column("Created", style="yellow")
    for item in manager.list_hotkeys(coldkey):
        table.add_row(item["name"], item["public_key"], item["created_at"])
    console.print(table)


@wallet_cli.command("show-hotkey")
@click.option("--coldkey", required=True)
@click.option("--hotkey", required=True)
@click.option("--base-dir", default=lambda: settings.HOTKEY_BASE_DIR)
def show_hotkey_cmd(coldkey, hotkey, base_dir):
    manager = WalletManager(base_dir=base_dir)
    item = manager.show_hotkey(coldkey, hotkey)
    console.print(Panel(f"[bold]Public key[/bold]\n[green]{item['public_key']}[/green]", title=hotkey))


@wallet_cli.command("show-address")
@click.option("--coldkey", required=True)
@click.option("--hotkey", required=True)
@click.option("--base-dir", default=lambda: settings.HOTKEY_BASE_DIR)
def show_address_cmd(coldkey, hotkey, base_dir):
    manager = WalletManager(base_dir=base_dir)
    item = manager.show_hotkey(coldkey, hotkey)
    console.print(Panel(f"[green]{item['public_key']}[/green]", title="Stellar Public Key"))
