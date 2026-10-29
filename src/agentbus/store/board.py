"""Ortak Kara Tahta (Board) veri deposu."""

import sqlite3
from typing import Optional, List
from agentbus.models import BoardEntry, utc_now_iso


def row_to_board(row: sqlite3.Row) -> BoardEntry:
    return BoardEntry(
        key=row["key"],
        value=row["value"],
        author=row["author"],
        updated_at=row["updated_at"],
        version=row["version"],
    )


class BoardStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def set_entry(self, key: str, value: str, author: str) -> BoardEntry:
        now = utc_now_iso()
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT version FROM board WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                new_ver = row["version"] + 1
                cursor.execute(
                    """
                    UPDATE board
                    SET value = ?, author = ?, updated_at = ?, version = ?
                    WHERE key = ?
                    """,
                    (value, author, now, new_ver, key)
                )
            else:
                new_ver = 1
                cursor.execute(
                    """
                    INSERT INTO board (key, value, author, updated_at, version)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (key, value, author, now, new_ver)
                )
        return BoardEntry(key=key, value=value, author=author, updated_at=now, version=new_ver)

    def get_entry(self, key: str) -> Optional[BoardEntry]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM board WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row_to_board(row) if row else None

    def list_entries(self) -> List[BoardEntry]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM board ORDER BY key ASC")
        return [row_to_board(r) for r in cursor.fetchall()]
