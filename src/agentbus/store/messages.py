"""Mesaj (Message) veri deposu."""

import sqlite3
from typing import Optional, List
from agentbus.models import Message, utc_now_iso


def row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        ts=row["ts"],
        from_id=row["from_id"],
        to_id=row["to_id"],
        body=row["body"],
        read_at=row["read_at"],
        reply_to=row["reply_to"],
    )


class MessagesStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def send_message(
        self,
        from_id: str,
        to_id: str,
        body: str,
        reply_to: Optional[int] = None,
    ) -> Message:
        now = utc_now_iso()
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages (ts, from_id, to_id, body, reply_to)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, from_id, to_id, body, reply_to)
            )
            msg_id = cursor.lastrowid
        return Message(
            id=msg_id,
            ts=now,
            from_id=from_id,
            to_id=to_id,
            body=body,
            reply_to=reply_to,
        )

    def get_inbox(
        self,
        recipient_id: str,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[Message]:
        query = "SELECT * FROM messages WHERE (to_id = ? OR to_id = 'all')"
        params = [recipient_id]
        if unread_only:
            query += " AND read_at IS NULL"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return [row_to_message(r) for r in cursor.fetchall()]

    def mark_read(self, message_id: int) -> None:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                "UPDATE messages SET read_at = ? WHERE id = ? AND read_at IS NULL",
                (now, message_id)
            )
