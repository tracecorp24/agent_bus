"""fake_agy.py birim testleri (not live)."""

import sys
import subprocess
import json
from pathlib import Path

FAKE_AGY = sys.executable + " " + str(Path(__file__).parent / "fake_agy.py")


def test_fake_agy_normal():
    cmd = f"{FAKE_AGY} --output-format stream-json"
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    assert p.returncode == 0
    lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    assert lines[0]["event"] == "init"
    assert lines[-1]["event"] == "result"
    assert lines[-1]["result"]["status"] == "SUCCESS"
    assert lines[-1]["result"]["structured_output"]["status"] == "done"


def test_fake_agy_conversation_reuse():
    conv_id = "test-conv-1234"
    cmd = f"{FAKE_AGY} --conversation {conv_id} --output-format stream-json"
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    assert p.returncode == 0
    lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    assert lines[0]["conversation_id"] == conv_id
    assert lines[-1]["result"]["conversation_id"] == conv_id


def test_fake_agy_crash():
    cmd = f"{FAKE_AGY} --fake-crash --output-format stream-json"
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    assert p.returncode == 1
    lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["event"] == "init"


def test_fake_agy_429():
    cmd = f"{FAKE_AGY} --fake-429 --output-format stream-json"
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    assert p.returncode == 1
    assert "429" in p.stderr or "429" in p.stdout


def test_fake_agy_stdin_stream_json():
    payload = json.dumps({"event": "user", "message": {"content": "Test prompt"}}) + "\n"
    cmd = [sys.executable, str(Path(__file__).parent / "fake_agy.py"), "--input-format", "stream-json", "--output-format", "stream-json"]
    p = subprocess.run(cmd, input=payload, capture_output=True, text=True)
    assert p.returncode == 0
    lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    assert lines[-1]["result"]["status"] == "SUCCESS"
