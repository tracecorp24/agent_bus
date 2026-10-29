"""Dosya Sahiplik Kilitleri (Claims) veri deposu."""

import sqlite3
from typing import Optional, List
from agentbus.models import Claim, utc_now_iso


def row_to_claim(row: sqlite3.Row) -> Claim:
    return Claim(
        path_glob=row["path_glob"],
        job_id=row["job_id"],
        created_at=row["created_at"],
    )


class ClaimsStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def claim_path(self, path_glob: str, job_id: str) -> Claim:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO claims (path_glob, job_id, created_at)
                VALUES (?, ?, ?)
                """,
                (path_glob, job_id, now)
            )
        return Claim(path_glob=path_glob, job_id=job_id, created_at=now)

    def unclaim_path(self, path_glob: str, job_id: str) -> bool:
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                "DELETE FROM claims WHERE path_glob = ? AND job_id = ?",
                (path_glob, job_id)
            )
            return cursor.rowcount > 0

    def list_claims(self, job_id: Optional[str] = None) -> List[Claim]:
        cursor = self.conn.cursor()
        if job_id:
            cursor.execute("SELECT * FROM claims WHERE job_id = ?", (job_id,))
        else:
            cursor.execute("SELECT * FROM claims ORDER BY created_at ASC")
        return [row_to_claim(r) for r in cursor.fetchall()]
