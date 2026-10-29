"""Agent Bus Supervisor (Daemon).

Zamanlayıcı (en çok 4 paralel iş), kira/kalp atışı yönetimi,
çöküş kurtarma (recovery), 429 geri çekilme ve tek örnek kilidi sağlar.
"""

import sys
import os
import time
import socket
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
import psutil

from agentbus.db import get_connection, transition, get_db_path, get_home_dir
from agentbus.models import JobStatus, TurnKind, TurnStatus, utc_now_iso, Job
from agentbus.store.jobs import JobsStore
from agentbus.store.turns import TurnsStore
from agentbus.store.events import EventsStore
from agentbus.store.messages import MessagesStore
from agentbus.store.agents import AgentsStore
from agentbus.store.meta import MetaStore
from agentbus.runner_agy import AgyRunner


class Supervisor:
    def __init__(
        self,
        home_dir: Optional[Path] = None,
        max_parallel: int = 4,
        agy_bin: Optional[str] = None,
        lease_duration_s: int = 60,
        heartbeat_interval_s: float = 5.0,
    ):
        self.home_dir = home_dir or get_home_dir()
        self.max_parallel = max_parallel
        self.agy_bin = agy_bin
        self.lease_duration_s = lease_duration_s
        self.heartbeat_interval_s = heartbeat_interval_s

        self.supervisor_id = f"sup_{os.getpid()}_{int(time.time())}"
        self.host = socket.gethostname()
        self._running = False
        self._active_workers: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

        self.db_path = get_db_path(str(self.home_dir))
        self.conn = get_connection(self.db_path)
        self.jobs_store = JobsStore(self.conn)
        self.turns_store = TurnsStore(self.conn)
        self.events_store = EventsStore(self.conn)
        self.agents_store = AgentsStore(self.conn)
        self.meta_store = MetaStore(self.conn)

    def acquire_supervisor_lock(self) -> bool:
        """Global tek örnek kilidini (meta.supervisor_lease) alır."""
        now = datetime.now(timezone.utc)
        lease_val = self.meta_store.get("supervisor_lease")
        if lease_val:
            try:
                owner, until_str = lease_val.split(":", 1)
                until_dt = datetime.fromisoformat(until_str.replace("Z", "+00:00"))
                if until_dt > now and owner != self.supervisor_id:
                    return False  # Başka canlı bir supervisor var
            except Exception:
                pass

        new_until = (now + timedelta(seconds=self.lease_duration_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.meta_store.set("supervisor_lease", f"{self.supervisor_id}:{new_until}")
        return True

    def release_supervisor_lock(self) -> None:
        lease_val = self.meta_store.get("supervisor_lease")
        if lease_val and lease_val.startswith(self.supervisor_id):
            self.meta_store.delete("supervisor_lease")

    def renew_supervisor_lock(self) -> None:
        now = datetime.now(timezone.utc)
        new_until = (now + timedelta(seconds=self.lease_duration_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.meta_store.set("supervisor_lease", f"{self.supervisor_id}:{new_until}")

    def recover(self) -> int:
        """Kira süresi dolmuş veya yetim kalmış işleri kurtarır.
        
        G1 gereği yetim agy süreçlerini PID/create_time kontrolüyle öldürür.
        """
        rec_conn = get_connection(self.db_path)
        turns_store = TurnsStore(rec_conn)
        events_store = EventsStore(rec_conn)

        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        recovered_count = 0
        cursor = rec_conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE status = 'running'")
        running_jobs = cursor.fetchall()

        for r in running_jobs:
            job_id = r["id"]
            lease_until = r["lease_until"]
            is_expired = False
            if lease_until:
                try:
                    until_dt = datetime.fromisoformat(lease_until.replace("Z", "+00:00"))
                    if until_dt < now:
                        is_expired = True
                except Exception:
                    is_expired = True
            else:
                is_expired = True

            if is_expired:
                # G1: Yetim süreci bul ve öldür
                latest_turn = turns_store.get_latest_turn(job_id)
                if latest_turn and latest_turn.pid:
                    try:
                        p = psutil.Process(latest_turn.pid)
                        # PID yeniden kullanımı kontrolü (create_time)
                        if latest_turn.process_create_time:
                            if abs(p.create_time() - latest_turn.process_create_time) < 3.0:
                                p.kill()
                        else:
                            p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                # Tur interrupted yap
                if latest_turn and latest_turn.status == TurnStatus.RUNNING:
                    turns_store.update_turn(
                        job_id, latest_turn.seq,
                        status=TurnStatus.INTERRUPTED,
                        finished_at=now_str
                    )

                # İş önce interrupted, ardından otomatik queued yapılır
                transition(rec_conn, job_id, JobStatus.RUNNING, JobStatus.INTERRUPTED, reason="Kira suresi doldu (recover)")
                transition(rec_conn, job_id, JobStatus.INTERRUPTED, JobStatus.QUEUED, reason="Otomatik kurtarma: sira sonraki turda")
                recovered_count += 1
                events_store.emit_event(
                    "job.recovered",
                    job_id=job_id,
                    level="warn",
                    payload={"previous_lease_until": lease_until}
                )

        rec_conn.close()
        return recovered_count

    def _worker_thread(self, job_id: str) -> None:
        """Bir işin turunu çalıştıran işçi iş parçacığı."""
        # Ayrı bir DB bağlantısı (Thread-safety)
        conn = get_connection(self.db_path)
        runner = AgyRunner(conn, self.home_dir, agy_bin=self.agy_bin)
        jobs_store = JobsStore(conn)
        turns_store = TurnsStore(conn)
        messages_store = MessagesStore(conn)

        try:
            job = jobs_store.get_job(job_id)
            if not job:
                return

            # Worktree hazırlığı (§5.2)
            if job.repo and not job.worktree_path:
                from agentbus.worktree import create_worktree
                repo_p = Path(job.repo).resolve()
                if repo_p.exists():
                    wt_dir = self.home_dir / "worktrees"
                    wt_path, branch, base_c = create_worktree(repo_p, job.id, wt_dir, job.base_commit)
                    jobs_store.update_job(
                        job.id,
                        worktree_path=str(wt_path),
                        branch=branch,
                        base_commit=base_c
                    )
                    job = jobs_store.get_job(job_id)

            # Tur türünü belirle: ilk tur mu, resume mi, followup mı?
            latest_turn = turns_store.get_latest_turn(job_id)
            if not latest_turn:
                kind = TurnKind.INITIAL
                followup = None
            elif latest_turn.status == TurnStatus.INTERRUPTED:
                kind = TurnKind.RESUME
                followup = None
            else:
                kind = TurnKind.FOLLOWUP
                # Varsa son gelen okunmamış mesajı al
                inbox = messages_store.get_inbox(job_id, unread_only=True)
                followup = inbox[0].body if inbox else None
                if inbox:
                    messages_store.mark_read(inbox[0].id)

            turn_status, result_data = runner.run_turn(
                job_id=job_id,
                kind=kind,
                followup_text=followup,
            )

            # G4: İşin durumunu sonuca göre güncelle
            res_status = result_data.get("status")
            summary = result_data.get("summary", "")

            # İşi güncelle
            jobs_store.update_job(
                job_id,
                result_summary=summary,
                lease_owner=None,
                lease_until=None
            )

            current_job = jobs_store.get_job(job_id)
            if not current_job or current_job.status != JobStatus.RUNNING:
                return

            if res_status == "done":
                transition(conn, job_id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW, reason="Gorev tamamlandi, inceleme bekliyor")
            elif res_status == "needs_input":
                # Soruyu orkestratöre mesaj olarak da at
                q_text = result_data.get("question") or "Ek bilgi gerekli."
                messages_store.send_message(from_id=job_id, to_id="orchestrator", body=q_text)
                transition(conn, job_id, JobStatus.RUNNING, JobStatus.NEEDS_INPUT, reason=f"Ajan soru sordu: {q_text}")
            elif res_status == "failed":
                if current_job.attempt >= current_job.max_attempts:
                    transition(conn, job_id, JobStatus.RUNNING, JobStatus.FAILED, reason="Maksimum deneme asildi")
                else:
                    transition(conn, job_id, JobStatus.RUNNING, JobStatus.INTERRUPTED, reason="Basarisiz tur, tekrar denenecek")
                    transition(conn, job_id, JobStatus.INTERRUPTED, JobStatus.QUEUED, reason="Tekrar deneme kuyruğuna alindi")
            else:
                # Beklenmeyen durumda inceleme bekle
                transition(conn, job_id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW, reason="Sonuc ayrıştırılamadı, inceleme gerekli")

        except Exception as e:
            try:
                jobs_store.update_job(job_id, error=str(e), lease_owner=None, lease_until=None)
                cur = jobs_store.get_job(job_id)
                if cur and cur.status == JobStatus.RUNNING:
                    transition(conn, job_id, JobStatus.RUNNING, JobStatus.INTERRUPTED, reason=f"Runner hatasi: {e}")
                    transition(conn, job_id, JobStatus.INTERRUPTED, JobStatus.QUEUED, reason="Hata sonrasi kurtarma kuyruga alindi")
            except Exception:
                pass
        finally:
            with self._lock:
                self._active_workers.pop(job_id, None)
            conn.close()

    def _heartbeat_loop(self) -> None:
        """Tüm çalışan işlerin kiralarını ve supervisor kilidini periyodik uzatır."""
        hb_conn = get_connection(self.db_path)
        agents_store = AgentsStore(hb_conn)
        meta_store = MetaStore(hb_conn)
        while self._running:
            try:
                # Kilidi yenile
                now = datetime.now(timezone.utc)
                new_until = (now + timedelta(seconds=self.lease_duration_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
                meta_store.set("supervisor_lease", f"{self.supervisor_id}:{new_until}")
                agents_store.heartbeat_agent(self.supervisor_id)

                with self._lock:
                    active_jobs = list(self._active_workers.keys())

                if active_jobs:
                    new_lease = (now + timedelta(seconds=self.lease_duration_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    with hb_conn:
                        for jid in active_jobs:
                            hb_conn.execute(
                                "UPDATE jobs SET lease_until = ? WHERE id = ? AND status = 'running'",
                                (new_lease, jid)
                            )
            except Exception:
                pass
            time.sleep(self.heartbeat_interval_s)
        hb_conn.close()

    def start(self, run_once: bool = False, max_loops: Optional[int] = None) -> None:
        """Supervisor ana döngüsünü başlatır."""
        start_conn = get_connection(self.db_path)
        meta_store = MetaStore(start_conn)
        agents_store = AgentsStore(start_conn)
        jobs_store = JobsStore(start_conn)

        # Kilidi al
        now = datetime.now(timezone.utc)
        lease_val = meta_store.get("supervisor_lease")
        if lease_val:
            try:
                owner, until_str = lease_val.split(":", 1)
                until_dt = datetime.fromisoformat(until_str.replace("Z", "+00:00"))
                if until_dt > now and owner != self.supervisor_id:
                    start_conn.close()
                    raise RuntimeError("Zaten çalışan başka bir Supervisor oturumu var (Tek-örnek kilidi aktif).")
            except RuntimeError:
                raise
            except Exception:
                pass

        new_until = (now + timedelta(seconds=self.lease_duration_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta_store.set("supervisor_lease", f"{self.supervisor_id}:{new_until}")

        self._running = True
        agents_store.register_agent(
            agent_id=self.supervisor_id,
            pid=os.getpid(),
            host=self.host
        )

        # Başlangıçta yarım kalmış işleri kurtar
        self.recover()

        # Kalp atışı iş parçacığı
        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb_thread.start()

        loops = 0
        try:
            while self._running:
                loops += 1
                is_paused = meta_store.get("paused") == "1"

                with self._lock:
                    active_count = len(self._active_workers)

                if not is_paused and active_count < self.max_parallel:
                    job = jobs_store.acquire_next_queued_job(
                        lease_owner=self.supervisor_id,
                        lease_duration_s=self.lease_duration_s
                    )
                    if job:
                        with self._lock:
                            t = threading.Thread(target=self._worker_thread, args=(job.id,), daemon=True)
                            self._active_workers[job.id] = t
                            t.start()

                if run_once and active_count == 0:
                    break

                if max_loops and loops >= max_loops:
                    break

                time.sleep(0.2)

        finally:
            self._running = False
            agents_store.unregister_agent(self.supervisor_id)
            lease_val = meta_store.get("supervisor_lease")
            if lease_val and lease_val.startswith(self.supervisor_id):
                meta_store.delete("supervisor_lease")
            start_conn.close()

    def run_once(self) -> None:
        """Tek bir zamanlama turu çalıştırır."""
        self._running = True
        conn = get_connection(self.db_path)
        jobs_store = JobsStore(conn)
        meta_store = MetaStore(conn)

        is_paused = meta_store.get("paused") == "1"
        with self._lock:
            active_count = len(self._active_workers)

        if not is_paused and active_count < self.max_parallel:
            job = jobs_store.acquire_next_queued_job(
                lease_owner=self.supervisor_id,
                lease_duration_s=self.lease_duration_s
            )
            if job:
                with self._lock:
                    t = threading.Thread(target=self._worker_thread, args=(job.id,), daemon=True)
                    self._active_workers[job.id] = t
                    t.start()
        conn.close()

    def stop(self, wait_workers: bool = True, timeout: float = 30.0) -> None:
        """Supervisor'ı nazikçe durdurur."""
        self._running = False
        if wait_workers:
            end_time = time.time() + timeout
            while time.time() < end_time:
                with self._lock:
                    if not self._active_workers:
                        break
                time.sleep(0.1)

        self.agents_store.unregister_agent(self.supervisor_id)
        self.release_supervisor_lock()
