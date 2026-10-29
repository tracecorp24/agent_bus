import os
import subprocess
from pathlib import Path
import pytest
from agentbus.db import get_connection, init_db, transition
from agentbus.models import JobStatus, Job, utc_now_iso
from agentbus.store.jobs import JobsStore
from agentbus.store.meta import MetaStore
from agentbus.worktree import (
    create_worktree,
    remove_worktree,
    get_diff,
    check_allowed_paths,
    gc_worktrees,
    run_git,
)
from agentbus.cli import build_parser


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    """Geçici ve izole bir git test deposu oluşturur."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)

    git_config = repo_dir / ".git" / "config"
    with open(git_config, "a", encoding="utf-8") as f:
        f.write("\n[user]\n\tname = Test User\n\temail = test@agentbus.local\n[core]\n\tautocrlf = false\n")

    # İlk commit
    (repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)

    return repo_dir


def test_worktree_create_and_diff(temp_git_repo, tmp_path):
    wt_dir = tmp_path / "worktrees"
    job_id = "j_test_01"

    wt_path, branch, base_commit = create_worktree(temp_git_repo, job_id, wt_dir)
    assert wt_path.exists()
    assert branch == f"agentbus/{job_id}"
    assert len(base_commit) == 40

    # Dosya değiştir ve diff al
    app_py = wt_path / "src" / "app.py"
    app_py.write_text("print('hello world!')\n", encoding="utf-8")

    diff = get_diff(wt_path, base_commit)
    assert "print('hello world!')" in diff
    assert "+print('hello world!')" in diff

    # Worktree kaldır
    removed = remove_worktree(temp_git_repo, wt_path, branch)
    assert removed
    assert not wt_path.exists()


def test_allowed_paths_g12(temp_git_repo, tmp_path):
    wt_dir = tmp_path / "worktrees"
    job_id = "j_test_g12"
    wt_path, branch, base_commit = create_worktree(temp_git_repo, job_id, wt_dir)

    allowed = ["src/**", "tests/**"]

    # 1. İzinli dosya düzenleme
    (wt_path / "src" / "feature.py").write_text("def feat(): pass\n", encoding="utf-8")
    disallowed = check_allowed_paths(wt_path, base_commit, allowed)
    assert disallowed == []

    # 2. İzin dışı dosya oluşturma (ör. package.json veya README.md)
    (wt_path / "package.json").write_text("{}", encoding="utf-8")
    disallowed = check_allowed_paths(wt_path, base_commit, allowed)
    assert "package.json" in disallowed

    # Commit edilmiş olsa dahi yakalanmalı
    subprocess.run(["git", "add", "."], cwd=str(wt_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add disallowed file"], cwd=str(wt_path), check=True, capture_output=True)
    disallowed_after_commit = check_allowed_paths(wt_path, base_commit, allowed)
    assert "package.json" in disallowed_after_commit

    remove_worktree(temp_git_repo, wt_path, branch)


def test_cli_diff_and_review(temp_git_repo, tmp_path, capsys):
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    job = jobs.create_job(
        title="Test diff job",
        task_md="Test diff",
        repo=str(temp_git_repo)
    )

    wt_dir = home / "worktrees"
    wt_path, branch, base_c = create_worktree(temp_git_repo, job.id, wt_dir)
    jobs.update_job(job.id, worktree_path=str(wt_path), branch=branch, base_commit=base_c)

    # Dosya ekle
    (wt_path / "test_file.txt").write_text("agent content\n", encoding="utf-8")

    parser = build_parser()

    # diff komutu
    args = parser.parse_args(["--home", str(home), "diff", job.id, "--json"])
    rc = args.func(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "agent content" in captured.out

    # review --reject
    # Önce durumu awaiting_review yap
    transition(conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW)

    args_rej = parser.parse_args(["--home", str(home), "review", job.id, "--reject", "Kod standardı yetersiz", "--json"])
    rc_rej = args_rej.func(args_rej)
    assert rc_rej == 0
    updated_job = jobs.get_job(job.id)
    assert updated_job.status == JobStatus.REJECTED


def test_gc_worktrees(temp_git_repo, tmp_path):
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    job = jobs.create_job(
        title="Promoted Job",
        task_md="Task done",
        repo=str(temp_git_repo)
    )
    wt_dir = home / "worktrees"
    wt_path, branch, base_c = create_worktree(temp_git_repo, job.id, wt_dir)
    jobs.update_job(job.id, worktree_path=str(wt_path), branch=branch, base_commit=base_c)

    transition(conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW)
    transition(conn, job.id, JobStatus.AWAITING_REVIEW, JobStatus.INTEGRATED)
    transition(conn, job.id, JobStatus.INTEGRATED, JobStatus.PROMOTED)

    assert wt_path.exists()
    cleaned = gc_worktrees(conn, home, temp_git_repo)
    assert cleaned == 1
    assert not wt_path.exists()
