"""Lightweight SQLite cache for metagraph participant snapshots."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable, List

from .base import MetagraphParticipant


class MetagraphIndexer:
    def __init__(self, db_path: str = "metagraph_index.sqlite3"):
        self.db_path = Path(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS participants (
                    role TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    stake REAL NOT NULL,
                    trust_score REAL NOT NULL,
                    performance REAL NOT NULL,
                    status INTEGER NOT NULL,
                    cycle INTEGER NOT NULL,
                    history_hash TEXT NOT NULL,
                    reward_balance REAL NOT NULL DEFAULT 0,
                    ledger INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (role, uid)
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(participants)").fetchall()}
            if "reward_balance" not in columns:
                conn.execute("ALTER TABLE participants ADD COLUMN reward_balance REAL NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def upsert_participants(self, participants: Iterable[MetagraphParticipant], ledger: int) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO participants (
                    role, uid, public_key, endpoint, stake, trust_score,
                    performance, status, cycle, history_hash, reward_balance, ledger, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(role, uid) DO UPDATE SET
                    public_key=excluded.public_key,
                    endpoint=excluded.endpoint,
                    stake=excluded.stake,
                    trust_score=excluded.trust_score,
                    performance=excluded.performance,
                    status=excluded.status,
                    cycle=excluded.cycle,
                    history_hash=excluded.history_hash,
                    reward_balance=excluded.reward_balance,
                    ledger=excluded.ledger,
                    updated_at=excluded.updated_at
                """,
                [
                    (
                        item.role,
                        item.uid,
                        item.public_key,
                        item.api_endpoint,
                        item.stake,
                        item.trust_score,
                        item.performance,
                        item.status,
                        item.cycle,
                        item.history_hash,
                        item.reward_balance,
                        ledger,
                        now,
                    )
                    for item in participants
                ],
            )
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES ('last_ledger', ?)",
                (str(ledger),),
            )

    def cached_participants(self, role: str, limit: int = 100, offset: int = 0) -> List[MetagraphParticipant]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT uid, public_key, endpoint, stake, trust_score, performance, status, cycle, history_hash, reward_balance
                FROM participants
                WHERE role = ?
                ORDER BY CAST(uid AS INTEGER), uid
                LIMIT ? OFFSET ?
                """,
                (role, limit, offset),
            ).fetchall()
        return [
            MetagraphParticipant(
                uid=str(row[0]),
                role=role,
                public_key=str(row[1]),
                api_endpoint=str(row[2]),
                stake=float(row[3]),
                trust_score=float(row[4]),
                performance=float(row[5]),
                status=int(row[6]),
                cycle=int(row[7]),
                history_hash=str(row[8]),
                reward_balance=float(row[9]),
            )
            for row in rows
        ]

    def last_ledger(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = 'last_ledger'").fetchone()
        return int(row[0]) if row else 0


def sync_metagraph_snapshot(client, indexer: MetagraphIndexer, role: str, page_size: int = 100) -> int:
    """Refresh the cache by paginating contract source-of-truth state."""

    ledger = client.current_ledger()
    cursor = 0
    while True:
        page = client.active_participants(role, cursor=cursor, limit=page_size)
        if not page:
            break
        indexer.upsert_participants(page, ledger)
        cursor += len(page)
        if len(page) < page_size:
            break
    return ledger
