"""Durum makinesi (state machine) ve geçiş testleri."""

import pytest
import sqlite3
import json
from agentbus.db import init_db, transition
from agentbus.models import JobStatus, InvalidTransitionError
from agentbus.store.jobs import JobsStore


@pytest.fixture
def db_conn(tmp_path):
    db_file = tmp_path / "test_bus.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)
    return conn


def test_valid_transitions(db_conn):
    store = JobsStore(db_conn)
    job = store.create_job(title="Test İş", task_md="Görev açıklaması")
    assert job.status == JobStatus.QUEUED

    # queued -> running
    transition(db_conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING, reason="İşçi başladı")
    updated = store.get_job(job.id)
    assert updated.status == JobStatus.RUNNING
    assert updated.started_at is not None

    # running -> awaiting_review
    transition(db_conn, job.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW, reason="Ajan tamamladı")
    updated = store.get_job(job.id)
    assert updated.status == JobStatus.AWAITING_REVIEW

    # awaiting_review -> integrated
    transition(db_conn, job.id, JobStatus.AWAITING_REVIEW, JobStatus.INTEGRATED, reason="Merge başarılı")
    updated = store.get_job(job.id)
    assert updated.status == JobStatus.INTEGRATED

    # integrated -> promoted
    transition(db_conn, job.id, JobStatus.INTEGRATED, JobStatus.PROMOTED, reason="Main branch terfisi yapıldı")
    updated = store.get_job(job.id)
    assert updated.status == JobStatus.PROMOTED
    assert updated.finished_at is not None

    # Olay kayıtlarının kontrolü
    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM events WHERE job_id = ? AND type = 'job.transition' ORDER BY id ASC", (job.id,))
    events = cursor.fetchall()
    assert len(events) == 4
    first_payload = json.loads(events[0]["payload_json"])
    assert first_payload["from_status"] == "queued"
    assert first_payload["to_status"] == "running"
    assert first_payload["reason"] == "İşçi başladı"


def test_invalid_transitions(db_conn):
    store = JobsStore(db_conn)
    job = store.create_job(title="Geçersiz Geçiş Testi", task_md="...")

    # queued -> promoted (doğrudan terfi yasak)
    with pytest.raises(InvalidTransitionError) as exc:
        transition(db_conn, job.id, JobStatus.QUEUED, JobStatus.PROMOTED, reason="Hatalı atlama")
    assert "geçersiz durum geçişi" in str(exc.value)

    # Durum değişmemiş olmalı
    updated = store.get_job(job.id)
    assert updated.status == JobStatus.QUEUED

    # Yanlış from_status verilirse
    with pytest.raises(InvalidTransitionError) as exc:
        transition(db_conn, job.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW, reason="Uyuşmazlık")
    assert "fakat veritabanındaki durum 'queued'" in str(exc.value)


def test_needs_input_and_retry_flow(db_conn):
    store = JobsStore(db_conn)
    job = store.create_job(title="Soru Akışı", task_md="...")

    transition(db_conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(db_conn, job.id, JobStatus.RUNNING, JobStatus.NEEDS_INPUT, reason="Soru soruldu")
    assert store.get_job(job.id).status == JobStatus.NEEDS_INPUT

    # Cevap verilince tekrar queued olur
    transition(db_conn, job.id, JobStatus.NEEDS_INPUT, JobStatus.QUEUED, reason="Kullanıcı yanıtladı")
    assert store.get_job(job.id).status == JobStatus.QUEUED


def test_interrupted_recovery_flow(db_conn):
    store = JobsStore(db_conn)
    job = store.create_job(title="Kurtarma Akışı", task_md="...")

    transition(db_conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    # Süreç çöktü veya kira düştü -> interrupted
    transition(db_conn, job.id, JobStatus.RUNNING, JobStatus.INTERRUPTED, reason="Kira süresi doldu")
    assert store.get_job(job.id).status == JobStatus.INTERRUPTED

    # Otomatik queued
    transition(db_conn, job.id, JobStatus.INTERRUPTED, JobStatus.QUEUED, reason="Supervisor yeniden kuyruğa aldı")
    assert store.get_job(job.id).status == JobStatus.QUEUED
