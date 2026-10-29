"""
AGENT BUS - Textual Tabanlı Gömülü Çoklu Ajan Arayüzü (TUI).

minion-cli-main UI bileşenleri üzerine inşa edilmiş, tam gömülü ConPTY terminali,
dinamik döşemeli ajan görünümleri, canlı SQLite olay akışı ve dahili CLI komut satırı.
"""

from __future__ import annotations
import asyncio
import os
import sys
import json
import time
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
    JobStatus.QUEUED: "[dim]○[/dim]",
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
    """Tek bir ajana ait döşeme (Tile). Canlı log veya gömülü ConPTY terminali gösterir."""

    DEFAULT_CSS = """
    AgentTileWidget {
        border: heavy #444444;
        background: #181818;
        height: 1fr;
        width: 1fr;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }
    AgentTileWidget:focus-within {
        border: heavy #00FF7F;
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
    .tile-actions {
        height: 1;
        background: #202020;
        layout: horizontal;
        padding: 0 1;
    }
    """

    def __init__(self, job: Job, app_ref: AgentBusTuiApp) -> None:
        super().__init__(id=f"tile_{job.id}")
        self.job = job
        self.app_ref = app_ref
        self.is_human_attached = (job.status == JobStatus.HUMAN_ATTACHED)
        self.log_widget = RichLog(highlight=True, markup=True, classes="tile-body")
        self.terminal_widget: Optional[EmbeddedTerminalWidget] = None
        self.last_stream_offset = 0

    def compose(self) -> ComposeResult:
        st_icon = STATUS_ICONS.get(self.job.status, "")
        header_text = f"{st_icon} {self.job.id} │ {self.job.title[:25]} │ {self.job.status.value}"
        with Horizontal(classes="tile-header"):
            yield Label(header_text, classes="tile-title", id=f"title_{self.job.id}")
            yield Button("Bağlan (Enter)", id=f"btn_attach_{self.job.id}", classes="btn-attach", variant="primary")
            yield Button("Devret (Detach)", id=f"btn_detach_{self.job.id}", classes="btn-detach", variant="warning")

        yield self.log_widget

    def update_job(self, job: Job) -> None:
        self.job = job
        try:
            lbl = self.query_one(f"#title_{self.job.id}", Label)
            st_icon = STATUS_ICONS.get(self.job.status, "")
            lbl.update(f"{st_icon} {self.job.id} │ {self.job.title[:25]} │ {self.job.status.value}")
        except Exception:
            pass

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
    """Ana AGENT BUS Textual Komuta ve İzleme Arayüzü."""

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
    #main_body {
        height: 1fr;
        layout: horizontal;
    }
    #left_panel {
        width: 34;
        background: #181818;
        border-right: solid #333333;
        layout: vertical;
    }
    #center_panel {
        width: 1fr;
        height: 1fr;
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1 1;
        padding: 1;
    }
    #right_panel {
        width: 40;
        background: #161616;
        border-left: solid #333333;
        layout: vertical;
    }
    #cmd_bar {
        height: 3;
        background: #202020;
        border-top: solid #444444;
        padding: 0 1;
    }
    .panel-header {
        height: 1;
        background: #282828;
        color: #00FF7F;
        text-style: bold;
        padding: 0 1;
    }
    """

    def __init__(self, home_dir: Path, periodic_sync: bool = True):
        super().__init__()
        self.home_dir = home_dir
        self.periodic_sync = periodic_sync
        self.db_path = home_dir / "bus.db"
        self._conn = None
        self.tiles: Dict[str, AgentTileWidget] = {}
        self.last_event_id = 0
        self.active_jobs_count = 0
        self._last_job_snapshot = None

    def get_db(self):
        if self._conn is None:
            self._conn = get_connection(self.db_path)
            init_db(self._conn)
        return self._conn

    def compose(self) -> ComposeResult:
        with Horizontal(id="top_bar"):
            yield Label("AGENT BUS ─ başlatılıyor...", id="lbl_top_stats")

        with Horizontal(id="main_body"):
            with Vertical(id="left_panel"):
                yield Label("İŞLER (Kuyruk / Çalışan)", classes="panel-header")
                yield ListView(id="job_list_view")

            with Container(id="center_panel"):
                yield Static("[dim]Ajan döşemeleri yükleniyor...[/dim]", id="lbl_empty_tiles")

            with Vertical(id="right_panel"):
                yield Label("OLAYLAR & HATALAR", classes="panel-header")
                yield RichLog(id="events_log_view", markup=True, highlight=True)

        with Horizontal(id="cmd_bar"):
            yield CliCommandInput(
                placeholder="agentbus komutu yazın (örn: submit -t 'Yeni İş' -m '...', review j_01 --approve, diff j_01)",
                id="tui_cmd_input"
            )

    def on_mount(self) -> None:
        self.sync_db()
        if self.periodic_sync:
            self.set_interval(0.5, self.sync_db)

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
            sup_str = "[green]UP[/green]" if sup_lease else "[yellow]DOWN[/yellow]"

            # Üst durum çubuğu
            stats_text = (
                f"AGENT BUS ─ supervisor: {sup_str} │ "
                f"çalışan: [bold green]{len(running)}/4[/bold green] │ "
                f"kuyruk: [bold yellow]{len(queued)}[/bold yellow] │ "
                f"inceleme: [bold magenta]{len(review)}[/bold magenta] │ "
                f"{utc_now_iso()[11:19]}Z"
            )
            self.query_one("#lbl_top_stats", Label).update(stats_text)

            # Sol liste güncelleme (yalnızca değiştiğinde)
            list_view = self.query_one("#job_list_view", ListView)
            job_snapshot = [(j.id, j.status.value, j.title) for j in all_jobs[:25]]
            if self._last_job_snapshot != job_snapshot:
                self._last_job_snapshot = job_snapshot
                list_view.clear()
                for j in all_jobs[:25]:
                    icon = STATUS_ICONS.get(j.status, "")
                    item_text = f"{icon} {j.id} {j.title[:16]}"
                    list_view.append(ListItem(Label(item_text), id=f"item_{j.id}"))

            # Merkez döşemeler (Tile sync)
            center = self.query_one("#center_panel", Container)
            active_ids = set()

            # Çalışan, inceleme bekleyen veya insan bağlı işleri döşemelerde göster (en çok 4)
            visible_jobs = running + review + [j for j in all_jobs if j.status == JobStatus.HUMAN_ATTACHED]
            if not visible_jobs and all_jobs:
                visible_jobs = all_jobs[:4]

            for job in visible_jobs[:4]:
                active_ids.add(job.id)
                if job.id not in self.tiles:
                    try:
                        self.query_one("#lbl_empty_tiles", Static).display = False
                    except Exception:
                        pass
                    tile = AgentTileWidget(job, self)
                    self.tiles[job.id] = tile
                    center.mount(tile)
                else:
                    self.tiles[job.id].update_job(job)

            # Kapanan işlerin döşemelerini kaldır
            for j_id in list(self.tiles.keys()):
                if j_id not in active_ids:
                    self.tiles[j_id].remove()
                    del self.tiles[j_id]

            # Sağ panel: yeni olayları ekle
            new_events = events_store.list_events(since_id=self.last_event_id, limit=30)
            new_events.reverse()
            if new_events:
                ev_log = self.query_one("#events_log_view", RichLog)
                for e in new_events:
                    self.last_event_id = max(self.last_event_id, e.id)
                    j_info = f"[cyan]{e.job_id}[/cyan]" if e.job_id else "[dim]system[/dim]"
                    ts_info = f"[dim]{e.ts[11:19]}[/dim]"
                    ev_color = "red" if "error" in e.event or "failed" in e.event else "magenta"
                    payload_s = json.dumps(e.payload or {}, ensure_ascii=False)
                    if len(payload_s) > 40:
                        payload_s = payload_s[:37] + "..."
                    ev_log.write(f"{ts_info} {j_info} [{ev_color}]{e.event}[/{ev_color}] {escape(payload_s)}")

        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("btn_attach_"):
            job_id = btn_id.replace("btn_attach_", "")
            if job_id in self.tiles:
                self.tiles[job_id].attach_terminal()
        elif btn_id.startswith("btn_detach_"):
            job_id = btn_id.replace("btn_detach_", "")
            if job_id in self.tiles:
                self.tiles[job_id].detach_terminal()

    async def on_cli_command_input_submitted(self, message: CliCommandInput.Submitted) -> None:
        """Alt komut satırından girilen agentbus komutunu işler."""
        cmd_text = message.value.strip()
        if not cmd_text:
            return

        ev_log = self.query_one("#events_log_view", RichLog)
        ev_log.write(f"[bold yellow]> agentbus {escape(cmd_text)}[/bold yellow]")

        # CLI'yı subprocess veya doğrudan çağırarak çalıştır
        from agentbus.cli import build_parser
        parser = build_parser()
        tokens = ["--home", str(self.home_dir)] + cmd_text.split()
        try:
            args = parser.parse_args(tokens)
            if hasattr(args, "func"):
                # Çıktıyı yakalamak için geçici yönlendirme
                import io
                from contextlib import redirect_stdout, redirect_stderr
                buf = io.StringIO()
                with redirect_stdout(buf), redirect_stderr(buf):
                    rc = args.func(args)
                out = buf.getvalue().strip()
                if out:
                    for line in out.splitlines():
                        ev_log.write(f"  {escape(line)}")
            else:
                ev_log.write("  [red]Bilinmeyen komut[/red]")
        except SystemExit:
            pass
        except Exception as ex:
            ev_log.write(f"  [red]Komut hatası: {escape(str(ex))}[/red]")

        self.sync_db()
