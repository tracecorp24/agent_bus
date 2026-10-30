"""
AGENT BUS - Textual Tabanlı Gömülü Çoklu Ajan Arayüzü (TUI Dashboard).

Orkestratör Master Konsolu, Dinamik Ajan Döşemeleri, İş Listesi,
Canlı Olay Akışı ve Gömülü ConPTY Terminal Desteği sunar.
"""

from __future__ import annotations
import asyncio
import os
import sys
import json
import time
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, Grid, Container
from textual.widgets import Static, Button, RichLog, Label, ListItem, ListView
from textual import events
from rich.text import Text
from rich.markup import escape

from agentbus.db import get_connection, init_db, transition
from agentbus.models import JobStatus, Job, Event, utc_now_iso
from agentbus.store.jobs import JobsStore
from agentbus.store.turns import TurnsStore
from agentbus.store.events import EventsStore
from agentbus.store.meta import MetaStore
from agentbus.store.messages import MessagesStore
from agentbus.tui.cli_input import CliCommandInput
from agentbus.tui.panes.embedded_terminal import EmbeddedTerminalWidget


STATUS_ICONS = {
    JobStatus.RUNNING: "[bold green]●[/bold green]",
    JobStatus.QUEUED: "[dim yellow]○[/dim yellow]",
    JobStatus.BLOCKED: "[bold yellow]◐[/bold yellow]",
    JobStatus.NEEDS_INPUT: "[bold magenta]?[/bold magenta]",
    JobStatus.HUMAN_ATTACHED: "[bold cyan]⌨[/bold cyan]",
    JobStatus.ATTACH_PENDING: "[yellow]⏳[/yellow]",
    JobStatus.AWAITING_REVIEW: "[bold blue]🔍[/bold blue]",
    JobStatus.INTEGRATED: "[green]✓[/green]",
    JobStatus.PROMOTED: "[bold green]★[/bold green]",
    JobStatus.CONFLICT: "[bold red]⚔[/bold red]",
    JobStatus.TESTS_FAILED: "[bold red]✗[/bold red]",
    JobStatus.FAILED: "[red]✗[/red]",
    JobStatus.CANCELLED: "[dim]⊘[/dim]",
    JobStatus.PAUSED: "[dim yellow]⏸[/dim yellow]",
}


