"""Olay (Event) veri deposu."""

import sqlite3
import json
from typing import Optional, List, Dict, Any
from agentbus.models import Event, utc_now_iso


def row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        ts=row["ts"],
        job_id=row["job_id"],
        agent_id=row["agent_id"],
        type=row["type"],
        level=row["level"],
        payload_json=row["payload_json"],
    )


class EventsStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def emit_event(
        self,
        event_type: str,
        job_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        level: str = "info",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Event:
        now = utc_now_iso()
        p_json = json.dumps(payload or {}, ensure_ascii=False)
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO events (ts, job_id, agent_id, type, level, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, job_id, agent_id, event_type, level, p_json)
            )
            event_id = cursor.lastrowid
        return Event(
            id=event_id,
            ts=now,
            job_id=job_id,
            agent_id=agent_id,
            type=event_type,
            level=level,
            payload_json=p_json,
        )

    def list_events(
        self,
        job_id: Optional[str] = None,
        event_type: Optional[str] = None,
        min_id: Optional[int] = None,
        limit: int = 100,
        ascending: bool = True,
    ) -> List[Event]:
        query = "SELECT * FROM events WHERE 1=1"
        params: List[Any] = []

        if job_id:
            query += " AND job_id = ?"
            params.append(job_id)
        if event_type:
            query += " AND type = ?"
            params.append(event_type)
        if min_id is not None:
            query += " AND id > ?"
            params.append(min_id)

        direction = "ASC" if ascending else "DESC"
        query += f" ORDER BY id {direction} LIMIT ?"
        params.append(limit)

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return [row_to_event(r) for r in cursor.fetchall()]
