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

from agentbus.db import get_connection, init_db, get_home_dir, get_db_path
from agentbus.models import JobStatus, Job, Turn, Event
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


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", type=str, default=None, help="Özel Agent Bus veri dizini (.data)")
    common.add_argument("--json", action="store_true", help="Makine-okunur JSON çıktısı üret")

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

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
