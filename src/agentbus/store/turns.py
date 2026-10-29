"""Tur (Turn) veri deposu."""

import sqlite3
import json
from typing import Optional, List, Any
from agentbus.models import Turn, TurnKind, TurnStatus, utc_now_iso


def row_to_turn(row: sqlite3.Row) -> Turn:
    return Turn(
        id=row["id"],
        job_id=row["job_id"],
        seq=row["seq"],
        kind=TurnKind(row["kind"]),
        prompt=row["prompt"],
        status=TurnStatus(row["status"]),
        response=row["response"],
        usage_json=row["usage_json"],
        duration_s=row["duration_s"],
        raw_path=row["raw_path"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        pid=row["pid"],
        process_create_time=row["process_create_time"],
    )


class TurnsStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_turn(
        self,
        job_id: str,
        kind: TurnKind = TurnKind.INITIAL,
        prompt: str = "",
        raw_path: Optional[str] = None,
        pid: Optional[int] = None,
        process_create_time: Optional[float] = None,
    ) -> Turn:
        """İş için bir sonraki turu oluşturur."""
        now = utc_now_iso()
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT coalesce(max(seq), 0) + 1 AS next_seq FROM turns WHERE job_id = ?",
            (job_id,)
        )
        next_seq = cursor.fetchone()["next_seq"]

        with self.conn:
            cursor.execute(
                """
                INSERT INTO turns (
                    job_id, seq, kind, prompt, status, raw_path,
                    started_at, pid, process_create_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, next_seq, kind.value, prompt,
                    TurnStatus.RUNNING.value, raw_path, now, pid, process_create_time
                )
            )
            turn_id = cursor.lastrowid
            # Olay kaydı
            self.conn.execute(
                """
                INSERT INTO events (ts, job_id, type, level, payload_json)
                VALUES (?, ?, 'turn.started', 'info', ?)
                """,
                (now, job_id, json.dumps({"seq": next_seq, "kind": kind.value, "pid": pid}))
            )
        return self.get_turn(job_id, next_seq)  # type: ignore

    def get_turn(self, job_id: str, seq: int) -> Optional[Turn]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM turns WHERE job_id = ? AND seq = ?",
            (job_id, seq)
        )
        row = cursor.fetchone()
        return row_to_turn(row) if row else None

    def get_latest_turn(self, job_id: str) -> Optional[Turn]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM turns WHERE job_id = ? ORDER BY seq DESC LIMIT 1",
            (job_id,)
        )
        row = cursor.fetchone()
        return row_to_turn(row) if row else None

    def list_turns(self, job_id: str) -> List[Turn]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM turns WHERE job_id = ? ORDER BY seq ASC",
            (job_id,)
        )
        return [row_to_turn(r) for r in cursor.fetchall()]

    def update_turn(self, job_id: str, seq: int, **kwargs: Any) -> Optional[Turn]:
        if not kwargs:
            return self.get_turn(job_id, seq)

        fields = []
        values = []
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            if isinstance(v, TurnStatus):
                values.append(v.value)
            elif isinstance(v, TurnKind):
                values.append(v.value)
            else:
                values.append(v)
        values.extend([job_id, seq])

        sql = f"UPDATE turns SET {', '.join(fields)} WHERE job_id = ? AND seq = ?"
        with self.conn:
            self.conn.execute(sql, values)
        return self.get_turn(job_id, seq)
