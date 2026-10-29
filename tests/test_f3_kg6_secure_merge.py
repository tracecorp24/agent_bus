import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest

from agentbus.db import get_connection, init_db, transition
from agentbus.models import JobStatus, Job, utc_now_iso
from agentbus.store.jobs import JobsStore
from agentbus.store.meta import MetaStore
from agentbus.profiles import RepoProfile
from agentbus.worktree import (
    create_worktree,
    integrate_job,
    promote_repo,
    revert_job,
    run_git,
    get_or_create_integration_worktree
)


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    """Geçici ve izole bir git test deposu oluşturur."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)

    git_config = repo_dir / ".git" / "config"
    with open(git_config, "a", encoding="utf-8") as f:
        f.write("\n[user]\n\tname = Test User\n\temail = test@agentbus.local\n[core]\n\tautocrlf = false\n")

    # Başlangıç dosyaları
    (repo_dir / "README.md").write_text("# Test Repo\nSatir 1\n", encoding="utf-8")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "app.py").write_text("def run():\n    return 'v1'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)

    return repo_dir


def test_kg6a_dirty_working_tree_promoted_aborts_without_touching(temp_git_repo, tmp_path):
    """K-G6a: Kullanıcı çalışma kopyası kirli ise terfi ASLA dokunmaz ve uyarır."""
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    job = jobs.create_job(
        title="Job 1 Clean",
        task_md="Modify app.py",
        repo=str(temp_git_repo)
    )
    wt_dir = home / "worktrees"
    wt_path, branch, base_c = create_worktree(temp_git_repo, job.id, wt_dir)
    jobs.update_job(job.id, worktree_path=str(wt_path), branch=branch, base_commit=base_c)

    # Worktree'de temiz bir geliştirme yap
    (wt_path / "src" / "feature.py").write_text("def new_feature(): return True\n", encoding="utf-8")
    transition(conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW)

    # Aşama 1: Entegrasyon başarılı olmalı
    ok_int, msg_int = integrate_job(conn, home, jobs.get_job(job.id))
    assert ok_int is True, msg_int
    assert jobs.get_job(job.id).status == JobStatus.INTEGRATED

    # Şimdi kullanıcının ana reposunu KİRLİ yapalım (staged veya unstaged dosya)
    dirty_file = temp_git_repo / "user_work.txt"
    dirty_content = "Kullanicinin henuz kaydetmedigi cok onemli kodlari"
    dirty_file.write_text(dirty_content, encoding="utf-8")

    # Kullanıcının main commit HEAD'ini kaydet
    _, main_head_before, _ = run_git(["rev-parse", "HEAD"], cwd=temp_git_repo)

    # Aşama 2: Terfi dene!
    ok_prom, msg_prom = promote_repo(conn, home, temp_git_repo)
    assert ok_prom is False
    assert "KİRLİ" in msg_prom

    # Güvenlik doğrulaması:
    # 1. Kullanıcı dosyası silinmedi veya değiştirilmedi
    assert dirty_file.exists()
    assert dirty_file.read_text(encoding="utf-8") == dirty_content
    # 2. main dalı ilerlemedi
    _, main_head_after, _ = run_git(["rev-parse", "HEAD"], cwd=temp_git_repo)
    assert main_head_after == main_head_before

    # Kullanıcı reposunu temizleyince terfi başarılı olmalı
    dirty_file.unlink()
    ok_prom2, msg_prom2 = promote_repo(conn, home, temp_git_repo)
    assert ok_prom2 is True, msg_prom2
    assert jobs.get_job(job.id).status == JobStatus.PROMOTED


def test_kg6b_conflicting_jobs_second_marked_conflict_integration_clean(temp_git_repo, tmp_path):
    """K-G6b: Çakışan iki işten ikincisi conflict olur, entegrasyon dalı bozulmaz, ilkinin sonucu korunur."""
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    wt_dir = home / "worktrees"

    # İki iş oluştur
    job_a = jobs.create_job(title="Job A", task_md="Change app.py v1->v2_A", repo=str(temp_git_repo))
    job_b = jobs.create_job(title="Job B", task_md="Change app.py v1->v2_B", repo=str(temp_git_repo))

    wt_a, br_a, base_a = create_worktree(temp_git_repo, job_a.id, wt_dir)
    jobs.update_job(job_a.id, worktree_path=str(wt_a), branch=br_a, base_commit=base_a)

    wt_b, br_b, base_b = create_worktree(temp_git_repo, job_b.id, wt_dir)
    jobs.update_job(job_b.id, worktree_path=str(wt_b), branch=br_b, base_commit=base_b)

    # İkisi de aynı satırı çakışacak şekilde değiştirir
    (wt_a / "src" / "app.py").write_text("def run():\n    return 'v2_A_conflict'\n", encoding="utf-8")
    (wt_b / "src" / "app.py").write_text("def run():\n    return 'v2_B_conflict'\n", encoding="utf-8")

    transition(conn, job_a.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job_a.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW)

    transition(conn, job_b.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job_b.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW)

    # 1. Job A başarıyla entegre edilir
    ok_a, msg_a = integrate_job(conn, home, jobs.get_job(job_a.id))
    assert ok_a is True, msg_a
    assert jobs.get_job(job_a.id).status == JobStatus.INTEGRATED

    # 2. Job B entegre edilmeye çalışılır -> çakışır
    ok_b, msg_b = integrate_job(conn, home, jobs.get_job(job_b.id))
    assert ok_b is False
    assert "çakıştı" in msg_b or "conflict" in msg_b.lower()
    assert jobs.get_job(job_b.id).status == JobStatus.CONFLICT

    # 3. Entegrasyon worktree'si temiz olmalı (çakışma artığı kalmamalı)
    int_wt, _ = get_or_create_integration_worktree(temp_git_repo, home)
    _, status_int, _ = run_git(["status", "--porcelain"], cwd=int_wt)
    assert status_int == ""

    # 4. Job A'nın içeriği entegrasyon dalında korunmalı
    app_content_int = (int_wt / "src" / "app.py").read_text(encoding="utf-8")
    assert "v2_A_conflict" in app_content_int


def test_kg6c_test_failure_rolls_back_integration(temp_git_repo, tmp_path):
    """K-G6c: Test kırılan birleştirme geri alınır; main ve entegrasyon dalı ilerlemez."""
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    job = jobs.create_job(
        title="Job Broken Test",
        task_md="Introduce broken test",
        repo=str(temp_git_repo)
    )
    wt_dir = home / "worktrees"
    wt_path, branch, base_c = create_worktree(temp_git_repo, job.id, wt_dir)
    jobs.update_job(job.id, worktree_path=str(wt_path), branch=branch, base_commit=base_c)

    (wt_path / "broken.txt").write_text("broken\n", encoding="utf-8")

    transition(conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW)

    int_wt, _ = get_or_create_integration_worktree(temp_git_repo, home)
    _, head_before, _ = run_git(["rev-parse", "HEAD"], cwd=int_wt)

    # Başarısız test komutlu profil
    failing_profile = RepoProfile(
        name="failing_profile",
        test_command="python -c \"import sys; sys.exit(1)\""
    )

    ok, msg = integrate_job(conn, home, jobs.get_job(job.id), repo_profile=failing_profile)
    assert ok is False
    assert "başarısız" in msg.lower()
    assert jobs.get_job(job.id).status == JobStatus.TESTS_FAILED

    # Entegrasyon dalı başa dönmeli
    _, head_after, _ = run_git(["rev-parse", "HEAD"], cwd=int_wt)
    assert head_after == head_before


def test_kg6d_interrupted_merge_recovery_and_revert(temp_git_repo, tmp_path):
    """K-G6d: Süreç öldürülüp yarım kilit veya yarım merge kalsa bile toparlanır; revert_job çalışır."""
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    meta = MetaStore(conn)

    # 1. Eski (süresi dolmuş) bir kilit bırak
    from agentbus.worktree import get_repo_id
    repo_id = get_repo_id(temp_git_repo)
    lock_key = f"integration_lock:{repo_id}"
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta.set(lock_key, f"stale_job:{old_time}")

    # Yeni iş entegre et: eski kilit otomatik kırılmalı ve işlem başarıyla bitmeli
    job = jobs.create_job(title="Job Recovery", task_md="Test recovery", repo=str(temp_git_repo))
    wt_dir = home / "worktrees"
    wt_path, branch, base_c = create_worktree(temp_git_repo, job.id, wt_dir)
    jobs.update_job(job.id, worktree_path=str(wt_path), branch=branch, base_commit=base_c)
    (wt_path / "recovered.txt").write_text("recovered\n", encoding="utf-8")

    transition(conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW)

    ok, msg = integrate_job(conn, home, jobs.get_job(job.id))
    assert ok is True, msg
    assert jobs.get_job(job.id).status == JobStatus.INTEGRATED

    # 2. revert_job testi: Bu işin merge commit'ini entegrasyon dalından geri al
    ok_rev, msg_rev = revert_job(conn, home, jobs.get_job(job.id))
    assert ok_rev is True, msg_rev

    int_wt, _ = get_or_create_integration_worktree(temp_git_repo, home)
    assert not (int_wt / "recovered.txt").exists()
