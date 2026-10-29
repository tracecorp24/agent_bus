import os
import sys
import json
import subprocess
from pathlib import Path
import pytest

from agentbus.db import get_connection, init_db, transition
from agentbus.models import JobStatus, Job
from agentbus.store.jobs import JobsStore
from agentbus.store.events import EventsStore
from agentbus.cli import build_parser


def test_tail_and_watch_cli(tmp_path, capsys):
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    events = EventsStore(conn)

    job = jobs.create_job(title="Tail Job", task_md="Tail test")
    events.emit_event("test.event_1", job_id=job.id, payload={"detail": "first"})
    events.emit_event("test.event_2", job_id=job.id, payload={"detail": "second"})

    parser = build_parser()

    # 1. tail komutu (--json)
    args_tail = parser.parse_args(["--home", str(home), "tail", "--job", job.id, "--json"])
    rc_tail = args_tail.func(args_tail)
    assert rc_tail == 0
    captured_tail = capsys.readouterr()
    assert "test.event_1" in captured_tail.out
    assert "test.event_2" in captured_tail.out

    # 2. watch --once komutu
    args_watch = parser.parse_args(["--home", str(home), "watch", "--once"])
    rc_watch = args_watch.func(args_watch)
    assert rc_watch == 0
    captured_watch = capsys.readouterr()
    assert "AGENT BUS CANLI İZLEME" in captured_watch.out


@pytest.mark.asyncio
async def test_tui_app_lifecycle(tmp_path):
    """Textual TUI uygulamasının başlatılmasını, DB senkronizasyonunu ve kapanmasını test eder."""
    home = tmp_path / ".data"
    conn = get_connection(home / "bus.db")
    init_db(conn)

    jobs = JobsStore(conn)
    events = EventsStore(conn)

    job1 = jobs.create_job(title="Running Agent 1", task_md="Task 1")
    transition(conn, job1.id, JobStatus.QUEUED, JobStatus.RUNNING)

    events.emit_event("step.started", job_id=job1.id, payload={"step": 1})

    from agentbus.tui.app import AgentBusTuiApp
    app = AgentBusTuiApp(home, periodic_sync=False)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.is_mounted

        # sync_db çağrısı ve mount işlemlerinin DOM'a yansıması için pause
        app.sync_db()
        await pilot.pause()

        # Tile kontrolü
        tile = app.query_one(f"#tile_{job1.id}")
        assert tile is not None

        # Detach butonu tetikleme
        btn_detach = app.query_one(f"#btn_detach_{job1.id}")
        btn_detach.press()
        await pilot.pause()
