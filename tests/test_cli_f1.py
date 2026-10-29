"""F1 CLI komutları birim testleri (not live)."""

import sys
import os
import subprocess
import json
from pathlib import Path


def run_cli(*args):
    cmd = [sys.executable, "-m", "agentbus.cli"] + list(args)
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env
    )
    return proc


def test_cli_init_and_doctor(tmp_path):
    home = str(tmp_path / ".data")

    # init
    p = run_cli("--home", home, "init", "--json")
    assert p.returncode == 0, f"init başarısız: {p.stderr}"
    data = json.loads(p.stdout)
    assert data["status"] == "ok"
    assert Path(data["db_path"]).exists()

    # doctor
    p_doc = run_cli("--home", home, "doctor", "--json")
    assert p_doc.returncode == 0, f"doctor başarısız: {p_doc.stderr}"
    doc_data = json.loads(p_doc.stdout)
    assert doc_data["status"] == "healthy"
    assert len(doc_data["checks"]) >= 4


def test_cli_submit_ls_show(tmp_path):
    home = str(tmp_path / ".data")
    run_cli("--home", home, "init")

    # submit
    p_sub = run_cli(
        "--home", home, "--json",
        "submit",
        "-t", "Örnek Görev 1",
        "-m", "Bu bir test görevidir.",
        "--priority", "8",
        "--paths", "src/api/**",
        "--key", "idemp_test_1"
    )
    assert p_sub.returncode == 0, f"submit başarısız: {p_sub.stderr}"
    sub_data = json.loads(p_sub.stdout)
    job_id = sub_data["job"]["id"]
    assert job_id.startswith("j_")

    # submit aynı key ile tekrar
    p_sub_dup = run_cli(
        "--home", home, "--json",
        "submit",
        "-t", "Örnek Görev Tekrar",
        "-m", "Farklı metin",
        "--key", "idemp_test_1"
    )
    assert p_sub_dup.returncode == 0
    sub_dup_data = json.loads(p_sub_dup.stdout)
    assert sub_dup_data["job"]["id"] == job_id

    # ls
    p_ls = run_cli("--home", home, "--json", "ls")
    assert p_ls.returncode == 0
    ls_data = json.loads(p_ls.stdout)
    assert len(ls_data) == 1
    assert ls_data[0]["id"] == job_id
    assert ls_data[0]["priority"] == 8

    # show
    p_show = run_cli("--home", home, "--json", "show", job_id, "--events", "5")
    assert p_show.returncode == 0
    show_data = json.loads(p_show.stdout)
    assert show_data["id"] == job_id
    assert show_data["title"] == "Örnek Görev 1"
    assert len(show_data["events"]) >= 1


def test_cli_human_output(tmp_path):
    home = str(tmp_path / ".data")
    run_cli("--home", home, "init")
    p_sub = run_cli("--home", home, "submit", "-t", "İnsan Çıktısı Testi", "-m", "Açıklama")
    assert p_sub.returncode == 0
    assert "Is kuyruga alindi" in p_sub.stdout

    p_ls = run_cli("--home", home, "ls")
    assert p_ls.returncode == 0
    assert "j_2026" in p_ls.stdout
    assert "İnsan" in p_ls.stdout or "Insan" in p_ls.stdout