class AgentTileWidget(Vertical):
    """Tek bir ajana ait eşit boyutlu döşeme (Tile). Canlı çıktı veya ConPTY terminali gösterir."""

    DEFAULT_CSS = """
    AgentTileWidget {
        border: solid #444444;
        background: #181818;
        height: 1fr;
        width: 1fr;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }
    AgentTileWidget:focus-within {
        border: solid #00FF7F;
    }
    .tile-header {
        height: 1;
        background: #252525;
        color: #FFE135;
        padding: 0 1;
        layout: horizontal;
    }
    .tile-title {
        width: 1fr;
        text-style: bold;
    }
    .tile-body {
        height: 1fr;
        background: #121212;
    }
    .btn-tile {
        height: 1;
        min-width: 10;
        padding: 0 1;
        margin-left: 1;
        border: none;
    }
    """

    def __init__(self, job: Job, app_ref: AgentBusTuiApp) -> None:
        super().__init__(id=f"tile_{job.id}")
        self.job = job
        self.app_ref = app_ref
        self.is_human_attached = (job.status == JobStatus.HUMAN_ATTACHED)
        self.log_widget = RichLog(highlight=True, markup=True, classes="tile-body")
        self.terminal_widget: Optional[EmbeddedTerminalWidget] = None
        self.last_stream_file: Optional[Path] = None
        self.last_stream_offset: int = 0
        self._initial_logged: bool = False

    def compose(self) -> ComposeResult:
        st_icon = STATUS_ICONS.get(self.job.status, "")
        header_text = f"{st_icon} {self.job.id} │ {self.job.title[:20]} │ {self.job.status.value}"
        with Horizontal(classes="tile-header"):
            yield Label(header_text, classes="tile-title", id=f"title_{self.job.id}")
            yield Button("Bağlan", id=f"btn_attach_{self.job.id}", classes="btn-tile", variant="primary")
            yield Button("Devret", id=f"btn_detach_{self.job.id}", classes="btn-tile", variant="warning")

        yield self.log_widget

    def update_job(self, job: Job) -> None:
        self.job = job
        try:
            lbl = self.query_one(f"#title_{self.job.id}", Label)
            st_icon = STATUS_ICONS.get(self.job.status, "")
            lbl.update(f"{st_icon} {self.job.id} │ {self.job.title[:20]} │ {self.job.status.value}")
        except Exception:
            pass

        self.update_logs()

    def update_logs(self) -> None:
        """İşin çalışma çıktısını diskteki stream dosyasından canlı okur."""
        if not self._initial_logged:
            self._initial_logged = True
            self.log_widget.write(f"[bold cyan]▶ Görev:[/bold cyan] {escape(self.job.title)}")
            if self.job.task_md:
                self.log_widget.write(f"[dim]{escape(self.job.task_md[:120])}[/dim]")

        turns_dir = self.app_ref.home_dir / "runs" / self.job.id / "turns"
        if not turns_dir.exists():
            return

        stream_files = sorted(turns_dir.glob("*.stream.jsonl"))
        if not stream_files:
            return

        latest_file = stream_files[-1]
        if self.last_stream_file != latest_file:
            self.last_stream_file = latest_file
            self.last_stream_offset = 0

        try:
            if latest_file.exists():
                with open(latest_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self.last_stream_offset)
                    new_text = f.read()
                    self.last_stream_offset = f.tell()

                if new_text:
                    for line in new_text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            evt = data.get("event")
                            if evt == "step_update":
                                su = data.get("step_update", {})
                                if su.get("step_type") == "tool" and su.get("state") == "ACTIVE":
                                    self.log_widget.write(f"[yellow]⚡ Araç:[/yellow] [bold]{escape(str(su.get('tool_name')))}[/bold]")
                                elif su.get("text_delta"):
                                    self.log_widget.write(f"[dim]{escape(str(su.get('text_delta')))}[/dim]")
                            elif evt == "result":
                                self.log_widget.write("[bold green]✓ Ajan turu tamamladı.[/bold green]")
                        except Exception:
                            self.log_widget.write(f"[dim]{escape(line[:80])}[/dim]")
        except Exception:
            pass

        if self.job.result_summary and self.job.status == JobStatus.AWAITING_REVIEW:
            if not getattr(self, "_summary_written", False):
                self._summary_written = True
                self.log_widget.write(f"[bold green]Sonuç Özeti:[/bold green] {escape(self.job.result_summary)}")

    def append_log_line(self, line: str) -> None:
        self.log_widget.write(line)

    def attach_terminal(self) -> None:
        """İşi human_attached yapar ve gömülü ConPTY terminalini başlatır."""
        if self.terminal_widget:
            return

        conn = self.app_ref.get_db()
        if self.job.status == JobStatus.RUNNING:
            transition(conn, self.job.id, JobStatus.RUNNING, JobStatus.ATTACH_PENDING, reason="TUI bağlanma isteği")
            self.append_log_line("[yellow]Çalışan turun tamamlanması bekleniyor (G3: attach_pending)...[/yellow]")
            return

        if self.job.status != JobStatus.HUMAN_ATTACHED:
            transition(conn, self.job.id, self.job.status, JobStatus.HUMAN_ATTACHED, reason="TUI'den bağlanıldı")

        self.is_human_attached = True
        work_dir = self.job.worktree_path or str(self.app_ref.home_dir)
        conv_args = f"--conversation {self.job.conversation_id}" if self.job.conversation_id else ""
        agy_cmd = f"agy {conv_args}".strip()

        self.terminal_widget = EmbeddedTerminalWidget(
            initial_command=agy_cmd,
            cwd=work_dir,
            classes="tile-body"
        )
        self.log_widget.display = False
        self.mount(self.terminal_widget)
        self.terminal_widget.focus()
        self.append_log_line(f"[bold green]Terminal bağlandı ({work_dir})[/bold green]")

    def detach_terminal(self) -> None:
        """Terminali kapatır ve işi supervisor kuyruğuna (QUEUED) geri devreder."""
        if self.terminal_widget:
            self.terminal_widget.terminate_process()
            self.terminal_widget.remove()
            self.terminal_widget = None

        self.log_widget.display = True
        self.is_human_attached = False

        conn = self.app_ref.get_db()
        if self.job.status in (JobStatus.HUMAN_ATTACHED, JobStatus.ATTACH_PENDING):
            transition(conn, self.job.id, self.job.status, JobStatus.QUEUED, reason="TUI'den devredildi (detach)")

        self.append_log_line("[bold cyan]İş devredildi (detach). Supervisor kuyruğunda devam edecek.[/bold cyan]")


