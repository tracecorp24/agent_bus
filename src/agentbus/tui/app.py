"""
AGENT BUS - Textual Tabanlı Gömülü Çoklu Ajan Arayüzü (TUI Dashboard).

Kullanıcı Deneyimi:
- Sol Taraf: Kompakt kontrol paneli (Sidebar): '➕ Yeni Pencere' butonu,
  hızlı düzen şablonları (3 Sütun, Sığdır, Ana+Yan, Izgara, Dikey, Yatay)
  ve aktif işlerin/ajanların listesi.
- Sağ Taraf: Dinamik Çalışma Tuvali (DynamicWorkspace):
  Kullanıcının '+' tuşu ile açtığı gerçek ConPTY terminalleri (Codex, Claude, AGY, Normal CLI).
  Pencereler fareyle sürüklenebilir ayraçlarla (DragSplitter) sağa/sola/yukarı/aşağı esnetilebilir,
  2 satır, 3 satır veya 3-5 sütunlu düzenler oluşturulabilir.
"""

from __future__ import annotations
import os
import sys
import json
import time
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Any

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, Container
from textual.widgets import Static, Button, RichLog, Label, ListItem, ListView
from textual import events
from textual.binding import Binding
from rich.text import Text
from rich.markup import escape

from agentbus.db import get_connection, init_db, transition
from agentbus.models import JobStatus, Job, utc_now_iso
from agentbus.store.jobs import JobsStore
from agentbus.store.turns import TurnsStore
from agentbus.store.events import EventsStore
from agentbus.tui.workspace import DynamicWorkspace
from agentbus.tui.context_menu import NewWindowModal


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


class JobCardWidget(Vertical):
    """Sol panelde her bir ajanın/işin durumunu ve bağlan/devret aksiyonlarını gösteren kart."""

    DEFAULT_CSS = """
    JobCardWidget {
        background: #1C1C1C;
        border: solid #333333;
        margin: 0 0 1 0;
        padding: 0 1;
        height: auto;
    }
    JobCardWidget:hover {
        border: solid #FFE135;
    }
    .job-card-hdr {
        height: 1;
        layout: horizontal;
    }
    .job-card-title {
        width: 1fr;
        color: #FFFFFF;
        text-style: bold;
    }
    .job-card-btns {
        height: 1;
        margin-top: 1;
        layout: horizontal;
    }
    .btn-job-action {
        height: 1;
        min-width: 8;
        margin-right: 1;
        border: none;
        padding: 0 1;
        background: #2E2E2E;
        color: #CCCCCC;
    }
    .btn-job-action:hover {
        background: #FFE135;
        color: #000000;
        text-style: bold;
    }
    .btn-job-attach:hover {
        background: #00FF7F;
        color: #000000;
    }
    .btn-job-detach:hover {
        background: #FF9900;
        color: #000000;
    }
    """

    def __init__(self, job: Job, app_ref: AgentBusTuiApp) -> None:
        super().__init__(id=f"tile_{job.id}")
        self.job = job
        self.app_ref = app_ref

    def compose(self) -> ComposeResult:
        icon = STATUS_ICONS.get(self.job.status, "○")
        with Horizontal(classes="job-card-hdr"):
            yield Label(f"{icon} {self.job.id} │ {self.job.status.value}", classes="job-card-title", id=f"title_{self.job.id}")

        with Horizontal(classes="job-card-btns"):
            yield Button("Bağlan", id=f"btn_attach_{self.job.id}", classes="btn-job-action btn-job-attach")
            yield Button("Devret", id=f"btn_detach_{self.job.id}", classes="btn-job-action btn-job-detach")

    def update_job(self, job: Job) -> None:
        self.job = job
        try:
            lbl = self.query_one(f"#title_{self.job.id}", Label)
            icon = STATUS_ICONS.get(self.job.status, "○")
            lbl.update(f"{icon} {self.job.id} │ {self.job.status.value}")
        except Exception:
            pass


