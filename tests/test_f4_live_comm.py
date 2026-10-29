"""F4 - Canlı agy iletişim testi (-m live)."""

import os
import sys
import json
import subprocess
import pytest
from pathlib import Path

from agentbus.db import get_connection, init_db
from agentbus.store.board import BoardStore
from agentbus.prompts import RESULT_JSON_SCHEMA_STR


@pytest.mark.live
def test_live_agent_board_communication(tmp_path):
    """Gerçek agy'nin agentbus board set komutuyla veri yazmasını doğrular."""
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    # agy'ye verilecek kısa talimat: CLI üzerinden tahtaya yaz
    cmd_agentbus = f"{sys.executable} -m agentbus.cli --home {str(home)}"
    prompt = (
        f"Şu komutu çalıştır: `{cmd_agentbus} board set greeting live_ok`.\n"
        "Çalıştırdıktan sonra sonucunu kontrol et ve görevini bitir."
    )

    env = dict(os.environ)
    env["AGENTBUS_HOME"] = str(home)
    env["AGENTBUS_ROLE"] = "agent"
    env["AGENTBUS_JOB_ID"] = "j_live_agent"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        "agy",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--model", "gemini-3.8-flash-high",
        "--dangerously-skip-permissions",
        "--json-schema", RESULT_JSON_SCHEMA_STR,
    ]

    ndjson_input = json.dumps({
        "event": "user",
        "message": {"content": prompt}
    }) + "\n"

    proc = subprocess.run(
        cmd,
        input=ndjson_input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180
    )

    assert proc.returncode == 0, f"agy başarısız: {proc.stderr}"

    # Tahtada greeting = live_ok olduğunu doğrula
    board = BoardStore(conn)
    entry = board.get_entry("greeting")
    assert entry is not None, "Ajan tahtaya 'greeting' anahtarını yazamadı"
    assert "live_ok" in entry.value
    assert entry.author == "j_live_agent"
