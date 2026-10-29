"""İş (Job) veri deposu."""

import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from agentbus.models import Job, JobStatus, utc_now_iso


def generate_job_id(conn: sqlite3.Connection) -> str:
    """j_YYYYMMDD_NNNN formatında atomik ve benzersiz iş kimliği üretir."""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"j_{today_str}_"
    meta_key = f"seq_{today_str}"

    with conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO meta (key, value) VALUES (?, '1')
            ON CONFLICT(key) DO UPDATE SET value = cast(value as integer) + 1
            RETURNING value
            """,
            (meta_key,)
        )
        row = cursor.fetchone()
        seq = int(row[0])
    return f"{prefix}{seq:04d}"


def row_to_job(row: sqlite3.Row) -> Job:
    """SQLite satırını Job dataclass'ına dönüştürür."""
    return Job(
        id=row["id"],
        title=row["title"],
        task_md=row["task_md"],
        parent_id=row["parent_id"],
        depends_on=json.loads(row["depends_on"]) if row["depends_on"] else [],
        status=JobStatus(row["status"]),
        priority=row["priority"],
        agent_profile=row["agent_profile"],
        conversation_id=row["conversation_id"],
        worktree_path=row["worktree_path"],
        branch=row["branch"],
        base_commit=row["base_commit"],
        allowed_paths=json.loads(row["allowed_paths"]) if row["allowed_paths"] else [],
        attempt=row["attempt"],
        max_attempts=row["max_attempts"],
        lease_owner=row["lease_owner"],
        lease_until=row["lease_until"],
        idempotency_key=row["idempotency_key"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        result_summary=row["result_summary"],
        error=row["error"],
        repo=row["repo"],
    )


class JobsStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_job(
        self,
        title: str,
        task_md: str,
        parent_id: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
        priority: int = 5,
        agent_profile: str = "default",
        allowed_paths: Optional[List[str]] = None,
        idempotency_key: Optional[str] = None,
        repo: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Job:
        """Yeni bir iş oluşturur veya idempotency_key varsa var olanı döndürür."""
        if idempotency_key:
            existing = self.find_by_idempotency_key(idempotency_key)
            if existing:
                return existing

        now = utc_now_iso()
        deps = json.dumps(depends_on or [])
        paths = json.dumps(allowed_paths or [])

        # Eşzamanlı oluşturmalarda ID çakışmasını önlemek için retry
        for attempt in range(10):
            j_id = job_id or generate_job_id(self.conn)
            try:
                with self.conn:
                    self.conn.execute(
                        """
                        INSERT INTO jobs (
                            id, title, task_md, parent_id, depends_on, status, priority,
                            agent_profile, allowed_paths, idempotency_key, created_at, updated_at, repo
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            j_id, title, task_md, parent_id, deps, JobStatus.QUEUED.value,
                            priority, agent_profile, paths, idempotency_key, now, now, repo
                        )
                    )
                    # Olay günlüğü
                    self.conn.execute(
                        """
                        INSERT INTO events (ts, job_id, type, level, payload_json)
                        VALUES (?, ?, 'job.created', 'info', ?)
                        """,
                        (now, j_id, json.dumps({"title": title, "priority": priority}))
                    )
                return self.get_job(j_id)  # type: ignore
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed: jobs.id" in str(e) and not job_id:
                    time.sleep(0.005 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("İş kimliği üretilemedi, çakışma aşılamadı.")

    def get_job(self, job_id: str) -> Optional[Job]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return row_to_job(row) if row else None

    def find_by_idempotency_key(self, key: str) -> Optional[Job]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (key,))
        row = cursor.fetchone()
        return row_to_job(row) if row else None

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: int = 100,
        order_by: str = "priority DESC, created_at ASC"
    ) -> List[Job]:
        cursor = self.conn.cursor()
        if status:
            cursor.execute(
                f"SELECT * FROM jobs WHERE status = ? ORDER BY {order_by} LIMIT ?",
                (status.value, limit)
            )
        else:
            cursor.execute(
                f"SELECT * FROM jobs ORDER BY {order_by} LIMIT ?",
                (limit,)
            )
        return [row_to_job(r) for r in cursor.fetchall()]

    def update_job(self, job_id: str, **kwargs: Any) -> Optional[Job]:
        if not kwargs:
            return self.get_job(job_id)

        kwargs["updated_at"] = utc_now_iso()
        fields = []
        values = []
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            if isinstance(v, (list, dict)):
                values.append(json.dumps(v))
            elif isinstance(v, JobStatus):
                values.append(v.value)
            else:
                values.append(v)
        values.append(job_id)

        sql = f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?"
        with self.conn:
            self.conn.execute(sql, values)
        return self.get_job(job_id)

    def acquire_next_queued_job(self, lease_owner: str, lease_duration_s: int = 60) -> Optional[Job]:
        """Kuyrukta bekleyen ve bağımlılıkları tamamlanmış en yüksek öncelikli işi atomik olarak alır.
        
        Kira süresi ve attempt sayısını günceller.
        """
        now = utc_now_iso()
        cursor = self.conn.cursor()

        # Bağımlılığı henüz bitmemiş işleri filtrele
        cursor.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'queued'
            ORDER BY priority DESC, created_at ASC
            """
        )
        candidates = [row_to_job(r) for r in cursor.fetchall()]
        for candidate in candidates:
            # Bağımlılık kontrolü: Tanımlı tüm bağımlılıkların bitmiş (integrated/promoted) olması gerekir
            if candidate.depends_on:
                cursor.execute(
                    f"SELECT count(*) as done_count FROM jobs WHERE id IN ({','.join(['?']*len(candidate.depends_on))}) AND status IN ('integrated', 'promoted')",
                    candidate.depends_on
                )
                done_cnt = cursor.fetchone()["done_count"]
                if done_cnt < len(candidate.depends_on):
                    continue  # Henüz tüm bağımlılıklar tamamlanmamış

            # Bu işi atomik olarak al
            from datetime import timedelta
            lease_until_dt = datetime.now(timezone.utc) + timedelta(seconds=lease_duration_s)
            lease_until_str = lease_until_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            with self.conn:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = 'running',
                        lease_owner = ?,
                        lease_until = ?,
                        attempt = attempt + 1,
                        started_at = coalesce(started_at, ?),
                        updated_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    (lease_owner, lease_until_str, now, now, candidate.id)
                )
                if cursor.rowcount > 0:
                    # Olay günlüğü
                    self.conn.execute(
                        """
                        INSERT INTO events (ts, job_id, agent_id, type, level, payload_json)
                        VALUES (?, ?, ?, 'job.acquired', 'info', ?)
                        """,
                        (now, candidate.id, lease_owner, json.dumps({"attempt": candidate.attempt + 1}))
                    )
                    return self.get_job(candidate.id)
        return None