class AgentBusTuiApp(App):
    """Ana AGENT BUS Dashboard Arayüzü (Sol Sidebar + Sağ Dinamik Çalışma Tuvali)."""

    BINDINGS = [
        Binding("+", "new_window", "Yeni Pencere", priority=True),
        Binding("=", "new_window", "Yeni Pencere", show=False),
        Binding("ctrl+n", "new_window", "Yeni Pencere"),
        Binding("f6", "new_window", "Yeni Pencere"),
        Binding("f1", "layout_three_cols", "3 Sütun"),
        Binding("f2", "layout_fit_all", "Sığdır"),
        Binding("f3", "layout_main_stack", "Ana + Yan"),
        Binding("f4", "layout_grid_2x2", "2x2 Izgara"),
        Binding("r", "refresh_data", "Yenile"),
        Binding("q", "quit", "Çıkış"),
    ]

    CSS = """
    Screen {
        background: #121212;
        color: #E0E0E0;
        layout: horizontal;
        padding: 0;
        margin: 0;
    }
    #sidebar {
        width: 32;
        height: 100%;
        background: #161616;
        border-right: heavy #FFE135;
        layout: vertical;
        padding: 0 1;
    }
    .sidebar-header {
        height: 2;
        content-align: center middle;
        text-align: center;
        background: #202020;
        color: #00FF7F;
        text-style: bold;
        margin: 1 0;
        border: solid #333333;
    }
    .btn-new-window-main {
        width: 100%;
        height: 3;
        background: #008040;
        color: #FFFFFF;
        text-style: bold;
        border: heavy #00FF7F;
        margin-bottom: 1;
    }
    .btn-new-window-main:hover {
        background: #00FF7F;
        color: #000000;
        text-style: bold;
    }
    .sidebar-section-title {
        color: #FFE135;
        text-style: bold;
        margin: 1 0 0 0;
        padding-left: 1;
    }
    .sidebar-presets-box {
        height: auto;
        layout: vertical;
        margin-bottom: 1;
    }
    .btn-preset-side {
        width: 100%;
        height: 1;
        margin: 0 0 1 0;
        background: #242424;
        color: #CCCCCC;
        border: none;
        text-align: left;
        padding-left: 1;
    }
    .btn-preset-side:hover {
        background: #FFE135;
        color: #000000;
        text-style: bold;
    }
    #jobs_scroll_container {
        height: 1fr;
        background: #141414;
        border: solid #2A2A2A;
        padding: 1;
        overflow-y: auto;
    }
    .lbl-empty-jobs {
        color: #666666;
        text-align: center;
        margin-top: 2;
    }
    .sidebar-footer {
        height: 3;
        background: #1A1A1A;
        border-top: solid #333333;
        color: #888888;
        content-align: center middle;
        text-align: center;
        margin-top: 1;
    }
    #workspace-container {
        width: 1fr;
        height: 100%;
        layout: vertical;
        padding: 0;
        margin: 0;
    }
    """

    def __init__(
        self,
        home_dir: Path,
        periodic_sync: bool = True,
        auto_start_supervisor: Optional[bool] = None,
    ):
        super().__init__()
        self.home_dir = Path(home_dir)
        self.periodic_sync = periodic_sync
        self.db_conn = None
        self._sync_task: Optional[asyncio.Task] = None
        self.workspace: Optional[DynamicWorkspace] = None
        self._known_job_ids: set[str] = set()

    def get_db(self):
        if self.db_conn is None:
            db_path = self.home_dir / "bus.db"
            self.db_conn = get_connection(db_path)
            init_db(self.db_conn)
        return self.db_conn

    def compose(self) -> ComposeResult:
        # 1. SOL PANEL (Sidebar)
        with Vertical(id="sidebar"):
            yield Static("🤖 AGENT BUS MULTI-CLI", classes="sidebar-header")
            yield Button("➕ YENİ PENCERE (+)", id="btn-side-new-window", classes="btn-new-window-main")

            yield Static("📐 DÜZEN ŞABLONLARI:", classes="sidebar-section-title")
            with Vertical(classes="sidebar-presets-box"):
                yield Button("⫴ 3 Sütun (Görsel Düzeni)", id="btn-side-three-cols", classes="btn-preset-side")
                yield Button("🗖 Tümünü Sığdır", id="btn-side-fit-all", classes="btn-preset-side")
                yield Button("◰ Ana + Yan Yığın", id="btn-side-main-stack", classes="btn-preset-side")
                yield Button("⊞ 2x2 Izgara", id="btn-side-grid-2x2", classes="btn-preset-side")
                yield Button("⬌ Dikey Böl (Split V)", id="btn-side-split-v", classes="btn-preset-side")
                yield Button("⬍ Yatay Böl (Split H)", id="btn-side-split-h", classes="btn-preset-side")

            yield Static("📋 AKTİF AJANLAR (DB):", classes="sidebar-section-title")
            with Vertical(id="jobs_scroll_container"):
                yield Static("Kayıtlı aktif ajan yok", id="lbl-empty-jobs", classes="lbl-empty-jobs")

            yield Static("[+] Yeni Pencere  [F1] 3 Sütun  [r] Yenile  [q] Çıkış", classes="sidebar-footer")

        # 2. SAĞ PANEL (Dinamik Çoklu Terminal Çalışma Tuvali)
        self.workspace = DynamicWorkspace(initial_preset="three_cols")
        with Container(id="workspace-container"):
            yield self.workspace

    async def on_mount(self) -> None:
        self.sync_db()
        if self.periodic_sync:
            self._sync_task = asyncio.create_task(self._sync_loop())

    async def _sync_loop(self) -> None:
        while True:
            await asyncio.sleep(2.0)
            self.sync_db()

    def sync_db(self) -> None:
        """Veritabanındaki işleri kontrol eder ve sol paneli günceller."""
        try:
            conn = self.get_db()
            jobs_store = JobsStore(conn)
            all_jobs = jobs_store.list_jobs()
        except Exception:
            return

        container = self.query_one("#jobs_scroll_container", Vertical)
        empty_lbl = self.query_one("#lbl-empty-jobs", Static)

        if not all_jobs:
            empty_lbl.display = True
            return

        empty_lbl.display = False
        current_ids = {j.id for j in all_jobs}

        for j in all_jobs:
            card = container.query(f"#tile_{j.id}")
            if card:
                card.first().update_job(j)
            else:
                new_card = JobCardWidget(j, self)
                container.mount(new_card)

        # Silinmiş iş kartlarını kaldır
        for cid in list(self._known_job_ids):
            if cid not in current_ids:
                card = container.query(f"#tile_{cid}")
                if card:
                    card.first().remove()

        self._known_job_ids = current_ids

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        # Sol Sidebar İşlemleri
        if btn_id == "btn-side-new-window":
            self.action_new_window()
            return
        elif btn_id == "btn-side-three-cols":
            self.action_layout_three_cols()
            return
        elif btn_id == "btn-side-fit-all":
            self.action_layout_fit_all()
            return
        elif btn_id == "btn-side-main-stack":
            self.action_layout_main_stack()
            return
        elif btn_id == "btn-side-grid-2x2":
            self.action_layout_grid_2x2()
            return
        elif btn_id == "btn-side-split-v":
            if self.workspace:
                self.run_worker(self.workspace.apply_preset("split_v"))
            return
        elif btn_id == "btn-side-split-h":
            if self.workspace:
                self.run_worker(self.workspace.apply_preset("split_h"))
            return

        # İş kartı aksiyonları
        if btn_id.startswith("btn_attach_"):
            job_id = btn_id.replace("btn_attach_", "")
            self._handle_attach_job(job_id)
        elif btn_id.startswith("btn_detach_"):
            job_id = btn_id.replace("btn_detach_", "")
            self._handle_detach_job(job_id)

    def _handle_attach_job(self, job_id: str) -> None:
        conn = self.get_db()
        jobs_store = JobsStore(conn)
        job = jobs_store.get_job(job_id)
        if not job:
            return

        if job.status == JobStatus.RUNNING:
            transition(conn, job.id, JobStatus.RUNNING, JobStatus.ATTACH_PENDING, reason="TUI bağlanma isteği")
            self.notify(f"Tur tamamlanınca bağlanılacak: {job.id}", title="BAĞLANMA BEKLENİYOR")
            return

        if job.status != JobStatus.HUMAN_ATTACHED:
            transition(conn, job.id, job.status, JobStatus.HUMAN_ATTACHED, reason="TUI üzerinden bağlandı")

        # Sağ çalışma alanına bu işe ait terminal aç
        conv_args = f"--conversation {job.conversation_id}" if job.conversation_id else ""
        cmd = f"agy {conv_args}".strip()
        if self.workspace:
            self.run_worker(self.workspace.add_new_tile(cli_type="antigravity", initial_command=cmd))
        self.notify(f"Ajan terminali açıldı: {job.id}", title="BAĞLANDI")
        self.sync_db()

    def _handle_detach_job(self, job_id: str) -> None:
        conn = self.get_db()
        jobs_store = JobsStore(conn)
        job = jobs_store.get_job(job_id)
        if not job:
            return

        if job.status in (JobStatus.HUMAN_ATTACHED, JobStatus.ATTACH_PENDING):
            transition(conn, job.id, job.status, JobStatus.QUEUED, reason="TUI'den devredildi")
            self.notify(f"İş supervisor kuyruğuna devredildi: {job.id}", title="DEVREDİLDİ (DETACH)")
        self.sync_db()

    # Kısayol Aksiyonları
    def action_new_window(self) -> None:
        if self.workspace:
            self.workspace.prompt_new_window()

    def action_layout_three_cols(self) -> None:
        if self.workspace:
            self.run_worker(self.workspace.apply_preset("three_cols"))

    def action_layout_fit_all(self) -> None:
        if self.workspace:
            self.run_worker(self.workspace.apply_preset("fit_all"))

    def action_layout_main_stack(self) -> None:
        if self.workspace:
            self.run_worker(self.workspace.apply_preset("main_stack"))

    def action_layout_grid_2x2(self) -> None:
        if self.workspace:
            self.run_worker(self.workspace.apply_preset("grid_2x2"))

    def action_refresh_data(self) -> None:
        self.sync_db()
        self.notify("Veriler yenilendi", title="AGENT BUS", severity="information")


if __name__ == "__main__":
    from agentbus.config import get_home_dir
    home = get_home_dir()
    app = AgentBusTuiApp(home)
    app.run()
