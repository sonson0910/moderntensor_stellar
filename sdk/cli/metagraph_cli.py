"""Metagraph registry commands."""

from __future__ import annotations

import click
import json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sdk.chain.base import MetagraphParticipant
from sdk.chain.indexer import MetagraphIndexer, sync_metagraph_snapshot
from sdk.chain.stellar import StellarChainClient, build_stellar_testnet_config
from sdk.config.settings import settings


console = Console()


def _client() -> StellarChainClient:
    return StellarChainClient(build_stellar_testnet_config(settings), timeout=settings.HTTP_TIMEOUT_SECONDS)


@click.group()
def metagraph_cli():
    """Manage the Soroban metagraph registry."""


@metagraph_cli.command("deploy")
@click.option("--wasm", required=True, type=click.Path(exists=True))
@click.option("--source", default=None, help="Stellar CLI source identity or secret seed.")
def deploy_cmd(wasm, source):
    contract_id = _client().deploy_contract(wasm, source_account=source)
    console.print(Panel(f"[bold green]{contract_id}[/bold green]", title="Metagraph Contract"))


@metagraph_cli.command("init")
@click.option("--admin", required=True, help="Admin public key.")
@click.option("--stake-token", required=True, help="Native asset contract address for locked stake.")
@click.option("--source", default=None)
def init_cmd(admin, stake_token, source):
    result = _client().invoke_contract(
        "init",
        ["--admin", admin, "--stake_token", stake_token],
        source_account=source,
    )
    console.print(Panel(result or "initialized", title="Metagraph Init"))


