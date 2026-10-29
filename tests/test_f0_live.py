"""F0 - Canlı agy protokolü keşif testleri (-m live)."""

import json
import subprocess
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.live
def test_stream_json_output():
    """agy stream-json çıktısının yapısını doğrula ve kaydet."""
    cmd = [
        "agy",
        "-p", "Sadece 'MERHABA' yaz.",
        "--model", "gemini-3.8-flash-high",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    assert proc.returncode == 0, f"agy başarısız: {proc.stderr}"
    
    raw_lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    assert len(raw_lines) >= 2, "En az init ve result satırları olmalı"
    
    out_file = FIXTURES_DIR / "agy_stream_basic.jsonl"
    out_file.write_text("\n".join(raw_lines), encoding="utf-8")
    
    init_obj = json.loads(raw_lines[0])
    assert init_obj.get("event") == "init"
    assert "conversation_id" in init_obj
    
    result_obj = json.loads(raw_lines[-1])
    assert result_obj.get("event") == "result"
    assert "status" in result_obj.get("result", {})
    assert result_obj["result"]["status"] == "SUCCESS"


@pytest.mark.live
def test_json_schema_enforcement():
    """--json-schema parametresinin davranışını doğrula."""
    schema = json.dumps({
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["done", "failed"]},
            "summary": {"type": "string"}
        },
        "required": ["status", "summary"]
    })
    cmd = [
        "agy",
        "-p", "Görev bitti de ve özetle.",
        "--model", "gemini-3.8-flash-high",
        "--output-format", "stream-json",
        "--json-schema", schema,
        "--dangerously-skip-permissions",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    assert proc.returncode == 0, f"agy başarısız: {proc.stderr}"
    
    raw_lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    out_file = FIXTURES_DIR / "agy_stream_schema.jsonl"
    out_file.write_text("\n".join(raw_lines), encoding="utf-8")
    
    result_obj = json.loads(raw_lines[-1])
    assert result_obj.get("event") == "result"
    res_data = result_obj.get("result", {})
    assert "structured_output" in res_data
    assert res_data["structured_output"]["status"] in ["done", "failed"]


@pytest.mark.live
def test_stdin_stream_json_input():
    """--input-format stream-json ile stdin'den istem vermeyi doğrula (G2 kesinleşti)."""
    payload = {"event": "user", "message": {"content": "Sadece 'STDIN_OK' yaz."}}
    cmd = [
        "agy",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--model", "gemini-3.8-flash-high",
        "--dangerously-skip-permissions",
    ]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30
    )
    assert proc.returncode == 0, f"STDIN başarısız: {proc.stderr}"
    
    raw_lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    out_file = FIXTURES_DIR / "agy_stdin_success.jsonl"
    out_file.write_text("\n".join(raw_lines), encoding="utf-8")
    
    init_obj = json.loads(raw_lines[0])
    assert init_obj["event"] == "init"
    
    result_obj = json.loads(raw_lines[-1])
    assert result_obj["event"] == "result"
    assert result_obj["result"]["status"] == "SUCCESS"


@pytest.mark.live
def test_print_timeout_behavior():
    """--print-timeout aşımı durumunda çıkış kodu ve çıktıyı gözlemle."""
    cmd = [
        "agy",
        "-p", "1000'e kadar say ve açıkla.",
        "--model", "gemini-3.8-flash-high",
        "--output-format", "stream-json",
        "--print-timeout", "2s",
        "--dangerously-skip-permissions",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30
    )
    assert proc.returncode == 0, f"agy başarısız: {proc.stderr}"
    out_file = FIXTURES_DIR / "agy_timeout_test.txt"
    out_file.write_text(f"Return: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}", encoding="utf-8")
    
    # Timeout mesajı stdout veya stderr'de bulunur
    assert "[agy] print timeout" in proc.stdout or "[agy] print timeout" in proc.stderr
    
    # stream-json son satırı result olmalı
    raw_lines = [l.strip() for l in proc.stdout.splitlines() if l.strip() and l.strip().startswith("{")]
    assert len(raw_lines) >= 1
    last_obj = json.loads(raw_lines[-1])
    assert last_obj.get("event") == "result"

