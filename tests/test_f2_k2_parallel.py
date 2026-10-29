"""F2 Kabul Testi K2: 4 Paralel İşçi Testi.

K2: 4 paralel iş kuyruğa alınır, supervisor max_parallel=4 ile çalışır
ve tüm işler eşzamanlı tamamlanıp awaiting_review olur.
"""

import sys
import os
import time
from pathlib import Path

from agentbus.db import get_connection, init_db
from agentbus.models import JobStatus
from agentbus.store.jobs import JobsStore
from agentbus.supervisor import Supervisor

FAKE_AGY_PATH = str(Path(__file__).parent / "fake_agy.py")


def test_k2_four_parallel_jobs(tmp_path):
    home_dir = tmp_path / ".data"
    home_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(home_dir / "bus.db")
    init_db(conn)

    jobs_store = JobsStore(conn)

    os.environ["FAKE_AGY_MODE"] = ""  # Normal mod

    # 4 paralel iş oluştur
    job_ids = []
    for i in range(1, 5):
        j = jobs_store.create_job(
            title=f"Paralel İş #{i}",
            task_md=f"Görev detayı #{i}",
            priority=5,
        )
        job_ids.append(j.id)

    assert len(job_ids) == 4

    # Supervisor başlat (max_parallel=4)
    sup = Supervisor(
        home_dir=home_dir,
        max_parallel=4,
        agy_bin=FAKE_AGY_PATH,
        lease_duration_s=60,
    )

    import threading
    sup_thread = threading.Thread(target=sup.start, daemon=True)
    sup_thread.start()

    # Tüm işlerin bitmesini bekle (en çok 15 sn)
    start_time = time.time()
    all_done = False
    while time.time() - start_time < 15:
        statuses = [jobs_store.get_job(jid).status for jid in job_ids]
        if all(st == JobStatus.AWAITING_REVIEW for st in statuses):
            all_done = True
            break
        time.sleep(0.2)

    sup.stop()

    assert all_done, f"Tüm 4 iş awaiting_review olamadı! Durumlar: {statuses}"
    for jid in job_ids:
        j = jobs_store.get_job(jid)
        assert j.status == JobStatus.AWAITING_REVIEW
        assert j.result_summary is not None