@metagraph_cli.command("subnet")
@click.option("--subnet-id", default=None, type=int)
def subnet_cmd(subnet_id):
    subnet = _client().get_subnet(subnet_id)
    if not subnet:
        console.print(Panel("not found", title="Subnet"))
        return
    table = Table(title=f"Subnet {subnet.subnet_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("owner", subnet.owner)
    table.add_row("commit_authority", subnet.commit_authority)
    table.add_row("stake_token", subnet.stake_token)
    table.add_row("treasury", subnet.treasury)
    table.add_row("emission_per_cycle", f"{subnet.emission_per_cycle:.6f}")
    table.add_row("miner_emission_bps", str(subnet.miner_emission_bps))
    table.add_row("validator_emission_bps", str(subnet.validator_emission_bps))
    table.add_row("status", str(subnet.status))
    table.add_row("created_ledger", str(subnet.created_ledger))
    console.print(table)


@metagraph_cli.command("query")
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
@click.option("--uid", default=None)
@click.option("--cursor", default=0, type=int)
@click.option("--page-size", default=100, type=int)
@click.option("--indexer-db", default=None, type=click.Path())
@click.option("--max-ledger-lag", default=25, type=int)
def query_cmd(role, uid, cursor, page_size, indexer_db, max_ledger_lag):
    client = _client()
    if uid:
        participant = client.query_participant(uid, role)
        rows = [participant] if participant else []
    elif indexer_db:
        indexer = MetagraphIndexer(indexer_db)
        rows = indexer.cached_participants(role, limit=page_size, offset=cursor)
        try:
            lag = client.current_ledger() - indexer.last_ledger()
            if lag > max_ledger_lag:
                console.print(f"[yellow]Indexer cache is {lag} ledgers behind source of truth.[/yellow]")
        except Exception:
            console.print("[yellow]Could not verify indexer ledger lag.[/yellow]")
    else:
        rows = client.active_participants(role, cursor=cursor, limit=page_size)
    table = Table(title=f"Active {role}s")
    table.add_column("UID", style="cyan")
    table.add_column("Public Key", style="green")
    table.add_column("Endpoint", style="yellow")
    table.add_column("Stake")
    table.add_column("Trust")
    table.add_column("Perf")
    for item in rows:
        table.add_row(item.uid, item.public_key, item.api_endpoint, str(item.stake), f"{item.trust_score:.4f}", f"{item.performance:.4f}")
    console.print(table)


@metagraph_cli.command("cycle")
@click.option("--cycle", "cycle_num", required=True, type=int)
def cycle_cmd(cycle_num):
    commit = _client().get_cycle_commit(cycle_num)
    if not commit:
        console.print(Panel("not committed", title=f"Cycle {cycle_num}"))
        return
    table = Table(title=f"Cycle {cycle_num}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("score_root", commit.score_root)
    table.add_row("updates_hash", commit.updates_hash)
    table.add_row("quorum_weight", f"{commit.quorum_weight:.6f}")
    table.add_row("distributed_rewards", f"{commit.distributed_rewards:.6f}")
    table.add_row("committed_at_ledger", str(commit.committed_at_ledger))
    console.print(table)


@metagraph_cli.command("commit-status")
@click.option("--cycle", "cycle_num", required=True, type=int)
def commit_status_cmd(cycle_num):
    commit = _client().get_cycle_commit(cycle_num)
    status = "committed" if commit else "pending"
    console.print(Panel(status, title=f"Cycle {cycle_num} Commit Status"))


@metagraph_cli.command("index")
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
@click.option("--db", "db_path", default="metagraph_index.sqlite3", type=click.Path())
@click.option("--page-size", default=100, type=int)
def index_cmd(role, db_path, page_size):
    indexer = MetagraphIndexer(db_path)
    ledger = sync_metagraph_snapshot(_client(), indexer, role, page_size=page_size)
    console.print(Panel(f"role={role}\nledger={ledger}\ndb={db_path}", title="Metagraph Index"))


@metagraph_cli.command("register-miner")
@click.option("--uid", required=True)
@click.option("--public-key", required=True)
@click.option("--endpoint", required=True)
@click.option("--stake", required=True, type=float)
@click.option("--source", default=None)
def register_miner_cmd(uid, public_key, endpoint, stake, source):
    tx = _client().register_participant(
        MetagraphParticipant(uid, "miner", public_key, endpoint, stake),
        source_account=source,
    )
    console.print(Panel(tx or "submitted", title="Register Miner"))


@metagraph_cli.command("register-validator")
@click.option("--uid", required=True)
@click.option("--public-key", required=True)
@click.option("--endpoint", required=True)
@click.option("--stake", required=True, type=float)
@click.option("--source", default=None)
def register_validator_cmd(uid, public_key, endpoint, stake, source):
    tx = _client().register_participant(
        MetagraphParticipant(uid, "validator", public_key, endpoint, stake),
        source_account=source,
    )
    console.print(Panel(tx or "submitted", title="Register Validator"))


@metagraph_cli.command("set-status")
@click.option("--uid", required=True)
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
@click.option("--status", required=True, type=int)
@click.option("--reason", default="")
@click.option("--source", default=None)
def set_status_cmd(uid, role, status, reason, source):
    tx = _client().set_participant_status(uid, role, status, reason, source_account=source)
    console.print(Panel(tx or "submitted", title="Set Status"))


@metagraph_cli.command("set-subnet-status")
@click.option("--subnet-id", default=None, type=int)
@click.option("--status", required=True, type=int)
@click.option("--source", default=None)
def set_subnet_status_cmd(subnet_id, status, source):
    tx = _client().set_subnet_status(status, subnet_id=subnet_id, source_account=source)
    console.print(Panel(tx or "submitted", title="Set Subnet Status"))


@metagraph_cli.command("pause-subnet")
@click.option("--subnet-id", default=None, type=int)
@click.option("--source", default=None)
def pause_subnet_cmd(subnet_id, source):
    tx = _client().pause_subnet(subnet_id=subnet_id, source_account=source)
    console.print(Panel(tx or "submitted", title="Pause Subnet"))


@metagraph_cli.command("resume-subnet")
@click.option("--subnet-id", default=None, type=int)
@click.option("--source", default=None)
def resume_subnet_cmd(subnet_id, source):
    tx = _client().resume_subnet(subnet_id=subnet_id, source_account=source)
    console.print(Panel(tx or "submitted", title="Resume Subnet"))


@metagraph_cli.command("update-tokenomics")
@click.option("--subnet-id", default=None, type=int)
@click.option("--emission-per-cycle", required=True, type=float)
@click.option("--miner-emission-bps", required=True, type=int)
@click.option("--validator-emission-bps", required=True, type=int)
@click.option("--source", default=None)
def update_tokenomics_cmd(subnet_id, emission_per_cycle, miner_emission_bps, validator_emission_bps, source):
    tx = _client().update_subnet_tokenomics(
        emission_per_cycle,
        miner_emission_bps,
        validator_emission_bps,
        subnet_id=subnet_id,
        source_account=source,
    )
    console.print(Panel(tx or "submitted", title="Update Tokenomics"))


@metagraph_cli.command("unbond-request")
@click.option("--uid", required=True)
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
def unbond_request_cmd(uid, role):
    request = _client().get_unbond_request(uid, role)
    if not request:
        console.print(Panel("none", title="Unbond Request"))
        return
    table = Table(title=f"{role} {uid} Unbond")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("amount", f"{request.amount:.6f}")
    table.add_row("requested_ledger", str(request.requested_ledger))
    table.add_row("unlock_ledger", str(request.unlock_ledger))
    table.add_row("subnet_id", str(request.subnet_id))
    console.print(table)


@metagraph_cli.command("request-unbond")
@click.option("--uid", required=True)
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
@click.option("--amount", required=True, type=float)
@click.option("--source", default=None)
def request_unbond_cmd(uid, role, amount, source):
    request = _client().request_unbond(uid, role, amount, source_account=source)
    body = (
        f"amount={request.amount:.6f}\n"
        f"requested_ledger={request.requested_ledger}\n"
        f"unlock_ledger={request.unlock_ledger}"
    )
    console.print(Panel(body, title="Request Unbond"))


@metagraph_cli.command("withdraw-unbonded")
@click.option("--uid", required=True)
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
@click.option("--source", default=None)
def withdraw_unbonded_cmd(uid, role, source):
    amount = _client().withdraw_unbonded(uid, role, source_account=source)
    console.print(Panel(f"withdrawn={amount:.6f}", title="Withdraw Unbonded"))


@metagraph_cli.command("slash-stake")
@click.option("--uid", required=True)
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
@click.option("--authority", required=True)
@click.option("--amount", required=True, type=float)
@click.option("--source", default=None)
def slash_stake_cmd(uid, role, authority, amount, source):
    slashed = _client().slash_stake(uid, role, authority, amount, source_account=source)
    console.print(Panel(f"slashed={slashed:.6f}", title="Slash Stake"))


@metagraph_cli.command("reward-balance")
@click.option("--uid", required=True)
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
def reward_balance_cmd(uid, role):
    amount = _client().reward_balance(uid, role)
    console.print(Panel(f"{amount:.6f}", title=f"{role} {uid} Rewards"))


@metagraph_cli.command("reward-reserve")
def reward_reserve_cmd():
    amount = _client().reward_reserve()
    console.print(Panel(f"{amount:.6f}", title="Reward Reserve"))


@metagraph_cli.command("fund-rewards")
@click.option("--from-account", required=True)
@click.option("--amount", required=True, type=float)
@click.option("--source", default=None)
def fund_rewards_cmd(from_account, amount, source):
    tx = _client().fund_rewards(from_account, amount, source_account=source)
    console.print(Panel(tx or "submitted", title="Fund Rewards"))


@metagraph_cli.command("claim-rewards")
@click.option("--uid", required=True)
@click.option("--role", type=click.Choice(["miner", "validator"]), required=True)
@click.option("--source", default=None)
def claim_rewards_cmd(uid, role, source):
    tx = _client().claim_rewards(uid, role, source_account=source)
    try:
        amount = float(json.loads(tx)) / settings.STELLAR_TOKEN_AMOUNT_SCALE
        body = f"claimed={amount:.6f}"
    except Exception:
        body = tx or "submitted"
    console.print(Panel(body, title="Claim Rewards"))
