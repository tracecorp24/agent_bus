#!/usr/bin/env python3
"""Fake agy CLI - Antigravity stream-json simülatörü.

Gerçek agy v1.4.10 çıktısını ve hata senaryolarını birebir simüle eder.
"""

import sys
import os
import json
import time
import uuid
import argparse


def main():
    parser = argparse.ArgumentParser(description="Fake agy CLI")
    parser.add_argument("-p", "--print", dest="prompt", type=str, default="")
    parser.add_argument("--prompt", dest="prompt_alias", type=str, default="")
    parser.add_argument("--conversation", type=str, default=None)
    parser.add_argument("--continue", dest="cont", action="store_true")
    parser.add_argument("--output-format", type=str, default="text")
    parser.add_argument("--input-format", type=str, default="text")
    parser.add_argument("--model", type=str, default="gemini-3.8-flash-high")
    parser.add_argument("--json-schema", type=str, default="")
    parser.add_argument("--print-timeout", type=str, default="0s")
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    parser.add_argument("--add-dir", action="append", default=[])
    parser.add_argument("--log-file", type=str, default="")
    parser.add_argument("--mode", type=str, default="auto")

    # Simülasyon senaryo bayrakları (CLI veya ortam değişkeninden)
    parser.add_argument("--fake-hang", action="store_true")
    parser.add_argument("--fake-crash", action="store_true")
    parser.add_argument("--fake-429", action="store_true")
    parser.add_argument("--fake-needs-input", action="store_true")

    args, unknown = parser.parse_known_args()

    hang = args.fake_hang or (os.environ.get("FAKE_AGY_MODE") == "hang")
    crash = args.fake_crash or (os.environ.get("FAKE_AGY_MODE") == "crash")
    quota_429 = args.fake_429 or (os.environ.get("FAKE_AGY_MODE") == "429")
    needs_input = args.fake_needs_input or (os.environ.get("FAKE_AGY_MODE") == "needs_input")

    # Stdin okuma (eğer --input-format stream-json ise)
    prompt_text = args.prompt or args.prompt_alias
    if args.input_format == "stream-json" and not sys.stdin.isatty():
        line = sys.stdin.readline()
        if line:
            try:
                data = json.loads(line)
                if data.get("event") == "user":
                    prompt_text = data.get("message", {}).get("content", "")
            except Exception:
                pass

    conv_id = args.conversation or str(uuid.uuid4())

    # Asılma senaryosu
    if hang:
        time.sleep(3600)
        return 0

    # 429 Senaryosu
    if quota_429:
        init_evt = {
            "event": "init",
            "conversation_id": conv_id,
            "init": {
                "model": args.model,
                "cwd": os.getcwd(),
                "tools": ["run_command"],
                "permission_mode": "always-proceed"
            }
        }
        sys.stdout.write(json.dumps(init_evt) + "\n")
        sys.stdout.flush()
        err_res = {
            "event": "result",
            "result": {
                "conversation_id": conv_id,
                "status": "ERROR",
                "error": "RESOURCE_EXHAUSTED: 429 Quota exceeded",
                "response": ""
            }
        }
        sys.stdout.write(json.dumps(err_res) + "\n")
        sys.stdout.flush()
        sys.stderr.write("error: 429 Quota exceeded for model\n")
        sys.stderr.flush()
        return 1

    # İlk satır: init
    init_evt = {
        "event": "init",
        "conversation_id": conv_id,
        "init": {
            "model": args.model,
            "cwd": os.getcwd(),
            "tools": ["run_command", "read_file", "write_to_file", "finish"],
            "permission_mode": "always-proceed"
        }
    }
    sys.stdout.write(json.dumps(init_evt) + "\n")
    sys.stdout.flush()

    # Çökme senaryosu (init'ten sonra süreç aniden ölür)
    if crash:
        sys.exit(1)

    # user_input step_update
    step0 = {
        "event": "step_update",
        "step_update": {
            "conversation_id": conv_id,
            "step_index": 0,
            "state": "DONE",
            "step_type": "user_input"
        }
    }
    sys.stdout.write(json.dumps(step0) + "\n")
    sys.stdout.flush()

    # agent_response step_update
    step1 = {
        "event": "step_update",
        "step_update": {
            "conversation_id": conv_id,
            "step_index": 1,
            "state": "DONE",
            "step_type": "agent_response",
            "text_delta": "İşlem yapılıyor...",
            "duration_seconds": 0.1,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120
            }
        }
    }
    sys.stdout.write(json.dumps(step1) + "\n")
    sys.stdout.flush()

    # Sonuç bloğu
    if needs_input:
        structured = {
            "status": "needs_input",
            "summary": "Ek bilgiye ihtiyaç var.",
            "files_changed": [],
            "tests": "",
            "question": "Hangi parametre kullanılmalı?"
        }
    else:
        structured = {
            "status": "done",
            "summary": "Görev başarıyla tamamlandı.",
            "files_changed": [],
            "tests": "pytest passed",
            "question": None
        }

    res_evt = {
        "event": "result",
        "result": {
            "conversation_id": conv_id,
            "status": "SUCCESS",
            "response": json.dumps(structured),
            "structured_output": structured,
            "duration_seconds": 0.5,
            "num_turns": 1,
            "usage": {
                "input_tokens": 150,
                "output_tokens": 50,
                "total_tokens": 200
            }
        }
    }
    sys.stdout.write(json.dumps(res_evt) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
