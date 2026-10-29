"""Agent Bus veritabanı bağlantısı, şema ve atomik durum geçişi."""

import os
import sqlite3
import json
from pathlib import Path
from typing import Optional, Any, Dict
from agentbus.models import (
    JobStatus,
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    utc_now_iso,
)

SCHEMA_VERSION = "1"

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / ".data"


def get_home_dir(custom_home: Optional[str] = None) -> Path:
    """Veri dizinini döndürür. Sıra: custom_home > AGENTBUS_HOME > .data"""
    if custom_home:
        p = Path(custom_home).resolve()
    elif os.environ.get("AGENTBUS_HOME"):
        p = Path(os.environ["AGENTBUS_HOME"]).resolve()
    else:
        p = DEFAULT_DATA_DIR.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path(custom_home: Optional[str] = None) -> Path:
    """bus.db dosya yolunu döndürür."""
    home = get_home_dir(custom_home)
    return home / "bus.db"


def get_connection(db_path: Optional[Path] = None, custom_home: Optional[str] = None) -> sqlite3.Connection:
    """SQLite bağlantısını WAL modu ve optimize PRAGMA'larla açar."""
    if db_path is None:
        db_path = get_db_path(custom_home)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(db_path),
        timeout=10.0,
        isolation_level=None  # autocommit / explicit transaction kontrolü
    )
    conn.row_factory = sqlite3.Row

    # WAL ve eşzamanlılık PRAGMA'ları
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Veritabanı tablolarını ve indekslerini oluşturur."""
    with conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            task_md TEXT NOT NULL,
            parent_id TEXT,
            depends_on TEXT DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'queued',
            priority INTEGER DEFAULT 5,
            agent_profile TEXT DEFAULT 'default',
            conversation_id TEXT,
            worktree_path TEXT,
            branch TEXT,
            base_commit TEXT,
            allowed_paths TEXT DEFAULT '[]',
            attempt INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            lease_owner TEXT,
            lease_until TEXT,
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            result_summary TEXT,
            error TEXT,
            repo TEXT
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            kind TEXT NOT NULL,
            prompt TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            response TEXT,
            usage_json TEXT,
            duration_s REAL,
            raw_path TEXT,
            started_at TEXT,
            finished_at TEXT,
            pid INTEGER,
            process_create_time REAL,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            UNIQUE(job_id, seq)
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            job_id TEXT,
            agent_id TEXT,
            type TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'info',
            payload_json TEXT DEFAULT '{}'
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            body TEXT NOT NULL,
            read_at TEXT,
            reply_to INTEGER
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS board (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            author TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            version INTEGER DEFAULT 1
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            path_glob TEXT NOT NULL,
            job_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(path_glob, job_id)
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            pid INTEGER NOT NULL,
            host TEXT NOT NULL,
            started_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            current_job TEXT
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)

        # Performans indeksleri
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(lease_owner, lease_until);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_job_seq ON turns(job_id, seq);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_id, read_at);")

        # Şema versiyon kaydı
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?);",
            (SCHEMA_VERSION,)
        )


def transition(
    conn: sqlite3.Connection,
    job_id: str,
    from_status: JobStatus,
    to_status: JobStatus,
    reason: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """İş durumunu atomik olarak günceller ve olay kaydı oluşturur.
    
    Yalnızca izin verilen geçişleri yapar; geçersiz geçişte InvalidTransitionError fırlatır.
    """
    allowed_next = ALLOWED_TRANSITIONS.get(from_status, [])
    if to_status not in allowed_next:
        raise InvalidTransitionError(
            job_id=job_id,
            from_status=from_status.value,
            to_status=to_status.value,
            reason=f"Bu durumdan geçişe izin verilmiyor (izinli: {[s.value for s in allowed_next]}). İstenen neden: {reason}"
        )

    now = utc_now_iso()
    with conn:
        cursor = conn.cursor()
        # Durumu ve varlığı doğrula
        cursor.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"İş bulunamadı: {job_id}")

        current_status = row["status"]
        if current_status != from_status.value:
            raise InvalidTransitionError(
                job_id=job_id,
                from_status=current_status,
                to_status=to_status.value,
                reason=f"Beklenen kaynak durum '{from_status.value}' fakat veritabanındaki durum '{current_status}'. {reason}"
            )

        # Durumu güncelle
        started_clause = ""
        finished_clause = ""
        params = [to_status.value, now]

        if to_status == JobStatus.RUNNING and from_status == JobStatus.QUEUED:
            started_clause = ", started_at = coalesce(started_at, ?)"
            params.append(now)

        if to_status in [JobStatus.PROMOTED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.REJECTED]:
            finished_clause = ", finished_at = ?"
            params.append(now)

        params.append(job_id)
        sql = f"UPDATE jobs SET status = ?, updated_at = ?{started_clause}{finished_clause} WHERE id = ?"
        cursor.execute(sql, params)

        # Olay günlüğüne yaz
        event_payload = {
            "from_status": from_status.value,
            "to_status": to_status.value,
            "reason": reason,
        }
        if payload:
            event_payload.update(payload)

        cursor.execute(
            """
            INSERT INTO events (ts, job_id, type, level, payload_json)
            VALUES (?, ?, 'job.transition', 'info', ?)
            """,
            (now, job_id, json.dumps(event_payload, ensure_ascii=False))
        )
