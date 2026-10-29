import os
import sys
import subprocess
import json
from pathlib import Path
import pytest

from agentbus.db import get_connection, init_db, transition
from agentbus.models import JobStatus, Job, TurnKind
from agentbus.store.jobs import JobsStore
from agentbus.store.messages import MessagesStore
from agentbus.store.board import BoardStore
from agentbus.store.claims import ClaimsStore
from agentbus.cli import build_parser


def run_cli_subprocess(args_list, env_extra=None):
    """CLI'yı izole alt süreç olarak çalıştırır."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, "-m", "agentbus.cli"] + args_list
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env
    )
    return proc


def test_msg_send_and_inbox(tmp_path):
    home = str(tmp_path / ".data")
    run_cli_subprocess(["--home", home, "init"])

    # 1. Mesaj gönder
    p_send = run_cli_subprocess([
        "--home", home, "msg", "send",
        "--to", "j_0001",
        "--sender", "orchestrator",
        "Lütfen API testlerini kontrol et",
        "--json"
    ])
    assert p_send.returncode == 0, p_send.stderr
    data_send = json.loads(p_send.stdout)
    assert data_send["status"] == "ok"
    assert data_send["to"] == "j_0001"

    # 2. Gelen kutusunu oku
    p_inbox = run_cli_subprocess([
        "--home", home, "msg", "inbox",
        "--for", "j_0001",
        "--json"
    ])
    assert p_inbox.returncode == 0, p_inbox.stderr
    msgs = json.loads(p_inbox.stdout)
    assert len(msgs) == 1
    assert msgs[0]["body"] == "Lütfen API testlerini kontrol et"
    assert msgs[0]["from"] == "orchestrator"

    # 3. Okundu olarak işaretle ve unread filtrele
    p_read = run_cli_subprocess([
        "--home", home, "msg", "inbox",
        "--for", "j_0001",
        "--mark-read",
        "--json"
    ])
    assert p_read.returncode == 0

    p_unread = run_cli_subprocess([
        "--home", home, "msg", "inbox",
        "--for", "j_0001",
        "--unread",
        "--json"
    ])
    assert p_unread.returncode == 0
    assert json.loads(p_unread.stdout) == []


def test_board_get_set_ls(tmp_path):
    home = str(tmp_path / ".data")
    run_cli_subprocess(["--home", home, "init"])

    # 1. Değer yaz
    p_set1 = run_cli_subprocess([
        "--home", home, "board", "set",
        "api_schema", "v1.0-alpha",
        "--author", "agent_api",
        "--json"
    ])
    assert p_set1.returncode == 0
    res1 = json.loads(p_set1.stdout)
    assert res1["version"] == 1

    # 2. Değer oku
    p_get = run_cli_subprocess([
        "--home", home, "board", "get", "api_schema", "--json"
    ])
    assert p_get.returncode == 0
    res_get = json.loads(p_get.stdout)
    assert res_get["value"] == "v1.0-alpha"
    assert res_get["author"] == "agent_api"

    # 3. Güncelle
    p_set2 = run_cli_subprocess([
        "--home", home, "board", "set",
        "api_schema", "v1.0-beta",
        "--author", "agent_api",
        "--json"
    ])
    assert p_set2.returncode == 0
    res2 = json.loads(p_set2.stdout)
    assert res2["version"] == 2

    # 4. Listele
    p_ls = run_cli_subprocess([
        "--home", home, "board", "ls", "--json"
    ])
    assert p_ls.returncode == 0
    entries = json.loads(p_ls.stdout)
    assert len(entries) >= 1
    assert any(e["key"] == "api_schema" and e["value"] == "v1.0-beta" for e in entries)


def test_claims_acquire_conflict_release(tmp_path):
    home = str(tmp_path / ".data")
    run_cli_subprocess(["--home", home, "init"])

    # 1. Job A kilit alır
    p_c1 = run_cli_subprocess([
        "--home", home, "claim", "src/auth/**", "--job", "j_auth_agent", "--json"
    ])
    assert p_c1.returncode == 0
    assert json.loads(p_c1.stdout)["status"] == "ok"

    # 2. Job B aynı yolu kilitlemeye çalışır -> conflict
    p_c2 = run_cli_subprocess([
        "--home", home, "claim", "src/auth/**", "--job", "j_other_agent", "--json"
    ])
    assert p_c2.returncode != 0
    assert "conflict" in p_c2.stdout or "kilitlenmiş" in p_c2.stderr

    # 3. Job A kilidi bırakır
    p_u = run_cli_subprocess([
        "--home", home, "unclaim", "src/auth/**", "--job", "j_auth_agent", "--json"
    ])
    assert p_u.returncode == 0

    # 4. Şimdi Job B kilidi alabilir
    p_c3 = run_cli_subprocess([
        "--home", home, "claim", "src/auth/**", "--job", "j_other_agent", "--json"
    ])
    assert p_c3.returncode == 0
    assert json.loads(p_c3.stdout)["status"] == "ok"


def test_open_and_detach_single_writer_g3(tmp_path):
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    job = jobs.create_job(title="Job Open Test", task_md="Open and detach")

    parser = build_parser()

    # 1. open komutu -> human_attached olmalı
    args_open = parser.parse_args(["--home", str(home), "open", job.id, "--here", "--json"])
    # Not: Gerçek agy başlatmasını önlemek için env AGENTBUS_AGY_BIN'e sys.executable ve -c "exit(0)" verilebilir
    os.environ["AGENTBUS_AGY_BIN"] = f"{sys.executable} -c \"import sys; sys.exit(0)\""
    rc_open = args_open.func(args_open)
    assert rc_open == 0

    job_attached = jobs.get_job(job.id)
    assert job_attached.status == JobStatus.HUMAN_ATTACHED

    # 2. G3: AgyRunner insan bağlıyken tur başlatmayı reddetmeli
    from agentbus.runner_agy import AgyRunner
    runner = AgyRunner(conn, home)
    with pytest.raises(RuntimeError, match="insan oturumu açık"):
        runner.run_turn(job.id, TurnKind.INITIAL)

    # 3. detach komutu -> iş queued olmalı
    args_detach = parser.parse_args(["--home", str(home), "detach", job.id, "--json"])
    rc_detach = args_detach.func(args_detach)
    assert rc_detach == 0

    job_detached = jobs.get_job(job.id)
    assert job_detached.status == JobStatus.QUEUED


def test_reply_and_send(tmp_path):
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    job = jobs.create_job(title="Job Needs Input", task_md="Question task")

    # İşi needs_input yap
    transition(conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job.id, JobStatus.RUNNING, JobStatus.NEEDS_INPUT)

    parser = build_parser()

    # 1. reply komutu
    args_reply = parser.parse_args(["--home", str(home), "reply", job.id, "PostgreSQL 16 kullan", "--json"])
    rc_reply = args_reply.func(args_reply)
    assert rc_reply == 0

    job_replied = jobs.get_job(job.id)
    assert job_replied.status == JobStatus.QUEUED

    msg_store = MessagesStore(conn)
    inbox = msg_store.get_inbox(job.id)
    assert any("PostgreSQL 16 kullan" in m.body for m in inbox)

    # 2. send komutu
    transition(conn, job.id, JobStatus.QUEUED, JobStatus.RUNNING)
    transition(conn, job.id, JobStatus.RUNNING, JobStatus.AWAITING_REVIEW)

    args_send = parser.parse_args(["--home", str(home), "send", job.id, "Lütfen flake8 çalıştır", "--json"])
    rc_send = args_send.func(args_send)
    assert rc_send == 0

    job_sent = jobs.get_job(job.id)
    assert job_sent.status == JobStatus.QUEUED


def test_g8_agent_role_restrictions(tmp_path):
    home = str(tmp_path / ".data")
    run_cli_subprocess(["--home", home, "init"])

    # İş oluştur
    p_sub = run_cli_subprocess(["--home", home, "submit", "-t", "Agent Job", "-m", "task", "--json"])
    job_id = json.loads(p_sub.stdout)["job"]["id"]

    agent_env = {
        "AGENTBUS_ROLE": "agent",
        "AGENTBUS_JOB_ID": job_id
    }

    # 1. Ajan yasaklı komut çalıştırmayı dener (cancel, up, down) -> HATA (13)
    p_cancel = run_cli_subprocess(["--home", home, "cancel", job_id], env_extra=agent_env)
    assert p_cancel.returncode == 13
    assert "Erişim reddedildi" in p_cancel.stderr

    p_up = run_cli_subprocess(["--home", home, "up"], env_extra=agent_env)
    assert p_up.returncode == 13
    assert "Erişim reddedildi" in p_up.stderr

    # 2. Ajan başka bir işi görmeyi dener (show j_other) -> HATA (13)
    p_show_other = run_cli_subprocess(["--home", home, "show", "j_99999999_9999"], env_extra=agent_env)
    assert p_show_other.returncode == 13

    # 3. Ajan kendi işini görebilir (show job_id) -> BAŞARILI
    p_show_self = run_cli_subprocess(["--home", home, "show", job_id, "--json"], env_extra=agent_env)
    assert p_show_self.returncode == 0

    # 4. Ajan izinli komutları (msg, board, claim) çalıştırabilir -> BAŞARILI
    p_msg = run_cli_subprocess(["--home", home, "msg", "send", "--to", "orchestrator", "İşlem bitti", "--json"], env_extra=agent_env)
    assert p_msg.returncode == 0

    p_board = run_cli_subprocess(["--home", home, "board", "set", "progress", "50%", "--json"], env_extra=agent_env)
    assert p_board.returncode == 0