class AgentBusTuiApp(App):
    """Ana AGENT BUS Dashboard Arayüzü (Master Konsol + Ajan Pencereleri + Liste)."""

    BINDINGS = [
        ("q", "quit", "Çıkış"),
        ("f1", "layout_master_focus", "Master Odak (60/40)"),
        ("f2", "layout_equal", "Eşit (50/50)"),
        ("f3", "layout_agents_focus", "Ajan Odak (35/65)"),
        ("[", "shrink_master", "Master Daralt"),
        ("]", "grow_master", "Master Genişlet"),
        ("r", "refresh_data", "Yenile"),
    ]

    CSS = """
    Screen {
        background: #121212;
        color: #E0E0E0;
        layout: vertical;
    }
    #top_bar {
        height: 1;
        background: #1E1E1E;
        color: #FFE135;
        padding: 0 1;
        layout: horizontal;
    }
    #lbl_top_stats {
        width: 1fr;
        text-style: bold;
    }
    .top-btn {
        height: 1;
        min-width: 8;
        margin-left: 1;
        background: #2D2D2D;
        color: #E0E0E0;
        border: none;
        padding: 0 1;
    }
    .top-btn:hover {
        background: #FFE135;
        color: #000000;
        text-style: bold;
    }
    .top-btn-active {
        background: #00FF7F;
        color: #000000;
        text-style: bold;
    }
    #main_body {
        height: 1fr;
        layout: horizontal;
    }
    #left_panel {
        width: 32;
        background: #181818;
        border-right: solid #333333;
        layout: vertical;
    }
    #job_list_view {
        height: 1fr;
        background: #141414;
    }
    #left_actions {
        height: 2;
        background: #1C1C1C;
        layout: horizontal;
        padding: 0 1;
        border-top: solid #333333;
    }
    .btn-quick {
        height: 1;
        min-width: 8;
        margin-right: 1;
        border: none;
        padding: 0 1;
    }
    #master_panel {
        width: 58%;
        background: #141414;
        border-right: solid #333333;
        layout: vertical;
    }
    #master_log_view {
        height: 1fr;
        background: #0E0E0E;
        padding: 0 1;
    }
    #agents_area {
        width: 42%;
        background: #161616;
        layout: vertical;
    }
    #agents_container {
        height: 1fr;
        layout: vertical;
        padding: 0;
        overflow: hidden;
    }
    #lbl_empty_tiles {
        height: 1fr;
        content-align: center middle;
        text-align: center;
        color: #777777;
        padding: 2;
    }
    #cmd_bar {
        height: 3;
        background: #202020;
        border-top: solid #FFE135;
        padding: 0 1;
    }
    .panel-header {
        height: 1;
        background: #252525;
        color: #00FF7F;
        text-style: bold;
        padding: 0 1;
    }
    """

    def __init__(self, home_dir: Path, periodic_sync: bool = True, auto_start_supervisor: Optional[bool] = None):
        super().__init__()
        self.home_dir = home_dir
        self.periodic_sync = periodic_sync
        self.auto_start_supervisor = periodic_sync if auto_start_supervisor is None else auto_start_supervisor
        self.db_path = home_dir / "bus.db"
        self._conn = None
        self.tiles: Dict[str, AgentTileWidget] = {}
        self.last_event_id = 0
        self._last_job_snapshot = None
        self.master_ratio = 58
        self.embedded_supervisor = None
        self.sup_thread = None

    def get_db(self):
        if self._conn is None:
            self._conn = get_connection(self.db_path)
            init_db(self._conn)
        return self._conn

    def compose(self) -> ComposeResult:
        with Horizontal(id="top_bar"):
            yield Label("AGENT BUS ─ Dashboard yükleniyor...", id="lbl_top_stats")
            yield Button("Master Odak [F1]", id="btn_layout_master", classes="top-btn top-btn-active")
            yield Button("Eşit [F2]", id="btn_layout_equal", classes="top-btn")
            yield Button("Ajan Odak [F3]", id="btn_layout_agents", classes="top-btn")
            yield Button("◀", id="btn_master_shrink", classes="top-btn")
            yield Button("▶", id="btn_master_grow", classes="top-btn")

        with Horizontal(id="main_body"):
            # 1. Sol Panel: İş Listesi
            with Vertical(id="left_panel"):
                yield Label("📋 İŞ LİSTESİ", classes="panel-header")
                yield ListView(id="job_list_view")
                with Horizontal(id="left_actions"):
                    yield Button("+ İş", id="btn_quick_new", classes="btn-quick", variant="primary")
                    yield Button("⚡ Plan", id="btn_quick_plan", classes="btn-quick", variant="default")
                    yield Button("🔄", id="btn_quick_refresh", classes="btn-quick", variant="default")

            # 2. Orta Panel: Master Konsol Panosu (Orkestratör - En Büyük)
            with Vertical(id="master_panel"):
                yield Label("👑 MASTER KONSOL (Orkestratör & Sistem Akışı)", classes="panel-header", id="lbl_master_header")
                yield RichLog(id="master_log_view", markup=True, highlight=True)

            # 3. Sağ Panel: Ajan Pencereleri (Eşit Boyutlu Döşemeler)
            with Vertical(id="agents_area"):
                yield Label("🤖 AJAN PENCERELERİ", classes="panel-header", id="lbl_agents_header")
                with Container(id="agents_container"):
                    yield Static(
                        "Henüz aktif ajan penceresi yok.\nİşler başladığında pencereleri burada eşit olarak açılacaktır.",
                        id="lbl_empty_tiles"
                    )

        # 4. Alt Panel: İnteraktif CLI Komut Çubuğu
        with Horizontal(id="cmd_bar"):
            yield CliCommandInput(
                placeholder="agentbus komutu girin (örn: submit -t 'Yeni İş' -m 'Detay', review j_01 --approve, merge j_01, promote)",
                id="tui_cmd_input"
            )

    def on_mount(self) -> None:
        self.apply_layout_ratio(self.master_ratio)
        self.log_master("[bold yellow]════════════════════════════════════════════════════════════════[/bold yellow]")
        self.log_master("[bold green]AGENT BUS Dashboard başlatıldı.[/bold green] Tek terminal, çoklu ajan orkestrasyonu.")

        # Gömülü Supervisor: Arka plan süreç karmaşası olmadan TUI içinde otonom çalışır
        if self.auto_start_supervisor:
            try:
                from agentbus.supervisor import Supervisor
                self.embedded_supervisor = Supervisor(home_dir=self.home_dir, max_parallel=4)
                if self.embedded_supervisor.acquire_supervisor_lock():
                    self.sup_thread = threading.Thread(target=self.embedded_supervisor.start, daemon=True)
                    self.sup_thread.start()
                    self.log_master("[bold green]✓ Gömülü Supervisor aktif edildi (4 paralel işçi yuvası devrede).[/bold green]")
                else:
                    self.log_master("[yellow]ℹ Harici bir Supervisor oturumu zaten aktif. Gömülü supervisor devrede değil.[/yellow]")
                    self.embedded_supervisor = None
            except Exception as e:
                self.log_master(f"[red]Supervisor başlatılamadı: {e}[/red]")

        self.log_master("[dim]Yardım: Alt çubuğa komut yazabilirsiniz. Kısayollar: [F1] Master Odak, [F2] Eşit, [F3] Ajan Odak, [q] Çıkış.[/dim]")
        self.sync_db()

        if self.periodic_sync:
            self.set_interval(0.5, self.sync_db)

    def on_unmount(self) -> None:
        if self.embedded_supervisor:
            self.embedded_supervisor.stop()

    def log_master(self, text: str) -> None:
        """Master konsola biçimlendirilmiş satır ekler."""
        try:
            mlog = self.query_one("#master_log_view", RichLog)
            mlog.write(text)
        except Exception:
            pass

    def apply_layout_ratio(self, master_pct: int) -> None:
        """Master ve Ajan panellerinin genişlik oranını ayarlar."""
        self.master_ratio = max(25, min(80, master_pct))
        agents_pct = 100 - self.master_ratio
        try:
            mp = self.query_one("#master_panel")
            ap = self.query_one("#agents_area")
            mp.styles.width = f"{self.master_ratio}%"
            ap.styles.width = f"{agents_pct}%"
        except Exception:
            pass

    def action_layout_master_focus(self) -> None:
        self.apply_layout_ratio(60)
        self._update_top_btn("btn_layout_master")

    def action_layout_equal(self) -> None:
        self.apply_layout_ratio(50)
        self._update_top_btn("btn_layout_equal")

    def action_layout_agents_focus(self) -> None:
        self.apply_layout_ratio(35)
        self._update_top_btn("btn_layout_agents")

    def action_grow_master(self) -> None:
        self.apply_layout_ratio(self.master_ratio + 5)

    def action_shrink_master(self) -> None:
        self.apply_layout_ratio(self.master_ratio - 5)

    def action_refresh_data(self) -> None:
        self.sync_db()

    def _update_top_btn(self, active_id: str) -> None:
        for b_id in ["btn_layout_master", "btn_layout_equal", "btn_layout_agents"]:
            try:
                b = self.query_one(f"#{b_id}", Button)
                if b_id == active_id:
                    b.add_class("top-btn-active")
                else:
                    b.remove_class("top-btn-active")
            except Exception:
                pass

    def sync_db(self) -> None:
        """bus.db'den periyodik ve dayanıklı durum güncellemesi."""
        try:
            conn = self.get_db()
            jobs_store = JobsStore(conn)
            turns_store = TurnsStore(conn)
            events_store = EventsStore(conn)
            meta_store = MetaStore(conn)

            all_jobs = jobs_store.list_jobs(limit=50)
            running = [j for j in all_jobs if j.status == JobStatus.RUNNING]
            queued = [j for j in all_jobs if j.status == JobStatus.QUEUED]
            review = [j for j in all_jobs if j.status == JobStatus.AWAITING_REVIEW]

            sup_lease = meta_store.get("supervisor_lease")
            if self.embedded_supervisor:
                sup_str = "[bold green]GÖMÜLÜ AKTİF[/bold green]"
            elif sup_lease:
                sup_str = "[bold cyan]HARİCİ AKTİF[/bold cyan]"
            else:
                sup_str = "[dim yellow]DURDURULDU[/dim yellow]"

            # Üst durum çubuğu
            stats_text = (
                f"AGENT BUS ─ supervisor: {sup_str} │ "
                f"çalışan: [bold green]{len(running)}/4[/bold green] │ "
                f"kuyruk: [bold yellow]{len(queued)}[/bold yellow] │ "
                f"inceleme: [bold magenta]{len(review)}[/bold magenta] │ "
                f"düzen: %{self.master_ratio} Master / %{100 - self.master_ratio} Ajanlar"
            )
            self.query_one("#lbl_top_stats", Label).update(stats_text)

            # Sol liste güncelleme (yalnızca değiştiğinde)
            list_view = self.query_one("#job_list_view", ListView)
            job_snapshot = [(j.id, j.status.value, j.title) for j in all_jobs[:30]]
            if self._last_job_snapshot != job_snapshot:
                self._last_job_snapshot = job_snapshot
                list_view.clear()
                for j in all_jobs[:30]:
                    icon = STATUS_ICONS.get(j.status, "")
                    item_text = f"{icon} {j.id} {j.title[:14]}"
                    list_view.append(ListItem(Label(item_text), id=f"item_{j.id}"))

            # Sağ panel: Ajan pencereleri (Tile sync)
            container = self.query_one("#agents_container", Container)
            active_ids = set()

            # Çalışan, inceleme bekleyen, insan bağlı veya son işler
            visible_jobs = running + review + [j for j in all_jobs if j.status == JobStatus.HUMAN_ATTACHED]
            if not visible_jobs and all_jobs:
                visible_jobs = all_jobs[:4]

            # Başlıkta aktif ajan sayısını güncelle
            header_lbl = self.query_one("#lbl_agents_header", Label)
            header_lbl.update(f"🤖 AJAN PENCERELERİ ({len(visible_jobs[:4])} Gösteriliyor / 4 Yuva)")

            empty_lbl = self.query_one("#lbl_empty_tiles", Static)
            if visible_jobs:
                empty_lbl.display = False
            else:
                empty_lbl.display = True

            for job in visible_jobs[:4]:
                active_ids.add(job.id)
                if job.id not in self.tiles:
                    tile = AgentTileWidget(job, self)
                    self.tiles[job.id] = tile
                    container.mount(tile)
                else:
                    self.tiles[job.id].update_job(job)

            # Kapanan işlerin döşemelerini kaldır
            for j_id in list(self.tiles.keys()):
                if j_id not in active_ids:
                    self.tiles[j_id].remove()
                    del self.tiles[j_id]

            # Master konsola yeni olayları ekle
            new_events = events_store.list_events(since_id=self.last_event_id, limit=30)
            new_events.reverse()
            if new_events:
                for e in new_events:
                    self.last_event_id = max(self.last_event_id, e.id)
                    j_info = f"[cyan]{e.job_id}[/cyan]" if e.job_id else "[dim]system[/dim]"
                    ts_info = f"[dim]{e.ts[11:19]}[/dim]"
                    ev_color = "red" if "error" in e.event or "failed" in e.event else "cyan"
                    payload_s = json.dumps(e.payload or {}, ensure_ascii=False)
                    if len(payload_s) > 60:
                        payload_s = payload_s[:57] + "..."
                    self.log_master(f"{ts_info} {j_info} [{ev_color}]{e.event}[/{ev_color}] {escape(payload_s)}")

        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        # Layout butonları
        if btn_id == "btn_layout_master":
            self.action_layout_master_focus()
        elif btn_id == "btn_layout_equal":
            self.action_layout_equal()
        elif btn_id == "btn_layout_agents":
            self.action_layout_agents_focus()
        elif btn_id == "btn_master_shrink":
            self.action_shrink_master()
        elif btn_id == "btn_master_grow":
            self.action_grow_master()

        # Sol panel hızlı butonlar
        elif btn_id == "btn_quick_new":
            cmd_in = self.query_one("#tui_cmd_input", CliCommandInput)
            cmd_in.value = "submit -t 'Yeni Görev' -m 'Açıklama'"
            cmd_in.focus()
        elif btn_id == "btn_quick_plan":
            cmd_in = self.query_one("#tui_cmd_input", CliCommandInput)
            cmd_in.value = "plan apply plan.yaml"
            cmd_in.focus()
        elif btn_id == "btn_quick_refresh":
            self.sync_db()

        # Ajan döşeme butonları
        elif btn_id.startswith("btn_attach_"):
            job_id = btn_id.replace("btn_attach_", "")
            if job_id in self.tiles:
                self.tiles[job_id].attach_terminal()
        elif btn_id.startswith("btn_detach_"):
            job_id = btn_id.replace("btn_detach_", "")
            if job_id in self.tiles:
                self.tiles[job_id].detach_terminal()

    async def on_cli_command_input_submitted(self, message: CliCommandInput.Submitted) -> None:
        """Alt komut satırından girilen komutu Master Konsolda çalıştırır."""
        cmd_text = message.value.strip()
        if not cmd_text:
            return

        self.log_master(f"[bold yellow]❯ agentbus {escape(cmd_text)}[/bold yellow]")

        from agentbus.cli import build_parser
        parser = build_parser()
        tokens = ["--home", str(self.home_dir)] + cmd_text.split()
        try:
            args = parser.parse_args(tokens)
            if hasattr(args, "func"):
                import io
                from contextlib import redirect_stdout, redirect_stderr
                buf = io.StringIO()
                with redirect_stdout(buf), redirect_stderr(buf):
                    rc = args.func(args)
                out = buf.getvalue().strip()
                if out:
                    for line in out.splitlines():
                        self.log_master(f"  {escape(line)}")
                else:
                    self.log_master(f"  [dim green]Komut tamamlandı (kod: {rc}).[/dim green]")
            else:
                self.log_master("  [red]Bilinmeyen veya eksik komut.[/red]")
        except SystemExit:
            pass
        except Exception as ex:
            self.log_master(f"  [bold red]Komut Hatası:[/bold red] {escape(str(ex))}")

        self.sync_db()
