"""Append-only SQLite audit log writer and reader."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                sim_ts REAL NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def append(self, incident_id: str, sim_ts: float, payload: BaseModel) -> int:
        cursor = self.connection.execute(
            "INSERT INTO events (incident_id, sim_ts, kind, payload) VALUES (?, ?, ?, ?)",
            (
                incident_id,
                sim_ts,
                payload.__class__.model_fields["type"].default,
                payload.model_dump_json(),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def export(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT seq, incident_id, sim_ts, kind, payload FROM events ORDER BY seq"
        )
        return [
            {
                "seq": seq,
                "incident_id": incident_id,
                "sim_ts": sim_ts,
                "kind": kind,
                "payload": json.loads(payload),
            }
            for seq, incident_id, sim_ts, kind, payload in rows
        ]

    def close(self) -> None:
        self.connection.close()
