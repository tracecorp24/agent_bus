"""F2 Kabul Testi K3: Veritabanı WAL bütünlüğü ve eşzamanlılık testi.

K3: Birden fazla iş parçacığı tarafından 1000 rastgele eşzamanlı yazma/okuma
işlemi yapılır; PRAGMA integrity_check ve PRAGMA quick_check hiçbir bozulma göstermez.
"""

import threading
import random
import time
from pathlib import Path

from agentbus.db import get_connection, init_db, transition
from agentbus.models import JobStatus
from agentbus.store.jobs import JobsStore
from agentbus.store.events import EventsStore
from agentbus.store.messages import MessagesStore


def test_k3_db_wal_integrity_under_concurrency(tmp_path):
    home_dir = tmp_path / ".data"
    home_dir.mkdir(parents=True, exist_ok=True)
    db_file = home_dir / "bus.db"

    # İlk kurulum
    conn = get_connection(db_file)
    init_db(conn)
    conn.close()

    total_operations = 1000
    num_threads = 8
    ops_per_thread = total_operations // num_threads

    errors = []

    def worker(worker_id: int):
        # Her thread kendi SQLite bağlantısını açar
        thread_conn = get_connection(db_file)
        j_store = JobsStore(thread_conn)
        e_store = EventsStore(thread_conn)
        m_store = MessagesStore(thread_conn)

        for i in range(ops_per_thread):
            try:
                op = random.randint(1, 4)
                if op == 1:
                    # İş oluştur
                    j_store.create_job(
                        title=f"W{worker_id} Job {i}",
                        task_md="Metin",
                        priority=random.randint(1, 10)
                    )
                elif op == 2:
                    # Olay bas
                    e_store.emit_event(
                        event_type="test.event",
                        payload={"worker": worker_id, "step": i}
                    )
                elif op == 3:
                    # Mesaj gönder
                    m_store.send_message(
                        from_id=f"worker_{worker_id}",
                        to_id="all",
                        body=f"Eşzamanlı mesaj {i}"
                    )
                elif op == 4:
                    # İşleri listele
                    j_store.list_jobs(limit=10)
            except Exception as e:
                errors.append(f"Worker {worker_id} op {i} error: {e}")
            time.sleep(0.001)

        thread_conn.close()

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(errors) == 0, f"Eşzamanlı işlemler sırasında hatalar oluştu: {errors[:5]}"

    # SQLite bütünlük kontrolü (Integrity check)
    check_conn = get_connection(db_file)
    cursor = check_conn.cursor()

    cursor.execute("PRAGMA integrity_check;")
    res = cursor.fetchall()
    assert len(res) == 1 and res[0][0] == "ok", f"Veritabanı bozuldu! Sonuç: {res}"

    cursor.execute("PRAGMA quick_check;")
    res_quick = cursor.fetchall()
    assert len(res_quick) == 1 and res_quick[0][0] == "ok", f"Quick check başarısız! Sonuç: {res_quick}"

    check_conn.close()
