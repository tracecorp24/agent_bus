"""Veri deposu (Stores) birim testleri."""

import pytest
import sqlite3
import json
from agentbus.db import init_db
from agentbus.models import JobStatus, TurnKind, TurnStatus
from agentbus.store.jobs import JobsStore
from agentbus.store.turns import TurnsStore
from agentbus.store.events import EventsStore
from agentbus.store.messages import MessagesStore
from agentbus.store.board import BoardStore
from agentbus.store.claims import ClaimsStore
from agentbus.store.agents import AgentsStore
from agentbus.store.meta import MetaStore


@pytest.fixture
def db_conn(tmp_path):
    db_file = tmp_path / "test_store_bus.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)
    return conn


def test_jobs_store_idempotency(db_conn):
    store = JobsStore(db_conn)
    j1 = store.create_job(
        title="İlk Deneme",
        task_md="Görev",
        idempotency_key="plan_abc:job_1"
    )
    assert j1.id is not None

    # Aynı idempotency key ile tekrar çağrılınca aynı iş dönmeli
    j2 = store.create_job(
        title="İkinci Deneme",
        task_md="Farklı metin",
        idempotency_key="plan_abc:job_1"
    )
    assert j2.id == j1.id
    assert j2.title == "İlk Deneme"


def test_jobs_store_acquire_with_dependencies(db_conn):
    store = JobsStore(db_conn)
    # Öncelikli ama bağımlı iş
    j_dep = store.create_job(title="Bağımlı İş", task_md="...", priority=10, depends_on=["j_parent_1"])
    # Bağımsız iş
    j_ready = store.create_job(title="Hazır İş", task_md="...", priority=5)

    # j_parent_1 henüz bitmediği için j_ready alınmalı
    acquired = store.acquire_next_queued_job(lease_owner="worker_1", lease_duration_s=30)
    assert acquired is not None
    assert acquired.id == j_ready.id
    assert acquired.status == JobStatus.RUNNING
    assert acquired.lease_owner == "worker_1"
    assert acquired.attempt == 1


def test_turns_store_lifecycle_and_g1(db_conn):
    jobs_store = JobsStore(db_conn)
    turns_store = TurnsStore(db_conn)
    job = jobs_store.create_job(title="Tur Testi", task_md="...")

    # Tur 1: G1 pid ve process_create_time kontrolü
    t1 = turns_store.create_turn(
        job_id=job.id,
        kind=TurnKind.INITIAL,
        prompt="İlk istem",
        pid=12345,
        process_create_time=1700000000.5
    )
    assert t1.seq == 1
    assert t1.status == TurnStatus.RUNNING
    assert t1.pid == 12345
    assert t1.process_create_time == 1700000000.5

    # Tur 1 tamamla
    turns_store.update_turn(
        job_id=job.id,
        seq=1,
        status=TurnStatus.COMPLETED,
        response="Tamamlandı",
        duration_s=3.2
    )
    t1_updated = turns_store.get_turn(job.id, 1)
    assert t1_updated.status == TurnStatus.COMPLETED
    assert t1_updated.duration_s == 3.2

    # Tur 2 (seq otomatik 2 olmalı)
    t2 = turns_store.create_turn(job_id=job.id, kind=TurnKind.FOLLOWUP, prompt="Ek talimat")
    assert t2.seq == 2


def test_messages_store(db_conn):
    store = MessagesStore(db_conn)
    msg = store.send_message(from_id="job_1", to_id="orchestrator", body="Onay gerekli mi?")
    assert msg.id is not None

    inbox = store.get_inbox("orchestrator", unread_only=True)
    assert len(inbox) == 1
    assert inbox[0].body == "Onay gerekli mi?"

    store.mark_read(msg.id)
    inbox_unread = store.get_inbox("orchestrator", unread_only=True)
    assert len(inbox_unread) == 0


def test_board_store_versioning(db_conn):
    store = BoardStore(db_conn)
    entry1 = store.set_entry("api_contract", "v1 payload", author="job_1")
    assert entry1.version == 1

    entry2 = store.set_entry("api_contract", "v2 payload", author="job_2")
    assert entry2.version == 2
    assert entry2.value == "v2 payload"


def test_claims_store(db_conn):
    store = ClaimsStore(db_conn)
    c = store.claim_path("src/core/**", "job_1")
    assert c.path_glob == "src/core/**"

    claims = store.list_claims("job_1")
    assert len(claims) == 1

    unclaimed = store.unclaim_path("src/core/**", "job_1")
    assert unclaimed is True
    assert len(store.list_claims("job_1")) == 0


def test_agents_store(db_conn):
    store = AgentsStore(db_conn)
    a = store.register_agent("worker_1", pid=9999, host="localhost")
    assert a.id == "worker_1"

    store.heartbeat_agent("worker_1", current_job="job_100")
    agents = store.list_agents()
    assert len(agents) == 1
    assert agents[0].current_job == "job_100"

    store.unregister_agent("worker_1")
    assert len(store.list_agents()) == 0


def test_meta_store(db_conn):
    store = MetaStore(db_conn)
    store.set("max_parallel", "4")
    assert store.get("max_parallel") == "4"
    assert store.get("non_existent", default="10") == "10"
