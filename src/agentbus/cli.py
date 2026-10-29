"""Agent Bus ana CLI arayüzü."""

import sys
import os
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List

from rich.console import Console
from rich.table import Table

from agentbus.db import get_connection, init_db, get_home_dir, get_db_path, transition
from agentbus.models import JobStatus, Job, Turn, Event, utc_now_iso
from agentbus.store.jobs import JobsStore
from agentbus.store.turns import TurnsStore
from agentbus.store.events import EventsStore
from agentbus.store.messages import MessagesStore
from agentbus.store.board import BoardStore
from agentbus.store.claims import ClaimsStore
from agentbus.store.agents import AgentsStore
from agentbus.store.meta import MetaStore

console = Console(legacy_windows=False)
err_console = Console(stderr=True, legacy_windows=False)


def is_json_mode(args: argparse.Namespace) -> bool:
    """Argümanlarda veya sys.argv içinde --json olup olmadığını kontrol eder."""
    return getattr(args, "json", False) or ("--json" in sys.argv)


def get_home_arg(args: argparse.Namespace) -> Optional[str]:
    """--home argümanını güvenilir biçimde döndürür."""
    if getattr(args, "home", None):
        return args.home
    if "--home" in sys.argv:
        try:
            idx = sys.argv.index("--home")
            return sys.argv[idx + 1]
        except (ValueError, IndexError):
            pass
    return None


def cmd_init(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    db_path = get_db_path(get_home_arg(args))
    runs_dir = home_dir / "runs"
    worktrees_dir = home_dir / "worktrees"
    logs_dir = home_dir / "logs"

    runs_dir.mkdir(parents=True, exist_ok=True)
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path)
    init_db(conn)

    meta = MetaStore(conn)
    if args.repo:
        repo_path = str(Path(args.repo).resolve())
        meta.set("default_repo", repo_path)

    if is_json_mode(args):
        print(json.dumps({
            "status": "ok",
            "home": str(home_dir),
            "db_path": str(db_path),
            "repo": args.repo
        }, indent=2))
    else:
        console.print(f"[bold green][OK] Agent Bus basariyla ilklendirildi.[/bold green]")
        console.print(f"  Veri Dizini: [cyan]{home_dir}[/cyan]")
        console.print(f"  Veritabani:  [cyan]{db_path}[/cyan]")
        if args.repo:
            console.print(f"  Varsayilan Repo: [cyan]{args.repo}[/cyan]")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = []

    # 1. Python sürümü
    py_ok = sys.version_info >= (3, 10)
    checks.append({
        "name": "Python 3.10+",
        "status": py_ok,
        "detail": f"{sys.version.split()[0]} ({sys.executable})"
    })

    # 2. agy CLI
    agy_path = shutil.which("agy")
    agy_ver = ""
    if agy_path:
        try:
            p = subprocess.run(["agy", "--version"], capture_output=True, text=True, timeout=5)
            agy_ver = p.stdout.strip()
        except Exception:
            agy_ver = "çalıştırılamadı"
    checks.append({
        "name": "Antigravity CLI (agy)",
        "status": bool(agy_path),
        "detail": f"{agy_ver} -> {agy_path or 'BULUNAMADI'}"
    })

    # 3. git CLI
    git_path = shutil.which("git")
    git_ver = ""
    if git_path:
        try:
            p = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
            git_ver = p.stdout.strip()
        except Exception:
            git_ver = "çalıştırılamadı"
    checks.append({
        "name": "Git CLI",
        "status": bool(git_path),
        "detail": f"{git_ver} -> {git_path or 'BULUNAMADI'}"
    })

    # 4. Veritabanı ve Dizinler
    home_dir = get_home_dir(get_home_arg(args))
    db_path = get_db_path(get_home_arg(args))
    db_ok = False
    db_detail = ""
    try:
        conn = get_connection(db_path)
        init_db(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) as cnt FROM jobs")
        cnt = cursor.fetchone()["cnt"]
        db_ok = True
        db_detail = f"Erişilebilir (toplam iş: {cnt}) -> {db_path}"
    except Exception as e:
        db_detail = str(e)

    checks.append({
        "name": "SQLite WAL Veritabanı",
        "status": db_ok,
        "detail": db_detail
    })

    all_passed = all(c["status"] for c in checks)

    if is_json_mode(args):
        print(json.dumps({
            "status": "healthy" if all_passed else "unhealthy",
            "checks": checks
        }, indent=2))
    else:
        table = Table(title="Agent Bus Sistem ve Sağlık Kontrolü (Doctor)")
        table.add_column("Bileşen", style="bold")
        table.add_column("Durum", justify="center")
        table.add_column("Ayrıntı")

        for c in checks:
            st = "[green]GEÇTİ[/green]" if c["status"] else "[red]HATA[/red]"
            table.add_row(c["name"], st, c["detail"])

        console.print(table)
        if all_passed:
            console.print("[bold green]Tüm kontroller başarılı. Sistem çalışmaya hazır.[/bold green]")
        else:
            console.print("[bold red]Bazı bileşenlerde eksikler var. Lütfen yukarıdaki hataları giderin.[/bold red]")

    return 0 if all_passed else 1


