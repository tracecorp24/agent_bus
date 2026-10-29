"""F2 Kabul Testi K1: Süreç öldürme ve kesintisiz kurtarma testi.

K1: fake_agy ortasında taskkill /F ile öldürülür, ardından agentbus up/recover
aynı conversation_id ile devam eder ve hiçbir tur kaydı kaybolmaz.
"""

import sys
import os
import time
import threading
import subprocess
from pathlib import Path
import psutil

from agentbus.db import get_connection, init_db
from agentbus.models import JobStatus, TurnKind, TurnStatus
from agentbus.store.jobs import JobsStore
from agentbus.store.turns import TurnsStore
from agentbus.supervisor import Supervisor

FAKE_AGY_PATH = str(Path(__file__).parent / "fake_agy.py")


def test_k1_kill_and_recover_without_losing_turns(tmp_path):
    home_dir = tmp_path / ".data"
    home_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(home_dir / "bus.db")
    init_db(conn)

    jobs_store = JobsStore(conn)
    turns_store = TurnsStore(conn)

    # 1. İş oluştur
    job = jobs_store.create_job(
        title="K1 Kesinti Test İşi",
        task_md="Bu iş yarıda kesilecek ve kurtarılacak."
    )
    assert job.status == JobStatus.QUEUED

    # 2. Süreç çalışırken supervisor çökmüş gibi bir durum simüle edelim:
    # Sahte agy'yi arka planda hang modunda başlatalım
    cmd = [
        sys.executable, FAKE_AGY_PATH,
        "--output-format", "stream-json",
        "--fake-hang"
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # İlk satırı (init) okuyup conversation_id'yi al
    first_line = proc.stdout.readline()
    import json
    init_obj = json.loads(first_line)
    conv_id = init_obj["conversation_id"]

    # Bu işi DB'de RUNNING ve 1. turu RUNNING olarak kaydedelim
    jobs_store.update_job(
        job.id,
        status=JobStatus.RUNNING,
        conversation_id=conv_id,
        lease_owner="crashed_supervisor",
        lease_until="2000-01-01T00:00:00Z"  # Süresi dolmuş kira
    )
    turn1 = turns_store.create_turn(
        job_id=job.id,
        kind=TurnKind.INITIAL,
        prompt="İlk istem",
        pid=proc.pid,
        process_create_time=psutil.Process(proc.pid).create_time()
    )

    assert psutil.pid_exists(proc.pid), "Agy süreci çalışıyor olmalı"

    # 3. Şimdi yeni bir Supervisor başlatalım ve recover() çağıralım
    sup = Supervisor(
        home_dir=home_dir,
        max_parallel=1,
        agy_bin=FAKE_AGY_PATH,
        lease_duration_s=60,
    )

    # recover() yetim süreci öldürmeli, turu interrupted yapmalı ve işi queued'a almalı!
    rec_count = sup.recover()
    assert rec_count == 1, "Asılı iş kurtarılmış olmalı"

    # G1 Kontrolü: Yetim süreç gerçekten öldürülmüş olmalı!
    time.sleep(0.5)
    assert not psutil.pid_exists(proc.pid), "Yetim agy süreci supervisor tarafından öldürülmüş olmalı"

    # Tur 1 INTERRUPTED olarak korunmalı (asla silinmemeli!)
    t1_check = turns_store.get_turn(job.id, 1)
    assert t1_check.status == TurnStatus.INTERRUPTED

    job_after_rec = jobs_store.get_job(job.id)
    assert job_after_rec.status == JobStatus.QUEUED
    assert job_after_rec.conversation_id == conv_id, "conversation_id korunmuş olmalı"

    # 4. İkinci turu normal çalıştır (devam turu - resume)
    os.environ["FAKE_AGY_MODE"] = ""  # Normal mod
    worker_t = threading.Thread(target=sup._worker_thread, args=(job.id,), daemon=True)
    with conn:
        conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job.id,))
    worker_t.start()
    worker_t.join(timeout=10)

    # 5. Doğrulamalar:
    # Toplam 2 tur olmalı, hiçbiri kaybolmamalı
    final_turns = turns_store.list_turns(job.id)
    assert len(final_turns) == 2, "Hiçbir tur kaybolmamalı, 2 tur bulunmalı"
    assert final_turns[0].seq == 1
    assert final_turns[0].status == TurnStatus.INTERRUPTED

    # İkinci tur resume türünde olmalı!
    assert final_turns[1].seq == 2
    assert final_turns[1].kind == TurnKind.RESUME
    assert final_turns[1].status == TurnStatus.COMPLETED

    # İş başarıyla awaiting_review olmalı!
    final_job = jobs_store.get_job(job.id)
    assert final_job.status == JobStatus.AWAITING_REVIEW
    assert final_job.conversation_id == conv_id
