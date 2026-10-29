import os
import sys
import subprocess
import json
import time
import threading
import yaml
from pathlib import Path
import pytest

from agentbus.db import get_connection, init_db, transition
from agentbus.models import JobStatus, Job
from agentbus.store.jobs import JobsStore
from agentbus.cli import build_parser
from agentbus.supervisor import Supervisor
from agentbus.worktree import integrate_job, promote_repo, run_git


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    """Geçici ve izole bir git test deposu oluşturur."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)

    git_config = repo_dir / ".git" / "config"
    with open(git_config, "a", encoding="utf-8") as f:
        f.write("\n[user]\n\tname = Test User\n\temail = test@agentbus.local\n[core]\n\tautocrlf = false\n")

    (repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "main.py").write_text("# Main entry\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)

    return repo_dir


def test_plan_apply_atomicity_and_idempotency_g15(tmp_path):
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    plan_data = {
        "goal": "Excel Dışa Aktarma Özelliği",
        "jobs": [
            {
                "key": "model",
                "title": "Veri Modeli",
                "task": "Export modelini tanımla",
                "paths": ["src/models/**"]
            },
            {
                "key": "service",
                "title": "Dışa Aktarma Servisi",
                "task": "Excel yazıcı servisini kur",
                "after": ["model"],
                "paths": ["src/services/**"]
            },
            {
                "key": "api",
                "title": "API Ucu",
                "task": "POST /export endpointini bağla",
                "after": ["service"],
                "paths": ["src/api/**"]
            }
        ]
    }
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(yaml.dump(plan_data, allow_unicode=True), encoding="utf-8")

    parser = build_parser()

    # 1. Planı uygula
    args1 = parser.parse_args(["--home", str(home), "plan", "apply", str(plan_file), "--json"])
    rc1 = args1.func(args1)
    assert rc1 == 0

    jobs_store = JobsStore(conn)
    jobs_list = jobs_store.list_jobs()
    assert len(jobs_list) == 3

    # Bağımlılık zincirini doğrula
    j_model = next(j for j in jobs_list if "Modeli" in j.title)
    j_service = next(j for j in jobs_list if "Servisi" in j.title)
    j_api = next(j for j in jobs_list if "API" in j.title)

    assert j_service.depends_on == [j_model.id]
    assert j_api.depends_on == [j_service.id]

    # 2. İdempotency (G15): Aynı planı tekrar uygula -> yeni iş eklenmemeli
    args2 = parser.parse_args(["--home", str(home), "plan", "apply", str(plan_file), "--json"])
    rc2 = args2.func(args2)
    assert rc2 == 0

    jobs_list2 = jobs_store.list_jobs()
    assert len(jobs_list2) == 3


def test_e2e_3job_scenario_orchestrator(temp_git_repo, tmp_path):
    """§12 F6: 3 işlik plan, supervisor, review, iki aşamalı birleştirme ve terfi."""
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    # 3 işlik plan
    plan_data = {
        "goal": "Uçtan Uca Çoklu Ajan Akışı",
        "repo": str(temp_git_repo),
        "jobs": [
            {
                "key": "step1",
                "title": "Adım 1 - Base Core",
                "task": "src/core.py oluştur",
                "paths": ["src/**"]
            },
            {
                "key": "step2",
                "title": "Adım 2 - Service",
                "task": "src/service.py oluştur",
                "after": ["step1"],
                "paths": ["src/**"]
            },
            {
                "key": "step3",
                "title": "Adım 3 - Utils",
                "task": "src/utils.py oluştur",
                "after": ["step2"],
                "paths": ["src/**"]
            }
        ]
    }
    plan_file = tmp_path / "e2e_plan.yaml"
    plan_file.write_text(yaml.dump(plan_data, allow_unicode=True), encoding="utf-8")

    parser = build_parser()
    args_apply = parser.parse_args(["--home", str(home), "plan", "apply", str(plan_file), "--json"])
    assert args_apply.func(args_apply) == 0

    jobs_store = JobsStore(conn)
    fake_agy_path = str(Path(__file__).parent / "fake_agy.py")

    # Supervisor başlat
    sup = Supervisor(
        home_dir=home,
        agy_bin=fake_agy_path,
        max_parallel=2,
        heartbeat_interval_s=1.0,
    )
    sup_thread = threading.Thread(target=sup.start, daemon=True)
    sup_thread.start()

    def wait_for_status(jid: str, target_status: JobStatus, timeout: float = 60.0) -> Job:
        start_t = time.time()
        while time.time() - start_t < timeout:
            current = jobs_store.get_job(jid)
            if current and current.status == target_status:
                return current
            time.sleep(0.3)
        current = jobs_store.get_job(jid)
        raise TimeoutError(f"İş [{jid}] {timeout}sn içinde '{target_status.value}' durumuna gelemedi (mevcut: {current.status.value if current else None}, error={current.error if current else None})")

    try:
        jobs_all = jobs_store.list_jobs()
        j1_id = next(j.id for j in jobs_all if "step1" in j.title or "Adım 1" in j.title)
        j2_id = next(j.id for j in jobs_all if "step2" in j.title or "Adım 2" in j.title)
        j3_id = next(j.id for j in jobs_all if "step3" in j.title or "Adım 3" in j.title)

        # 1. İş 1 koşulur
        j1 = wait_for_status(j1_id, JobStatus.AWAITING_REVIEW, timeout=60.0)
        assert j1.status == JobStatus.AWAITING_REVIEW

        # İş 1'in worktree'sinde dosya üretilmiş olsun
        assert j1.worktree_path and Path(j1.worktree_path).exists()
        (Path(j1.worktree_path) / "src" / "core.py").write_text("# core v1\n", encoding="utf-8")

        # Orkestratör onaylar ve entegre eder (§15 Aşama 1)
        ok_int1, msg1 = integrate_job(conn, home, j1)
        assert ok_int1 is True, msg1
        assert jobs_store.get_job(j1.id).status == JobStatus.INTEGRATED

        # Main'e terfi et (§15 Aşama 2)
        ok_prom1, msg_p1 = promote_repo(conn, home, temp_git_repo)
        assert ok_prom1 is True, msg_p1
        assert jobs_store.get_job(j1.id).status == JobStatus.PROMOTED

        # 2. İş 2 bağımlılığı (step1 promoted oldu) çözüldüğü için artık çalışabilir!
        j2 = wait_for_status(j2_id, JobStatus.AWAITING_REVIEW, timeout=60.0)
        assert j2.status == JobStatus.AWAITING_REVIEW
        (Path(j2.worktree_path) / "src" / "service.py").write_text("# service v1\n", encoding="utf-8")

        ok_int2, msg2 = integrate_job(conn, home, j2)
        assert ok_int2 is True, msg2
        ok_prom2, _ = promote_repo(conn, home, temp_git_repo)
        assert ok_prom2 is True
        assert jobs_store.get_job(j2.id).status == JobStatus.PROMOTED

        # 3. İş 3 çalışır
        j3 = wait_for_status(j3_id, JobStatus.AWAITING_REVIEW, timeout=60.0)
        assert j3.status == JobStatus.AWAITING_REVIEW
        (Path(j3.worktree_path) / "src" / "utils.py").write_text("# utils v1\n", encoding="utf-8")

        ok_int3, msg3 = integrate_job(conn, home, j3)
        assert ok_int3 is True, msg3
        ok_prom3, _ = promote_repo(conn, home, temp_git_repo)
        assert ok_prom3 is True
        assert jobs_store.get_job(j3.id).status == JobStatus.PROMOTED

        # Sonuç doğrulaması: Hedef repoda main dalı tüm dosyaları içermeli
        assert (temp_git_repo / "src" / "core.py").exists()
        assert (temp_git_repo / "src" / "service.py").exists()
        assert (temp_git_repo / "src" / "utils.py").exists()

        # Git log'unda her 3 işin merge commit'i bulunmalı
        rc_log, log_out, _ = run_git(["log", "--oneline"], cwd=temp_git_repo)
        assert "Merge job" in log_out
    finally:
        sup.stop()
