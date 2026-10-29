"""Canlı İşçi Süreçleri (Agents) veri deposu."""

import sqlite3
from typing import Optional, List
from agentbus.models import AgentWorker, utc_now_iso


def row_to_agent(row: sqlite3.Row) -> AgentWorker:
    return AgentWorker(
        id=row["id"],
        pid=row["pid"],
        host=row["host"],
        started_at=row["started_at"],
        heartbeat_at=row["heartbeat_at"],
        current_job=row["current_job"],
    )


class AgentsStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def register_agent(self, agent_id: str, pid: int, host: str, current_job: Optional[str] = None) -> AgentWorker:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO agents (id, pid, host, started_at, heartbeat_at, current_job)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (agent_id, pid, host, now, now, current_job)
            )
        return AgentWorker(id=agent_id, pid=pid, host=host, started_at=now, heartbeat_at=now, current_job=current_job)

    def heartbeat_agent(self, agent_id: str, current_job: Optional[str] = None) -> None:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                UPDATE agents
                SET heartbeat_at = ?, current_job = coalesce(?, current_job)
                WHERE id = ?
                """,
                (now, current_job, agent_id)
            )

    def unregister_agent(self, agent_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))

    def list_agents(self) -> List[AgentWorker]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM agents ORDER BY started_at ASC")
        return [row_to_agent(r) for r in cursor.fetchall()]
