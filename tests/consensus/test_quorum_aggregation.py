import pytest

from sdk.chain.base import ChainCycleCommit, MetagraphParticipant
from sdk.consensus.node import ValidatorNode
from sdk.core.datatypes import MinerInfo, ValidatorInfo, ValidatorScore


class DummyChain:
    def __init__(self):
        self.commits = []

    def current_ledger(self):
        return 600

    def active_participants(self, role, cursor=0, limit=100):
        return []

    def commit_cycle(self, cycle, updates, quorum_validators, score_root, updates_hash):
        self.commits.append((cycle, updates, quorum_validators, score_root, updates_hash))
        return ChainCycleCommit(
            cycle=cycle,
            score_root=score_root,
            updates_hash=updates_hash,
            quorum_weight=2.0,
            tx_hash="txhash",
        )


def _node(tmp_path):
    chain = DummyChain()
    node = ValidatorNode(
        validator_info=ValidatorInfo(uid="v1", public_key="G1", stake=10, trust_score=1.0),
        chain_client=chain,
        stellar_secret="S" + "A" * 55,
        state_file=str(tmp_path / "state.json"),
    )
    node.current_cycle = 5
    node.miners_info = {
        "m1": MinerInfo(uid="m1", public_key="GM1", trust_score=0.5, stake=100),
    }
    node.validators_info = {
        "v1": ValidatorInfo(uid="v1", public_key="G1", stake=1, trust_score=1.0),
        "v2": ValidatorInfo(uid="v2", public_key="G2", stake=10, trust_score=1.0),
        "v3": ValidatorInfo(uid="v3", public_key="G3", stake=1, trust_score=1.0),
    }
    return node, chain


@pytest.mark.asyncio
async def test_weighted_median_quorum_commit(tmp_path):
    node, chain = _node(tmp_path)
    await node.add_received_score("v1", 5, [ValidatorScore("t1", "m1", "v1", 0.1)])
    await node.add_received_score("v2", 5, [ValidatorScore("t2", "m1", "v2", 0.9)])
    await node.add_received_score("v3", 5, [ValidatorScore("t3", "m1", "v3", 1.0)])

    updates, quorum = node.aggregate_cycle_updates(5)

    assert quorum == ["v1", "v2", "v3"]
    assert len(updates) == 1
    assert updates[0].performance == 0.9
    assert round(updates[0].trust, 2) == 0.58

    tx = await node.commit_quorum_state()

    assert tx == "txhash"
    assert len(chain.commits) == 1


@pytest.mark.asyncio
async def test_votes_below_quorum_do_not_commit(tmp_path):
    node, chain = _node(tmp_path)
    await node.add_received_score("v1", 5, [ValidatorScore("t1", "m1", "v1", 1.0)])

    updates, quorum = node.aggregate_cycle_updates(5)
    tx = await node.commit_quorum_state()

    assert updates == []
    assert quorum == []
    assert tx is None
    assert chain.commits == []


@pytest.mark.asyncio
async def test_metrics_snapshot_tracks_consensus_observability(tmp_path):
    node, _chain = _node(tmp_path)
    node.tasks_sent = {"t1": object()}
    node.results_buffer = {"t1": object()}

    await node.add_received_score("v1", 5, [ValidatorScore("t1", "m1", "v1", 0.8)])
    await node.add_received_score("v1", 5, [ValidatorScore("t1", "m1", "v1", 0.8)])

    snapshot = node.metrics_snapshot()

    assert snapshot["cycle"] == 5
    assert snapshot["peers"]["miners_total"] == 1
    assert snapshot["peers"]["validators_active"] == 3
    assert snapshot["queues"]["task_depth"] == 1
    assert snapshot["queues"]["result_depth"] == 1
    assert snapshot["buffers"]["votes_buffered"] == 1
    assert snapshot["counters"]["validator_score_votes_accepted_total"] == 1
    assert snapshot["counters"]["validator_score_votes_rejected_total"] == 1
    assert snapshot["counters"]["duplicate_score_votes"] == 1
