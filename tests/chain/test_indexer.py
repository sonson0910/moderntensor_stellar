from sdk.chain.base import MetagraphParticipant
from sdk.chain.indexer import MetagraphIndexer, sync_metagraph_snapshot


def test_indexer_caches_participants(tmp_path):
    indexer = MetagraphIndexer(str(tmp_path / "index.sqlite3"))
    indexer.upsert_participants(
        [
            MetagraphParticipant(
                uid="1",
                role="miner",
                public_key="G1",
                api_endpoint="http://m1",
                stake=10,
                trust_score=0.5,
                performance=0.9,
                status=1,
                cycle=7,
                history_hash="hash",
            )
        ],
        ledger=123,
    )

    rows = indexer.cached_participants("miner")

    assert indexer.last_ledger() == 123
    assert len(rows) == 1
    assert rows[0].uid == "1"
    assert rows[0].performance == 0.9


def test_sync_metagraph_snapshot_paginates(tmp_path):
    class Client:
        def current_ledger(self):
            return 50

        def active_participants(self, role, cursor=0, limit=100):
            if cursor > 0:
                return []
            return [
                MetagraphParticipant(
                    uid="2",
                    role=role,
                    public_key="G2",
                    api_endpoint="http://m2",
                    stake=1,
                )
            ]

    indexer = MetagraphIndexer(str(tmp_path / "index.sqlite3"))
    ledger = sync_metagraph_snapshot(Client(), indexer, "miner", page_size=1)

    assert ledger == 50
    assert indexer.cached_participants("miner")[0].uid == "2"
