"""Antigravity (agy) tek tur çalıştırıcı (Runner).

Windows Job Object (G1), Stdin NDJSON (G2), Tek yazar (G3),
Sonuç JSON ayrıştırma (G4), UTF-8 (G13) ve Durgunluk kontrolü (G18) sağlar.
"""

import sys
import os
import json
import time
import subprocess
import ctypes
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import psutil

from agentbus.db import get_connection, transition
from agentbus.models import JobStatus, TurnKind, TurnStatus, utc_now_iso, Job, Turn
from agentbus.store.jobs import JobsStore
from agentbus.store.turns import TurnsStore
from agentbus.store.events import EventsStore
from agentbus.prompts import (
    RESULT_JSON_SCHEMA_STR,
    SYSTEM_CONTRACT_PROMPT,
    RESUME_PROMPT_TEMPLATE,
)

# Windows Job Object sabitleri (G1)
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryLimit", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


def create_kill_on_close_job_object():
    """Kapanışta tüm çocuk süreçleri öldüren bir Windows Job Object oluşturur."""
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        res = kernel32.SetInformationJobObject(
            job_handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not res:
            kernel32.CloseHandle(job_handle)
            return None
        return job_handle
    except Exception:
        return None


def assign_process_to_job(job_handle, proc_handle):
    """Süreci Windows Job Object'e bağlar."""
    if sys.platform != "win32" or not job_handle:
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        return bool(kernel32.AssignProcessToJobObject(job_handle, proc_handle))
    except Exception:
        return False


class AgyRunner:
    def __init__(
        self,
        conn,
        home_dir: Path,
        agy_bin: Optional[str] = None,
        stall_timeout_s: float = 600.0,
    ):
        self.conn = conn
        self.home_dir = home_dir
        self.agy_bin = agy_bin or os.environ.get("AGENTBUS_AGY_BIN", "agy")
        self.stall_timeout_s = stall_timeout_s
        self.jobs_store = JobsStore(conn)
        self.turns_store = TurnsStore(conn)
        self.events_store = EventsStore(conn)

    def prepare_prompt(self, job: Job, kind: TurnKind, followup_text: Optional[str] = None) -> str:
        """Tur türüne göre istem metnini hazırlar."""
        if kind == TurnKind.INITIAL:
            parts = [SYSTEM_CONTRACT_PROMPT.strip(), f"## GÖREV: {job.title}", job.task_md]
            if job.allowed_paths:
                parts.append(f"İzinli Dosya Yolları: {', '.join(job.allowed_paths)}")
            return "\n\n".join(parts)
        elif kind == TurnKind.RESUME:
            return RESUME_PROMPT_TEMPLATE.strip()
        elif kind == TurnKind.FOLLOWUP:
            return followup_text or "Lütfen göreve devam et ve tamamla."
        elif kind == TurnKind.REVIEW:
            return f"Üst ajan inceleme notu: {followup_text}\nGereken düzeltmeleri yap ve rapor ver."
        return job.task_md

    def run_turn(
        self,
        job_id: str,
        kind: TurnKind = TurnKind.INITIAL,
        followup_text: Optional[str] = None,
        cwd_override: Optional[str] = None,
    ) -> Tuple[TurnStatus, Dict[str, Any]]:
        """İş için tek bir agy turunu baştan sona çalıştırır ve kaydeder."""
        job = self.jobs_store.get_job(job_id)
        if not job:
            raise ValueError(f"İş bulunamadı: {job_id}")

        # G3: İnsan bağlıyken tur başlatılamaz!
        if job.status in [JobStatus.HUMAN_ATTACHED, JobStatus.ATTACH_PENDING]:
            raise RuntimeError(f"İş [{job_id}] durumunda insan oturumu açık ({job.status.value}). Tur başlatılamaz.")

        # Dizin ve dosya hazırlığı
        run_dir = self.home_dir / "runs" / job_id
        turns_dir = run_dir / "turns"
        turns_dir.mkdir(parents=True, exist_ok=True)

        prompt_text = self.prepare_prompt(job, kind, followup_text)

        # Tur nesnesini veritabanında oluştur (seq belirlenir)
        turn = self.turns_store.create_turn(
            job_id=job.id,
            kind=kind,
            prompt=prompt_text,
        )

        seq_str = f"{turn.seq:03d}"
        prompt_file = turns_dir / f"{seq_str}.prompt.md"
        stream_file = turns_dir / f"{seq_str}.stream.jsonl"
        result_file = turns_dir / f"{seq_str}.result.json"
        log_file = run_dir / "agy.log"

        prompt_file.write_text(prompt_text, encoding="utf-8")
        self.turns_store.update_turn(job.id, turn.seq, raw_path=str(stream_file))

        # Komut inşası
        work_dir = cwd_override or job.worktree_path or str(self.home_dir)
        cmd = [
            self.agy_bin,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--model", "gemini-3.8-flash-high",
            "--dangerously-skip-permissions",
            "--json-schema", RESULT_JSON_SCHEMA_STR,
            "--log-file", str(log_file),
        ]
        if job.conversation_id:
            cmd.extend(["--conversation", job.conversation_id])

        # Eğer sahte agy scripti ise python ile çalıştır
        if self.agy_bin.endswith(".py"):
            cmd = [sys.executable] + cmd

        # G1: Windows Job Object oluştur
        job_obj = create_kill_on_close_job_object()

        # Ortam değişkenleri (G8, G13, G16)
        env = dict(os.environ)
        env["AGENTBUS_HOME"] = str(self.home_dir)
        env["AGENTBUS_JOB_ID"] = job.id
        env["AGENTBUS_ROLE"] = "agent"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        # G2: Stdin'den verilecek tek satırlık NDJSON
        input_payload = json.dumps({
            "event": "user",
            "message": {"content": prompt_text}
        }, ensure_ascii=False) + "\n"

        start_time = time.time()
        turn_status = TurnStatus.FAILED
        structured_result: Dict[str, Any] = {}
        raw_lines = []

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work_dir,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                bufsize=1,  # Line-buffered
            )

            # G1: Süreci Job Object'e bağla ve PID/create_time kaydet
            if job_obj:
                kernel32 = ctypes.windll.kernel32
                # PROCESS_ALL_ACCESS = 0x1FFFFF
                proc_handle = kernel32.OpenProcess(0x1FFFFF, False, proc.pid)
                if proc_handle:
                    assign_process_to_job(job_obj, proc_handle)
                    kernel32.CloseHandle(proc_handle)

            p_create_time = None
            try:
                p_create_time = psutil.Process(proc.pid).create_time()
            except Exception:
                pass

            self.turns_store.update_turn(
                job.id, turn.seq,
                pid=proc.pid,
                process_create_time=p_create_time
            )

            # G2: Stdin'e istemi yaz ve kapat
            if proc.stdin:
                proc.stdin.write(input_payload)
                proc.stdin.flush()
                proc.stdin.close()

            last_activity = time.time()

            # Stream okuma döngüsü (G14, G18)
            with open(stream_file, "a", encoding="utf-8") as sf:
                while True:
                    line = proc.stdout.readline() if proc.stdout else ""
                    if not line:
                        if proc.poll() is not None:
                            break
                        # Durgunluk kontrolü (G18)
                        if time.time() - last_activity > self.stall_timeout_s:
                            self.events_store.emit_event(
                                "turn.stalled",
                                job_id=job.id,
                                level="warn",
                                payload={"stall_s": self.stall_timeout_s}
                            )
                            proc.kill()
                            turn_status = TurnStatus.INTERRUPTED
                            break
                        time.sleep(0.05)
                        continue

                    last_activity = time.time()
                    sf.write(line)
                    sf.flush()
                    line_str = line.strip()
                    if not line_str:
                        continue

                    raw_lines.append(line_str)

                    # JSON olayını incele
                    try:
                        evt_obj = json.loads(line_str)
                    except Exception:
                        continue

                    evt_type = evt_obj.get("event")

                    # İlk satırda conversation_id görülür görülmez kaydet!
                    if evt_type == "init":
                        cid = evt_obj.get("conversation_id")
                        if cid and not job.conversation_id:
                            self.jobs_store.update_job(job.id, conversation_id=cid)
                            job.conversation_id = cid

                    # Araç çağrısı özeti (G14)
                    elif evt_type == "step_update":
                        su = evt_obj.get("step_update", {})
                        if su.get("step_type") == "tool" and su.get("state") == "ACTIVE":
                            self.events_store.emit_event(
                                "tool.call",
                                job_id=job.id,
                                payload={
                                    "tool": su.get("tool_name"),
                                    "params": su.get("tool_info", {}).get("parameters")
                                }
                            )

                    elif evt_type == "result":
                        res_data = evt_obj.get("result", {})
                        # structured_output varsa al
                        if "structured_output" in res_data:
                            structured_result = res_data["structured_output"]
                        elif "response" in res_data:
                            try:
                                structured_result = json.loads(res_data["response"])
                            except Exception:
                                pass

            proc.wait(timeout=10)
            duration = time.time() - start_time

            # G4: Durumu yalnız sonuç JSON'undan çıkar
            res_status = structured_result.get("status")
            if res_status == "done":
                turn_status = TurnStatus.COMPLETED
            elif res_status == "needs_input":
                turn_status = TurnStatus.COMPLETED  # Tur bitti ama iş needs_input olacak
            elif res_status in ["failed", "blocked"]:
                turn_status = TurnStatus.FAILED
            else:
                # Geçerli sözleşme JSON'u yoksa
                if turn_status != TurnStatus.INTERRUPTED:
                    turn_status = TurnStatus.FAILED
                    structured_result = {
                        "status": "failed",
                        "summary": "Ajan sözleşmesine uygun sonuç JSON'u üretilemedi.",
                        "files_changed": [],
                        "tests": "",
                        "question": None
                    }

            result_file.write_text(json.dumps(structured_result, indent=2, ensure_ascii=False), encoding="utf-8")

            self.turns_store.update_turn(
                job.id,
                turn.seq,
                status=turn_status,
                response=json.dumps(structured_result, ensure_ascii=False),
                duration_s=duration,
                finished_at=utc_now_iso(),
            )

        except Exception as e:
            duration = time.time() - start_time
            turn_status = TurnStatus.FAILED
            self.turns_store.update_turn(
                job.id,
                turn.seq,
                status=TurnStatus.FAILED,
                duration_s=duration,
                finished_at=utc_now_iso(),
            )
            structured_result = {"status": "failed", "summary": str(e), "files_changed": [], "tests": "", "question": None}

        finally:
            if job_obj and sys.platform == "win32":
                ctypes.windll.kernel32.CloseHandle(job_obj)

        return turn_status, structured_result