def cmd_submit(args: argparse.Namespace) -> int:
    task_text = ""
    if args.file:
        task_path = Path(args.file)
        if not task_path.exists():
            err_console.print(f"[red]Görev dosyası bulunamadı: {args.file}[/red]")
            return 1
        task_text = task_path.read_text(encoding="utf-8")
    elif args.task:
        task_text = args.task
    else:
        err_console.print("[red]Görev metni için -f/--file veya -m/--task belirtilmelidir.[/red]")
        return 1

    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)

    allowed_paths = [p.strip() for p in args.paths.split(",") if p.strip()] if args.paths else []
    depends_on = [d.strip() for d in args.after.split(",") if d.strip()] if args.after else []

    job = jobs_store.create_job(
        title=args.title,
        task_md=task_text,
        parent_id=args.parent,
        depends_on=depends_on,
        priority=args.priority,
        agent_profile=args.profile or "default",
        allowed_paths=allowed_paths,
        idempotency_key=args.key,
        repo=args.repo,
    )

    if is_json_mode(args):
        print(json.dumps({
            "status": "submitted",
            "job": {
                "id": job.id,
                "title": job.title,
                "status": job.status.value,
                "priority": job.priority,
                "created_at": job.created_at,
                "idempotency_key": job.idempotency_key
            }
        }, indent=2))
    else:
        console.print(f"[bold green][OK] Is kuyruga alindi:[/bold green] [cyan]{job.id}[/cyan] ({job.title})")
        console.print(f"  Öncelik: {job.priority} | Durum: {job.status.value}")
        if job.depends_on:
            console.print(f"  Bağımlılıklar: {job.depends_on}")
        if job.allowed_paths:
            console.print(f"  İzinli Yollar: {job.allowed_paths}")
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)

    st_filter = JobStatus(args.status) if args.status else None
    jobs = jobs_store.list_jobs(status=st_filter, limit=args.limit)

    if is_json_mode(args):
        items = []
        for j in jobs:
            items.append({
                "id": j.id,
                "title": j.title,
                "status": j.status.value,
                "priority": j.priority,
                "attempt": j.attempt,
                "conversation_id": j.conversation_id,
                "created_at": j.created_at,
                "updated_at": j.updated_at,
            })
        print(json.dumps(items, indent=2))
    else:
        if not jobs:
            console.print("[dim]Kuyrukta veya veritabanında iş bulunamadı.[/dim]")
            return 0

        table = Table(title="Agent Bus İşleri (Jobs)")
        table.add_column("İş No (ID)", style="cyan bold")
        table.add_column("Başlık")
        table.add_column("Durum", justify="center")
        table.add_column("Öncelik", justify="right")
        table.add_column("Deneme", justify="right")
        table.add_column("Sohbet ID (Conv)")
        table.add_column("Oluşturulma", style="dim")

        for j in jobs:
            st_color = {
                JobStatus.QUEUED: "yellow",
                JobStatus.RUNNING: "bold green",
                JobStatus.NEEDS_INPUT: "bold magenta",
                JobStatus.AWAITING_REVIEW: "bold cyan",
                JobStatus.PROMOTED: "green",
                JobStatus.FAILED: "red",
                JobStatus.INTERRUPTED: "bold red",
                JobStatus.CANCELLED: "dim",
            }.get(j.status, "white")

            table.add_row(
                j.id,
                j.title[:40],
                f"[{st_color}]{j.status.value}[/{st_color}]",
                str(j.priority),
                f"{j.attempt}/{j.max_attempts}",
                j.conversation_id[:12] if j.conversation_id else "-",
                j.created_at[11:19]
            )

        console.print(table)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    turns_store = TurnsStore(conn)
    events_store = EventsStore(conn)

    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    turns = turns_store.list_turns(args.job_id) if args.turns else []
    events = events_store.list_events(job_id=args.job_id, limit=args.events) if args.events else []

    if is_json_mode(args):
        data = {
            "id": job.id,
            "title": job.title,
            "task_md": job.task_md,
            "status": job.status.value,
            "priority": job.priority,
            "agent_profile": job.agent_profile,
            "conversation_id": job.conversation_id,
            "worktree_path": job.worktree_path,
            "branch": job.branch,
            "base_commit": job.base_commit,
            "allowed_paths": job.allowed_paths,
            "attempt": job.attempt,
            "max_attempts": job.max_attempts,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "result_summary": job.result_summary,
            "error": job.error,
            "turns": [
                {
                    "seq": t.seq,
                    "kind": t.kind.value,
                    "status": t.status.value,
                    "duration_s": t.duration_s,
                    "started_at": t.started_at,
                    "finished_at": t.finished_at
                } for t in turns
            ],
            "events": [
                {
                    "id": e.id,
                    "ts": e.ts,
                    "type": e.type,
                    "level": e.level,
                    "payload": json.loads(e.payload_json) if e.payload_json else {}
                } for e in events
            ]
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        console.print(f"[bold cyan]İş Detayı: {job.id}[/bold cyan] — [bold]{job.title}[/bold]")
        console.print(f"  Durum:           [bold]{job.status.value}[/bold]")
        console.print(f"  Öncelik/Deneme:  {job.priority} / {job.attempt} (en çok {job.max_attempts})")
        console.print(f"  Sohbet (ConvID): {job.conversation_id or '-'}")
        console.print(f"  Worktree:        {job.worktree_path or '-'}")
        console.print(f"  Dal (Branch):    {job.branch or '-'}")
        console.print(f"  Oluşturulma:     {job.created_at}")
        if job.result_summary:
            console.print(f"  Özet:            [green]{job.result_summary}[/green]")
        if job.error:
            console.print(f"  Hata:            [red]{job.error}[/red]")

        if turns:
            console.print("\n[bold]Turlar (Turns):[/bold]")
            for t in turns:
                console.print(f"  #{t.seq} [{t.kind.value}] - Durum: {t.status.value} (Süre: {t.duration_s or 0:.1f}s)")

        if events:
            console.print("\n[bold]Son Olaylar (Events):[/bold]")
            for e in events:
                console.print(f"  [{e.ts[11:19]}] {e.type} -> {e.payload_json[:80]}")

    return 0


def cmd_up(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    if args.detach:
        # Arka planda bağımsız süreç olarak başlat
        cmd = [
            sys.executable, "-m", "agentbus.cli",
            "--home", str(home_dir),
            "up",
            "--parallel", str(args.parallel)
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        if is_json_mode(args):
            print(json.dumps({"status": "started", "pid": proc.pid, "detached": True}, indent=2))
        else:
            console.print(f"[bold green][OK] Supervisor arka planda baslatildi (PID: {proc.pid}).[/bold green]")
        return 0

    from agentbus.supervisor import Supervisor
    sup = Supervisor(home_dir=home_dir, max_parallel=args.parallel)
    if not is_json_mode(args):
        console.print(f"[bold green]Supervisor baslatiliyor... (Paralel yuva: {args.parallel})[/bold green]")
        console.print("Durdurmak icin Ctrl+C basin.")
    try:
        sup.start()
    except KeyboardInterrupt:
        if not is_json_mode(args):
            console.print("\n[yellow]Supervisor durduruluyor...[/yellow]")
        sup.stop()
    except Exception as e:
        err_console.print(f"[red]Supervisor hatasi: {e}[/red]")
        return 1
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    meta = MetaStore(conn)
    meta.set("paused", "1")
    if is_json_mode(args):
        print(json.dumps({"status": "stopping", "paused": True}, indent=2))
    else:
        console.print("[yellow][OK] Supervisor'a durma sinyali gonderildi (paused=1).[/yellow]")
        console.print("Calisan turlar bittiginde surecler duracaktir.")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    from agentbus.supervisor import Supervisor
    sup = Supervisor(home_dir=home_dir)
    count = sup.recover()
    if is_json_mode(args):
        print(json.dumps({"status": "recovered", "recovered_jobs_count": count}, indent=2))
    else:
        console.print(f"[bold green][OK] Kurtarma taramasi tamamlandi. Kurtarilan is sayisi: {count}[/bold green]")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1
    if not job.worktree_path or not Path(job.worktree_path).exists():
        err_console.print(f"[yellow]İş için worktree bulunamadı veya henüz oluşturulmadı.[/yellow]")
        return 0

    from agentbus.worktree import get_diff
    diff_text = get_diff(Path(job.worktree_path), job.base_commit)
    if is_json_mode(args):
        print(json.dumps({"job_id": job.id, "diff": diff_text}, indent=2, ensure_ascii=False))
    else:
        if not diff_text:
            console.print("[dim]Herhangi bir değişiklik yok.[/dim]")
        else:
            print(diff_text)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    if args.approve:
        if job.status != JobStatus.AWAITING_REVIEW:
            err_console.print(f"[red]İş awaiting_review durumunda değil (şu anki durum: {job.status.value}).[/red]")
            return 1
        from agentbus.worktree import integrate_job
        success, msg = integrate_job(conn, home_dir, job)
        if success:
            if is_json_mode(args):
                print(json.dumps({"status": "approved_and_integrated", "job_id": job.id, "message": msg}, indent=2))
            else:
                console.print(f"[bold green][OK] İş onaylandı ve entegre edildi: {msg}[/bold green]")
            return 0
        else:
            err_console.print(f"[red]Entegrasyon başarısız: {msg}[/red]")
            return 1
    elif args.reject:
        transition(conn, job.id, job.status, JobStatus.REJECTED, reason=args.reject)
        if is_json_mode(args):
            print(json.dumps({"status": "rejected", "job_id": job.id, "reason": args.reject}, indent=2))
        else:
            console.print(f"[yellow][OK] İş reddedildi: {args.reject}[/yellow]")
        return 0
    else:
        err_console.print("[yellow]--approve veya --reject <neden> belirtilmelidir.[/yellow]")
        return 1


def cmd_merge(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    from agentbus.worktree import integrate_job
    success, msg = integrate_job(conn, home_dir, job)
    if success:
        if is_json_mode(args):
            print(json.dumps({"status": "integrated", "job_id": job.id, "message": msg}, indent=2))
        else:
            console.print(f"[bold green][OK] {msg}[/bold green]")
        return 0
    else:
        err_console.print(f"[red]Merge başarısız: {msg}[/red]")
        return 1


def cmd_promote(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    meta = MetaStore(conn)

    repo_str = args.repo or meta.get("default_repo")
    if not repo_str:
        err_console.print("[red]Hedef repo belirtilmedi (--repo veya 'agentbus init --repo').[/red]")
        return 1

    from agentbus.worktree import promote_repo
    success, msg = promote_repo(conn, home_dir, Path(repo_str))
    if success:
        if is_json_mode(args):
            print(json.dumps({"status": "promoted", "repo": repo_str, "message": msg}, indent=2))
        else:
            console.print(f"[bold green][OK] {msg}[/bold green]")
        return 0
    else:
        if is_json_mode(args):
            print(json.dumps({"status": "failed", "repo": repo_str, "error": msg}, indent=2))
        else:
            err_console.print(f"[yellow][UYARI] {msg}[/yellow]")
        return 1


def cmd_revert(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    from agentbus.worktree import revert_job
    success, msg = revert_job(conn, home_dir, job)
    if success:
        if is_json_mode(args):
            print(json.dumps({"status": "reverted", "job_id": job.id, "message": msg}, indent=2))
        else:
            console.print(f"[bold green][OK] {msg}[/bold green]")
        return 0
    else:
        err_console.print(f"[red]Revert başarısız: {msg}[/red]")
        return 1


def cmd_gc(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    meta = MetaStore(conn)
    repo_str = args.repo or meta.get("default_repo")
    if not repo_str:
        err_console.print("[red]Hedef repo belirtilmedi.[/red]")
        return 1

    from agentbus.worktree import gc_worktrees
    cleaned = gc_worktrees(conn, home_dir, Path(repo_str))
    if is_json_mode(args):
        print(json.dumps({"status": "ok", "cleaned_count": cleaned}, indent=2))
    else:
        console.print(f"[bold green][OK] {cleaned} adet worktree temizlendi.[/bold green]")
    return 0


def check_agent_role_guard(command_name: str, args: argparse.Namespace) -> bool:
    """G8: AGENTBUS_ROLE=agent ise yetkisiz komutları engeller."""
    role = os.environ.get("AGENTBUS_ROLE")
    if role != "agent":
        return True

    allowed_commands = ["msg", "board", "claim", "unclaim", "show"]
    if command_name not in allowed_commands:
        err_console.print(f"[red]Erişim reddedildi: Ajan rolü bu komutu çalıştıramaz ({command_name} - G8 kuralı)[/red]")
        return False

    agent_job_id = os.environ.get("AGENTBUS_JOB_ID")
    if command_name == "show":
        if getattr(args, "job_id", None) != agent_job_id:
            err_console.print(f"[red]Erişim reddedildi: Ajan rolü yalnızca kendi işini görüntüleyebilir (G8 kuralı)[/red]")
            return False

    return True


def cmd_msg_send(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    messages_store = MessagesStore(conn)
    events_store = EventsStore(conn)

    sender = os.environ.get("AGENTBUS_JOB_ID") or getattr(args, "sender", None) or "orchestrator"
    msg = messages_store.send_message(from_id=sender, to_id=args.to, body=args.body)
    events_store.emit_event(
        "message.sent",
        job_id=sender if sender != "orchestrator" else None,
        payload={"msg_id": msg.id, "from": sender, "to": args.to, "body": args.body}
    )
    if is_json_mode(args):
        print(json.dumps({"status": "ok", "message_id": msg.id, "from": sender, "to": args.to, "body": args.body}, indent=2, ensure_ascii=False))
    else:
        console.print(f"[bold green][OK] Mesaj gönderildi -> {args.to} (#{msg.id})[/bold green]")
    return 0


def cmd_msg_inbox(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    messages_store = MessagesStore(conn)

    recipient = getattr(args, "for_id", None) or os.environ.get("AGENTBUS_JOB_ID") or "orchestrator"
    msgs = messages_store.get_inbox(recipient_id=recipient, unread_only=getattr(args, "unread", False), limit=getattr(args, "limit", 50))

    if getattr(args, "mark_read", False):
        for m in msgs:
            messages_store.mark_read(m.id)

    if is_json_mode(args):
        data = [
            {"id": m.id, "ts": m.ts, "from": m.from_id, "to": m.to_id, "body": m.body, "read_at": m.read_at}
            for m in msgs
        ]
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        if not msgs:
            console.print("[dim]Gelen kutusu boş.[/dim]")
            return 0
        table = Table(title=f"Gelen Kutusu ({recipient})")
        table.add_column("ID", style="cyan", width=6)
        table.add_column("Kimden", style="green", width=16)
        table.add_column("Tarih", style="magenta", width=20)
        table.add_column("Mesaj", style="white")
        for m in msgs:
            table.add_row(str(m.id), m.from_id, m.ts[:19], m.body)
        console.print(table)
    return 0


def cmd_board_get(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    board_store = BoardStore(conn)
    entry = board_store.get_entry(args.key)
    if not entry:
        if is_json_mode(args):
            print(json.dumps({"error": "not_found", "key": args.key}, indent=2))
        else:
            err_console.print(f"[yellow]Anahtar bulunamadı: {args.key}[/yellow]")
        return 1
    if is_json_mode(args):
        print(json.dumps({"key": entry.key, "value": entry.value, "author": entry.author, "version": entry.version, "updated_at": entry.updated_at}, indent=2, ensure_ascii=False))
    else:
        print(entry.value)
    return 0


def cmd_board_set(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    board_store = BoardStore(conn)
    events_store = EventsStore(conn)

    author = os.environ.get("AGENTBUS_JOB_ID") or getattr(args, "author", None) or "orchestrator"
    entry = board_store.set_entry(args.key, args.value, author=author)
    events_store.emit_event(
        "board.updated",
        job_id=author if author != "orchestrator" else None,
        payload={"key": entry.key, "value": entry.value, "version": entry.version, "author": author}
    )
    if is_json_mode(args):
        print(json.dumps({"status": "ok", "key": entry.key, "value": entry.value, "version": entry.version}, indent=2, ensure_ascii=False))
    else:
        console.print(f"[bold green][OK] Tahta güncellendi: {entry.key} (v{entry.version})[/bold green]")
    return 0


def cmd_board_ls(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    board_store = BoardStore(conn)
    entries = board_store.list_entries()
    if is_json_mode(args):
        data = [
            {"key": e.key, "value": e.value, "author": e.author, "version": e.version, "updated_at": e.updated_at}
            for e in entries
        ]
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        if not entries:
            console.print("[dim]Tahta boş.[/dim]")
            return 0
        table = Table(title="Ortak Kara Tahta")
        table.add_column("Anahtar", style="cyan", width=20)
        table.add_column("Değer", style="white")
        table.add_column("Yazar", style="green", width=16)
        table.add_column("Ver.", style="magenta", width=6)
        table.add_column("Güncelleme", style="dim", width=20)
        for e in entries:
            val_preview = e.value if len(e.value) <= 60 else e.value[:57] + "..."
            table.add_row(e.key, val_preview, e.author, str(e.version), e.updated_at[:19])
        console.print(table)
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    claims_store = ClaimsStore(conn)
    events_store = EventsStore(conn)

    job_id = os.environ.get("AGENTBUS_JOB_ID") or getattr(args, "job", None) or "orchestrator"

    # Çakışma kontrolü
    existing_claims = claims_store.list_claims()
    for c in existing_claims:
        if c.path_glob == args.glob and c.job_id != job_id:
            msg = f"Bu dosya yolu zaten başka bir iş tarafından kilitlenmiş: {c.path_glob} ({c.job_id})"
            if is_json_mode(args):
                print(json.dumps({"status": "conflict", "error": msg}, indent=2))
            else:
                err_console.print(f"[red]{msg}[/red]")
            return 1

    claim = claims_store.claim_path(args.glob, job_id=job_id)
    events_store.emit_event(
        "claim.acquired",
        job_id=job_id if job_id != "orchestrator" else None,
        payload={"glob": claim.path_glob, "job_id": job_id}
    )
    if is_json_mode(args):
        print(json.dumps({"status": "ok", "glob": claim.path_glob, "job_id": job_id}, indent=2))
    else:
        console.print(f"[bold green][OK] Kilit alındı: {claim.path_glob} ({job_id})[/bold green]")
    return 0


def cmd_unclaim(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    claims_store = ClaimsStore(conn)
    events_store = EventsStore(conn)

    job_id = os.environ.get("AGENTBUS_JOB_ID") or getattr(args, "job", None) or "orchestrator"
    ok = claims_store.unclaim_path(args.glob, job_id=job_id)
    if ok:
        events_store.emit_event(
            "claim.released",
            job_id=job_id if job_id != "orchestrator" else None,
            payload={"glob": args.glob, "job_id": job_id}
        )
        if is_json_mode(args):
            print(json.dumps({"status": "ok", "glob": args.glob}, indent=2))
        else:
            console.print(f"[bold green][OK] Kilit bırakıldı: {args.glob}[/bold green]")
        return 0
    else:
        if is_json_mode(args):
            print(json.dumps({"status": "not_found", "glob": args.glob}, indent=2))
        else:
            err_console.print(f"[yellow]Bırakılacak kilit bulunamadı: {args.glob}[/yellow]")
        return 1


def cmd_open(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    if job.status == JobStatus.RUNNING:
        transition(conn, job.id, JobStatus.RUNNING, JobStatus.ATTACH_PENDING, reason="İnsan bağlanmak istedi (G3)")
        console.print("[yellow]İş şu an çalışıyor; çalışan turun bitmesi bekleniyor (G3 kuralı: attach_pending)...[/yellow]")
        return 0

    if job.status != JobStatus.HUMAN_ATTACHED:
        transition(conn, job.id, job.status, JobStatus.HUMAN_ATTACHED, reason="İnsan oturumu açtı (open)")

    events_store = EventsStore(conn)
    events_store.emit_event("job.attached", job_id=job.id, payload={"conversation_id": job.conversation_id})

    work_dir = job.worktree_path or str(home_dir)
    conv_arg = ["--conversation", job.conversation_id] if job.conversation_id else []

    if getattr(args, "here", False) or not sys.platform.startswith("win"):
        if is_json_mode(args):
            print(json.dumps({"status": "human_attached", "job_id": job.id, "cwd": work_dir}, indent=2))
        else:
            console.print(f"[bold green][OK] İş {job.id} human_attached yapıldı. agy başlatılıyor...[/bold green]")
            agy_bin = os.environ.get("AGENTBUS_AGY_BIN", "agy")
            subprocess.run([agy_bin] + conv_arg, cwd=work_dir)
    else:
        agy_bin = os.environ.get("AGENTBUS_AGY_BIN", "agy")
        cmd_str = f'start "Agent Bus: {job.id}" {agy_bin} ' + " ".join(conv_arg)
        subprocess.Popen(cmd_str, shell=True, cwd=work_dir)
        if is_json_mode(args):
            print(json.dumps({"status": "human_attached", "job_id": job.id, "terminal": "new_window"}, indent=2))
        else:
            console.print(f"[bold green][OK] İş {job.id} human_attached yapıldı ve yeni konsol penceresinde açıldı.[/bold green]")
    return 0


def cmd_detach(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    if job.status not in (JobStatus.HUMAN_ATTACHED, JobStatus.ATTACH_PENDING):
        err_console.print(f"[yellow]İş insan oturumunda değil (durum: {job.status.value}).[/yellow]")
        return 1

    transition(conn, job.id, job.status, JobStatus.QUEUED, reason="İnsan oturumu devretti (detach)")
    events_store = EventsStore(conn)
    events_store.emit_event("job.detached", job_id=job.id)

    if is_json_mode(args):
        print(json.dumps({"status": "queued", "job_id": job.id}, indent=2))
    else:
        console.print(f"[bold green][OK] İş {job.id} devredildi (detach). Supervisor kuyruğunda devam edecek.[/bold green]")
    return 0


def cmd_reply(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    if job.status != JobStatus.NEEDS_INPUT:
        err_console.print(f"[yellow]İş soru bekler (needs_input) durumda değil (şu anki durum: {job.status.value}).[/yellow]")
        return 1

    messages_store = MessagesStore(conn)
    messages_store.send_message(from_id="orchestrator", to_id=job.id, body=args.answer)
    transition(conn, job.id, JobStatus.NEEDS_INPUT, JobStatus.QUEUED, reason=f"Yanıt verildi: {args.answer[:40]}")
    events_store = EventsStore(conn)
    events_store.emit_event("job.replied", job_id=job.id, payload={"answer": args.answer})

    if is_json_mode(args):
        print(json.dumps({"status": "queued", "job_id": job.id, "answer": args.answer}, indent=2, ensure_ascii=False))
    else:
        console.print(f"[bold green][OK] İş {job.id} yanıtlandı ve tekrar kuyruğa alındı.[/bold green]")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    messages_store = MessagesStore(conn)
    messages_store.send_message(from_id="orchestrator", to_id=job.id, body=args.instruction)
    if job.status in (JobStatus.AWAITING_REVIEW, JobStatus.PAUSED, JobStatus.FAILED):
        transition(conn, job.id, job.status, JobStatus.QUEUED, reason=f"Ek talimat verildi: {args.instruction[:40]}")

    events_store = EventsStore(conn)
    events_store.emit_event("job.instruction_sent", job_id=job.id, payload={"instruction": args.instruction})

    if is_json_mode(args):
        print(json.dumps({"status": "ok", "job_id": job.id, "instruction": args.instruction}, indent=2, ensure_ascii=False))
    else:
        console.print(f"[bold green][OK] İş {job.id}'e talimat gönderildi.[/bold green]")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    transition(conn, job.id, job.status, JobStatus.CANCELLED, reason=getattr(args, "reason", None) or "Kullanıcı iptali")
    if is_json_mode(args):
        print(json.dumps({"status": "cancelled", "job_id": job.id}, indent=2))
    else:
        console.print(f"[bold green][OK] İş {job.id} iptal edildi.[/bold green]")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    transition(conn, job.id, job.status, JobStatus.PAUSED, reason="Kullanıcı duraklattı")
    if is_json_mode(args):
        print(json.dumps({"status": "paused", "job_id": job.id}, indent=2))
    else:
        console.print(f"[bold green][OK] İş {job.id} duraklatıldı.[/bold green]")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    transition(conn, job.id, job.status, JobStatus.QUEUED, reason="Kullanıcı devam ettirdi")
    if is_json_mode(args):
        print(json.dumps({"status": "queued", "job_id": job.id}, indent=2))
    else:
        console.print(f"[bold green][OK] İş {job.id} kuyruğa alındı (devam ediyor).[/bold green]")
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    job = jobs_store.get_job(args.job_id)
    if not job:
        err_console.print(f"[red]İş bulunamadı: {args.job_id}[/red]")
        return 1

    if job.status != JobStatus.FAILED:
        err_console.print(f"[yellow]Yalnızca failed durumundaki işler yeniden denenebilir (şu anki durum: {job.status.value}).[/yellow]")
        return 1

    new_max = job.attempt + 3
    jobs_store.update_job(job.id, max_attempts=new_max)
    transition(conn, job.id, JobStatus.FAILED, JobStatus.QUEUED, reason=f"Yeniden denendi (yeni sınır: {new_max})")

    if is_json_mode(args):
        print(json.dumps({"status": "queued", "job_id": job.id, "max_attempts": new_max}, indent=2))
    else:
        console.print(f"[bold green][OK] İş {job.id} tekrar kuyruğa alındı (max_attempts: {new_max}).[/bold green]")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    events_store = EventsStore(conn)

    job_id = getattr(args, "job", None)
    event_type = getattr(args, "type", None)
    limit = getattr(args, "limit", 20)
    follow = getattr(args, "follow", False)

    events = events_store.list_events(job_id=job_id, event_type=event_type, limit=limit)
    events.reverse()
    last_id = 0
    for e in events:
        last_id = max(last_id, e.id)
        if is_json_mode(args):
            print(json.dumps({"id": e.id, "ts": e.ts, "event": e.event, "job_id": e.job_id, "payload": e.payload}, ensure_ascii=False))
        else:
            j_str = f"[{e.job_id}]" if e.job_id else "[-]"
            console.print(f"[dim]{e.ts[:19]}[/dim] [cyan]{j_str:<18}[/cyan] [bold magenta]{e.event:<18}[/bold magenta] {json.dumps(e.payload or {}, ensure_ascii=False)}")

    if not follow:
        return 0

    try:
        import time
        while True:
            time.sleep(0.5)
            new_events = events_store.list_events(since_id=last_id, job_id=job_id, event_type=event_type, limit=50)
            new_events.reverse()
            for e in new_events:
                last_id = max(last_id, e.id)
                if is_json_mode(args):
                    print(json.dumps({"id": e.id, "ts": e.ts, "event": e.event, "job_id": e.job_id, "payload": e.payload}, ensure_ascii=False))
                else:
                    j_str = f"[{e.job_id}]" if e.job_id else "[-]"
                    console.print(f"[dim]{e.ts[:19]}[/dim] [cyan]{j_str:<18}[/cyan] [bold magenta]{e.event:<18}[/bold magenta] {json.dumps(e.payload or {}, ensure_ascii=False)}")
    except KeyboardInterrupt:
        pass
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    conn = get_connection(get_db_path(get_home_arg(args)))
    init_db(conn)
    jobs_store = JobsStore(conn)
    events_store = EventsStore(conn)
    meta_store = MetaStore(conn)

    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    import time

    def make_watch_layout() -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="jobs", ratio=2),
            Layout(name="events", ratio=1)
        )

        sup_lease = meta_store.get("supervisor_lease")
        sup_status = f"[green]AKTİF ({sup_lease[:8]})[/green]" if sup_lease else "[yellow]DURDU[/yellow]"

        all_jobs = jobs_store.list_jobs(limit=100)
        running = [j for j in all_jobs if j.status == JobStatus.RUNNING]
        queued = [j for j in all_jobs if j.status == JobStatus.QUEUED]
        review = [j for j in all_jobs if j.status == JobStatus.AWAITING_REVIEW]

        header_table = Table.grid(expand=True)
        header_table.add_column(justify="left")
        header_table.add_column(justify="right")
        header_table.add_row(
            f" [bold cyan]AGENT BUS CANLI İZLEME[/bold cyan] │ Supervisor: {sup_status} │ Çalışan: [bold green]{len(running)}/4[/bold green] │ Kuyruk: [bold yellow]{len(queued)}[/bold yellow] │ İnceleme: [bold magenta]{len(review)}[/bold magenta]",
            f"[dim]{utc_now_iso()}[/dim] "
        )
        layout["header"].update(Panel(header_table, style="blue"))

        # İşler Tablosu
        t_jobs = Table(expand=True, box=None)
        t_jobs.add_column("İş ID", style="cyan", width=16)
        t_jobs.add_column("Başlık", style="white")
        t_jobs.add_column("Durum", style="bold", width=16)
        t_jobs.add_column("Öncelik", justify="center", width=8)
        t_jobs.add_column("Deneme", justify="center", width=8)
        t_jobs.add_column("Worktree", style="dim", width=22)

        for j in all_jobs[:15]:
            st_color = "green" if j.status == JobStatus.RUNNING else "yellow" if j.status == JobStatus.QUEUED else "magenta" if j.status == JobStatus.AWAITING_REVIEW else "white"
            wt_name = Path(j.worktree_path).name if j.worktree_path else "-"
            t_jobs.add_row(
                j.id,
                j.title[:35],
                f"[{st_color}]{j.status.value}[/{st_color}]",
                str(j.priority),
                f"{j.attempt}/{j.max_attempts}",
                wt_name
            )
        layout["jobs"].update(Panel(t_jobs, title="İş Durumları", border_style="cyan"))

        # Olaylar Tablosu
        latest_events = events_store.list_events(limit=8)
        latest_events.reverse()
        t_ev = Table(expand=True, box=None)
        t_ev.add_column("Zaman", style="dim", width=12)
        t_ev.add_column("İş", style="cyan", width=16)
        t_ev.add_column("Olay", style="bold magenta", width=18)
        t_ev.add_column("Detay", style="white")
        for e in latest_events:
            j_str = e.job_id or "-"
            payload_str = json.dumps(e.payload or {}, ensure_ascii=False)
            if len(payload_str) > 55:
                payload_str = payload_str[:52] + "..."
            t_ev.add_row(e.ts[11:19], j_str, e.event, payload_str)
        layout["events"].update(Panel(t_ev, title="Son Olaylar (events)", border_style="magenta"))

        return layout

    if getattr(args, "once", False) or is_json_mode(args):
        console.print(make_watch_layout())
        return 0

    try:
        with Live(make_watch_layout(), refresh_per_second=2, console=console) as live:
            while True:
                time.sleep(0.5)
                live.update(make_watch_layout())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    home_dir = get_home_dir(get_home_arg(args))
    from agentbus.tui.app import AgentBusTuiApp
    app = AgentBusTuiApp(home_dir)
    app.run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", type=str, default=argparse.SUPPRESS, help="Özel Agent Bus veri dizini (.data)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Makine-okunur JSON çıktısı üret")

    parser = argparse.ArgumentParser(
        prog="agentbus",
        description="AGENT BUS - Kalıcı SQLite Tabanlı Ajan Otobüsü",
        parents=[common]
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", parents=[common], help="Agent Bus veritabanını ve klasör yapısını kurar")
    p_init.add_argument("--repo", type=str, default=None, help="Varsayılan hedef git deposu yolu")
    p_init.set_defaults(func=cmd_init)

    # doctor
    p_doctor = subparsers.add_parser("doctor", parents=[common], help="Ortam ve bağımlılık sağlık kontrolü")
    p_doctor.set_defaults(func=cmd_doctor)

    # submit
    p_submit = subparsers.add_parser("submit", parents=[common], help="Kuyruğa yeni bir iş ekler")
    p_submit.add_argument("-t", "--title", required=True, help="İş başlığı")
    p_submit.add_argument("-f", "--file", help="Görev metni dosyası (.md)")
    p_submit.add_argument("-m", "--task", help="Doğrudan görev metni")
    p_submit.add_argument("--paths", help="İzinli yollar (virgülle ayrılmış glob)")
    p_submit.add_argument("--after", help="Bağımlı iş kimlikleri (virgülle ayrılmış)")
    p_submit.add_argument("--priority", type=int, default=5, help="Öncelik (varsayılan: 5)")
    p_submit.add_argument("--profile", default="default", help="Ajan profili")
    p_submit.add_argument("--key", help="İdempotency anahtarı (mükerrerliği önler)")
    p_submit.add_argument("--repo", help="İşe özel hedef git repo yolu")
    p_submit.add_argument("--parent", help="Üst iş kimliği (varsa)")
    p_submit.set_defaults(func=cmd_submit)

    # ls
    p_ls = subparsers.add_parser("ls", parents=[common], help="Kayıtlı işleri listeler")
    p_ls.add_argument("--status", help="Duruma göre filtrele (queued, running, ...)")
    p_ls.add_argument("--limit", type=int, default=50, help="Listelenecek en çok kayıt")
    p_ls.set_defaults(func=cmd_ls)

    # show
    p_show = subparsers.add_parser("show", parents=[common], help="Bir işin tüm detaylarını gösterir")
    p_show.add_argument("job_id", help="İş kimliği (örn. j_20261029_0001)")
    p_show.add_argument("--turns", action="store_true", help="Turları da listele")
    p_show.add_argument("--events", type=int, default=10, help="Son N olayı listele")
    p_show.set_defaults(func=cmd_show)

    # up
    p_up = subparsers.add_parser("up", parents=[common], help="Supervisor daemon'u başlatır")
    p_up.add_argument("--parallel", type=int, default=4, help="Paralel işçi sayısı (en çok 4)")
    p_up.add_argument("--detach", action="store_true", help="Arka planda bağımsız çalıştır")
    p_up.set_defaults(func=cmd_up)

    # down
    p_down = subparsers.add_parser("down", parents=[common], help="Supervisor'ı nazikçe durdurur")
    p_down.set_defaults(func=cmd_down)

    # recover
    p_rec = subparsers.add_parser("recover", parents=[common], help="Kira süresi geçmiş işleri kurtarır")
    p_rec.set_defaults(func=cmd_recover)

    # diff
    p_diff = subparsers.add_parser("diff", parents=[common], help="İş worktree diff'ini görüntüler")
    p_diff.add_argument("job_id", help="İş kimliği")
    p_diff.set_defaults(func=cmd_diff)

    # review
    p_rev = subparsers.add_parser("review", parents=[common], help="İnceleme bekleyen işi onaylar veya reddeder")
    p_rev.add_argument("job_id", help="İş kimliği")
    p_rev_grp = p_rev.add_mutually_exclusive_group(required=True)
    p_rev_grp.add_argument("--approve", action="store_true", help="İşi onayla ve entegre et")
    p_rev_grp.add_argument("--reject", type=str, metavar="NEDEN", help="İşi reddet")
    p_rev.set_defaults(func=cmd_review)

    # merge
    p_merge = subparsers.add_parser("merge", parents=[common], help="İşi entegrasyon dalına birleştirir (§15 Aşama 1)")
    p_merge.add_argument("job_id", help="İş kimliği")
    p_merge.set_defaults(func=cmd_merge)

    # promote
    p_prom = subparsers.add_parser("promote", parents=[common], help="Entegrasyon dalını main dalına terfi eder (§15 Aşama 2)")
    p_prom.add_argument("repo", nargs="?", default=None, help="Hedef repo dizini")
    p_prom.set_defaults(func=cmd_promote)

    # revert
    p_revert = subparsers.add_parser("revert", parents=[common], help="İşin entegrasyon merge commit'ini geri alır")
    p_revert.add_argument("job_id", help="İş kimliği")
    p_revert.set_defaults(func=cmd_revert)

    # gc
    p_gc = subparsers.add_parser("gc", parents=[common], help="Kullanılmayan/tamamlanan worktree'leri temizler")
    p_gc.add_argument("--repo", type=str, default=None, help="Hedef repo dizini")
    p_gc.set_defaults(func=cmd_gc)

    # msg
    p_msg = subparsers.add_parser("msg", parents=[common], help="Ajanlar ve orkestratör arası mesajlaşma")
    p_msg_subs = p_msg.add_subparsers(dest="msg_command", required=True)

    # msg send
    p_msg_send = p_msg_subs.add_parser("send", parents=[common], help="Mesaj gönder")
    p_msg_send.add_argument("--to", required=True, help="Alıcı iş kimliği veya 'orchestrator' veya 'all'")
    p_msg_send.add_argument("--sender", help="Gönderen kimliği (varsayılan: AGENTBUS_JOB_ID veya orchestrator)")
    p_msg_send.add_argument("body", help="Mesaj metni")
    p_msg_send.set_defaults(func=cmd_msg_send)

    # msg inbox
    p_msg_inbox = p_msg_subs.add_parser("inbox", parents=[common], help="Gelen kutusunu oku")
    p_msg_inbox.add_argument("--for", dest="for_id", help="Hangi alıcı için listelensin")
    p_msg_inbox.add_argument("--unread", action="store_true", help="Yalnızca okunmamış mesajları listele")
    p_msg_inbox.add_argument("--mark-read", action="store_true", help="Mesajları okundu olarak işaretle")
    p_msg_inbox.add_argument("--limit", type=int, default=50, help="En çok kaç mesaj listelensin")
    p_msg_inbox.set_defaults(func=cmd_msg_inbox)

    # board
    p_board = subparsers.add_parser("board", parents=[common], help="Ortak kara tahta")
    p_board_subs = p_board.add_subparsers(dest="board_command", required=True)

    # board get
    p_board_get = p_board_subs.add_parser("get", parents=[common], help="Tahtadan değer oku")
    p_board_get.add_argument("key", help="Anahtar adı")
    p_board_get.set_defaults(func=cmd_board_get)

    # board set
    p_board_set = p_board_subs.add_parser("set", parents=[common], help="Tahtaya değer yaz")
    p_board_set.add_argument("key", help="Anahtar adı")
    p_board_set.add_argument("value", help="Değer")
    p_board_set.add_argument("--author", help="Yazar kimliği")
    p_board_set.set_defaults(func=cmd_board_set)

    # board ls
    p_board_ls = p_board_subs.add_parser("ls", parents=[common], help="Tahtadaki tüm girdileri listele")
    p_board_ls.set_defaults(func=cmd_board_ls)

    # claim
    p_claim = subparsers.add_parser("claim", parents=[common], help="Dosya yolu veya glob için kilit al")
    p_claim.add_argument("glob", help="Dosya yolu glob kalıbı (örn: src/api/**)")
    p_claim.add_argument("--job", help="İş kimliği (varsayılan: AGENTBUS_JOB_ID)")
    p_claim.set_defaults(func=cmd_claim)

    # unclaim
    p_unclaim = subparsers.add_parser("unclaim", parents=[common], help="Dosya kilidini bırak")
    p_unclaim.add_argument("glob", help="Bırakılacak glob kalıbı")
    p_unclaim.add_argument("--job", help="İş kimliği")
    p_unclaim.set_defaults(func=cmd_unclaim)

    # open
    p_open = subparsers.add_parser("open", parents=[common], help="İş oturumunu interaktif açar (human_attached)")
    p_open.add_argument("job_id", help="İş kimliği")
    p_open.add_argument("--here", action="store_true", help="Mevcut terminalde aç")
    p_open.set_defaults(func=cmd_open)

    # detach
    p_detach = subparsers.add_parser("detach", parents=[common], help="İşi supervisor'a devredip kuyruğa bırakır")
    p_detach.add_argument("job_id", help="İş kimliği")
    p_detach.set_defaults(func=cmd_detach)

    # reply
    p_reply = subparsers.add_parser("reply", parents=[common], help="needs_input sorusuna yanıt ver")
    p_reply.add_argument("job_id", help="İş kimliği")
    p_reply.add_argument("answer", help="Yanıt metni")
    p_reply.set_defaults(func=cmd_reply)

    # send
    p_send = subparsers.add_parser("send", parents=[common], help="İşe ek talimat gönder")
    p_send.add_argument("job_id", help="İş kimliği")
    p_send.add_argument("instruction", help="Talimat metni")
    p_send.set_defaults(func=cmd_send)

    # cancel
    p_cancel = subparsers.add_parser("cancel", parents=[common], help="İşi iptal et")
    p_cancel.add_argument("job_id", help="İş kimliği")
    p_cancel.add_argument("--reason", default="Kullanıcı iptali", help="İptal gerekçesi")
    p_cancel.set_defaults(func=cmd_cancel)

    # pause
    p_pause = subparsers.add_parser("pause", parents=[common], help="İşi duraklat")
    p_pause.add_argument("job_id", help="İş kimliği")
    p_pause.set_defaults(func=cmd_pause)

    # resume
    p_resume = subparsers.add_parser("resume", parents=[common], help="Duraklatılan işi devam ettir")
    p_resume.add_argument("job_id", help="İş kimliği")
    p_resume.set_defaults(func=cmd_resume)

    # retry
    p_retry = subparsers.add_parser("retry", parents=[common], help="Başarısız işi yeniden dene")
    p_retry.add_argument("job_id", help="İş kimliği")
    p_retry.set_defaults(func=cmd_retry)

    # tail
    p_tail = subparsers.add_parser("tail", parents=[common], help="Olay akışını görüntüler")
    p_tail.add_argument("--job", help="İş kimliğine göre filtrele")
    p_tail.add_argument("--type", help="Olay türüne göre filtrele")
    p_tail.add_argument("--limit", type=int, default=20, help="Listelenecek olay sayısı")
    p_tail.add_argument("-f", "--follow", action="store_true", help="Canlı akışı izle")
    p_tail.set_defaults(func=cmd_tail)

    # watch
    p_watch = subparsers.add_parser("watch", parents=[common], help="Canlı pano (Rich): işler, yuvalar, son olaylar")
    p_watch.add_argument("--once", action="store_true", help="Tek seferlik tablo basıp çık")
    p_watch.set_defaults(func=cmd_watch)

    # tui
    p_tui = subparsers.add_parser("tui", parents=[common], help="Tam Textual gömülü ConPTY arayüzünü başlatır")
    p_tui.set_defaults(func=cmd_tui)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not check_agent_role_guard(args.command, args):
        sys.exit(13)
    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
