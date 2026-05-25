from click.testing import CliRunner

from sdk.chain.base import SubnetCreationPolicy, UnbondRequest
from sdk.cli import metagraph_cli as metagraph_module


class FakeClient:
    def __init__(self):
        self.calls = []

    def request_unbond(self, uid, role, amount, source_account=None):
        self.calls.append(("request_unbond", uid, role, amount, source_account))
        return UnbondRequest(amount=amount, requested_ledger=100, unlock_ledger=110)

    def register_participant(self, participant, source_account=None):
        self.calls.append(("register_participant", participant.uid, participant.role, participant.public_key, source_account))
        return "registered"

    def pause_subnet(self, subnet_id=None, source_account=None):
        self.calls.append(("pause_subnet", subnet_id, source_account))
        return "paused"

    def resume_subnet(self, subnet_id=None, source_account=None):
        self.calls.append(("resume_subnet", subnet_id, source_account))
        return "resumed"

    def slash_stake(self, uid, role, authority, amount, source_account=None):
        self.calls.append(("slash_stake", uid, role, authority, amount, source_account))
        return amount

    def update_subnet_tokenomics(
        self,
        emission_per_cycle,
        miner_emission_bps,
        validator_emission_bps,
        subnet_id=None,
        source_account=None,
    ):
        self.calls.append(
            (
                "update_subnet_tokenomics",
                emission_per_cycle,
                miner_emission_bps,
                validator_emission_bps,
                subnet_id,
                source_account,
            )
        )
        return "updated"

    def update_subnet_registration(
        self,
        max_miners,
        max_validators,
        min_miner_stake,
        min_validator_stake,
        registration_fee,
        subnet_id=None,
        source_account=None,
    ):
        self.calls.append(
            (
                "update_subnet_registration",
                max_miners,
                max_validators,
                min_miner_stake,
                min_validator_stake,
                registration_fee,
                subnet_id,
                source_account,
            )
        )
        return "updated"

    def get_subnet_creation_policy(self):
        self.calls.append(("get_subnet_creation_policy",))
        return SubnetCreationPolicy(max_subnets=256, subnet_count=2, subnet_registration_fee=0.5)

    def update_subnet_creation_policy(self, max_subnets, subnet_registration_fee, source_account=None):
        self.calls.append(("update_subnet_creation_policy", max_subnets, subnet_registration_fee, source_account))
        return "updated"


def test_request_unbond_cli_preserves_rich_output_and_source(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(metagraph_module, "_client", lambda: fake)

    result = CliRunner().invoke(
        metagraph_module.metagraph_cli,
        ["request-unbond", "--uid", "1", "--role", "miner", "--amount", "1.5", "--source", "owner"],
    )

    assert result.exit_code == 0
    assert ("request_unbond", "1", "miner", 1.5, "owner") in fake.calls
    assert "Request Unbond" in result.output
    assert "unlock_ledger=110" in result.output


def test_register_cli_passes_owner_source(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(metagraph_module, "_client", lambda: fake)

    result = CliRunner().invoke(
        metagraph_module.metagraph_cli,
        [
            "register-miner",
            "--uid",
            "3",
            "--public-key",
            "GMINER",
            "--endpoint",
            "http://127.0.0.1:8000",
            "--stake",
            "1",
            "--source",
            "miner-secret",
        ],
    )

    assert result.exit_code == 0
    assert ("register_participant", "3", "miner", "GMINER", "miner-secret") in fake.calls


def test_subnet_lifecycle_cli_commands_call_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(metagraph_module, "_client", lambda: fake)
    runner = CliRunner()

    pause = runner.invoke(metagraph_module.metagraph_cli, ["pause-subnet", "--subnet-id", "2", "--source", "owner"])
    resume = runner.invoke(metagraph_module.metagraph_cli, ["resume-subnet", "--subnet-id", "2", "--source", "owner"])

    assert pause.exit_code == 0
    assert resume.exit_code == 0
    assert ("pause_subnet", 2, "owner") in fake.calls
    assert ("resume_subnet", 2, "owner") in fake.calls


def test_slash_stake_cli_scales_operator_intent(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(metagraph_module, "_client", lambda: fake)

    result = CliRunner().invoke(
        metagraph_module.metagraph_cli,
        [
            "slash-stake",
            "--uid",
            "7",
            "--role",
            "validator",
            "--authority",
            "GAUTH",
            "--amount",
            "0.25",
            "--source",
            "admin",
        ],
    )

    assert result.exit_code == 0
    assert ("slash_stake", "7", "validator", "GAUTH", 0.25, "admin") in fake.calls
    assert "slashed=0.250000" in result.output


def test_update_tokenomics_cli_calls_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(metagraph_module, "_client", lambda: fake)

    result = CliRunner().invoke(
        metagraph_module.metagraph_cli,
        [
            "update-tokenomics",
            "--subnet-id",
            "1",
            "--emission-per-cycle",
            "1",
            "--miner-emission-bps",
            "8000",
            "--validator-emission-bps",
            "2000",
            "--source",
            "admin",
        ],
    )

    assert result.exit_code == 0
    assert ("update_subnet_tokenomics", 1.0, 8000, 2000, 1, "admin") in fake.calls


def test_update_registration_cli_calls_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(metagraph_module, "_client", lambda: fake)

    result = CliRunner().invoke(
        metagraph_module.metagraph_cli,
        [
            "update-registration",
            "--subnet-id",
            "1",
            "--max-miners",
            "100",
            "--max-validators",
            "25",
            "--min-miner-stake",
            "2",
            "--min-validator-stake",
            "10",
            "--registration-fee",
            "0.1",
            "--source",
            "admin",
        ],
    )

    assert result.exit_code == 0
    assert ("update_subnet_registration", 100, 25, 2.0, 10.0, 0.1, 1, "admin") in fake.calls


def test_subnet_policy_cli_commands(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(metagraph_module, "_client", lambda: fake)
    runner = CliRunner()

    show = runner.invoke(metagraph_module.metagraph_cli, ["subnet-policy"])
    update = runner.invoke(
        metagraph_module.metagraph_cli,
        ["update-subnet-policy", "--max-subnets", "256", "--subnet-registration-fee", "0.5", "--source", "admin"],
    )

    assert show.exit_code == 0
    assert update.exit_code == 0
    assert "Subnet Creation Policy" in show.output
    assert ("update_subnet_creation_policy", 256, 0.5, "admin") in fake.calls
