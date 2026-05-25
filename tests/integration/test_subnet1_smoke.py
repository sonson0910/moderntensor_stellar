import json

import pytest

from scripts import subnet1_smoke


def test_subnet1_smoke_runs_local_without_live(monkeypatch):
    pytest.importorskip("stellar_sdk")
    monkeypatch.delenv("STELLAR_LIVE_TESTNET", raising=False)
    monkeypatch.delenv("STELLAR_METAGRAPH_CONTRACT_ID", raising=False)
    monkeypatch.delenv("VALIDATOR_STELLAR_SECRET", raising=False)

    report = subnet1_smoke.run_smoke(live=False)

    assert report.cycle == 7
    assert report.score == 0.875
    assert report.local_commit_tx == "local-smoke-7"
    assert report.live_commit_tx is None
    assert report.quorum_validators == ["1", "2", "3"]
    assert len(report.updates) == 1
    assert report.updates[0].uid == "101"


def test_subnet1_smoke_cli_json_local_only(monkeypatch, capsys):
    pytest.importorskip("stellar_sdk")
    monkeypatch.delenv("STELLAR_LIVE_TESTNET", raising=False)

    exit_code = subnet1_smoke.main(["--no-live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["score"] == 0.875
    assert payload["local_commit_tx"] == "local-smoke-7"
    assert payload["live_commit_tx"] is None
