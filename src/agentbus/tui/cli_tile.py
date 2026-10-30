"""
AGENT BUS - Bağımsız Çoklu Terminal Bölmesi (CliTilePane).
Gerçek ConPTY (winpty + pyte) terminal sürecini barındırır.
Dikey/yatay bölünebilir, sürüklenebilir ayraçlarla yeniden boyutlandırılabilir,
harici Windows CMD penceresine aktarılabilir veya kapatılabilir.
"""

from __future__ import annotations
import os
import subprocess
from typing import Optional, Callable, Dict, Any

from textual.app import ComposeResult
from textual.widgets import Static, Button
from textual.containers import Vertical, Horizontal
from textual import events

from agentbus.tui.panes.embedded_terminal import EmbeddedTerminalWidget
from agentbus.tui.context_menu import TileContextMenu, CliSelectorModal


class CliTilePane(Vertical):
    """Her biri bağımsız bir CLI sürecini (Codex, Claude, Antigravity veya CMD) çalıştıran döşeme."""

    DEFAULT_CSS = """
    CliTilePane {
        border: heavy #FFE135;
        background: #121212;
        height: 1fr;
        width: 1fr;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }
    CliTilePane:focus-within {
        border: heavy #00FF7F;
    }
    .tile-header-bar {
        height: 1;
        background: #1E1E1E;
        padding: 0 1;
        layout: horizontal;
    }
    .tile-title-text {
        width: 1fr;
        height: 1;
        color: #FFE135;
        text-style: bold;
        overflow-x: hidden;
        text-overflow: ellipsis;
    }
    .tile-actions-strip {
        width: auto;
        layout: horizontal;
    }
    .tile-hdr-btn {
        width: 4;
        min-width: 4;
        height: 1;
        padding: 0;
        margin: 0 0 0 1;
        background: #2D2D2D;
        color: #FFFFFF;
        border: none;
    }
    .tile-hdr-btn:hover {
        background: #FFE135;
        color: #000000;
        text-style: bold;
    }
    .tile-hdr-btn-danger:hover {
        background: #FF4444;
        color: #FFFFFF;
        text-style: bold;
    }
    .tile-terminal-container {
        height: 1fr;
        width: 100%;
        padding: 0;
        margin: 0;
        overflow: hidden;
        background: #0C0C0C;
    }
    """

    def __init__(
        self,
        tile_id: str,
        cli_type: str = "normal",
        initial_command: Optional[str] = None,
        cwd: Optional[str] = None,
        on_action: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ) -> None:
        super().__init__(id=tile_id)
        self.tile_id = tile_id
        self.cli_type = cli_type
        self.initial_command = initial_command
        self.cwd = cwd or os.getcwd()
        self.on_action = on_action
        self.terminal: Optional[EmbeddedTerminalWidget] = None

    def _resolve_command(self) -> str:
        if self.initial_command is not None:
            return self.initial_command
        if self.cli_type == "codex":
            return "codex"
        elif self.cli_type == "claude":
            return "claude"
        elif self.cli_type in ("antigravity", "agy"):
            return "agy --dangerously-skip-permissions"
        return ""

    def _format_title(self) -> str:
        icons = {
            "codex": "🧠 CODEX AGENT CLI",
            "claude": "🎭 CLAUDE CODE CLI",
            "antigravity": "🚀 ANTIGRAVITY AGENT CLI",
            "agy": "🚀 ANTIGRAVITY AGENT CLI",
            "normal": "💻 NORMAL CLI (cmd.exe)",
            "shell": "💻 NORMAL CLI (cmd.exe)",
        }
        return icons.get(self.cli_type, f"⚡ {self.cli_type.upper()}")

    def compose(self) -> ComposeResult:
        with Horizontal(classes="tile-header-bar"):
            yield Static(self._format_title(), id=f"title-{self.tile_id}", classes="tile-title-text")
            with Horizontal(classes="tile-actions-strip"):
                yield Button("⬌", id=f"btn-vsplit-{self.tile_id}", classes="tile-hdr-btn", tooltip="Dikey Böl (Sağa Ekle)")
                yield Button("⬍", id=f"btn-hsplit-{self.tile_id}", classes="tile-hdr-btn", tooltip="Yatay Böl (Aşağı Ekle)")
                yield Button("🔄", id=f"btn-switch-{self.tile_id}", classes="tile-hdr-btn", tooltip="CLI Türünü Değiştir")
                yield Button("🪟", id=f"btn-ext-{self.tile_id}", classes="tile-hdr-btn", tooltip="Ayrı Windows Konsolunda Aç")
                yield Button("✖", id=f"btn-close-{self.tile_id}", classes="tile-hdr-btn tile-hdr-btn-danger", tooltip="Pencereyi Kapat")

        resolved_cmd = self._resolve_command()
        self.terminal = EmbeddedTerminalWidget(
            shell_cmd="cmd.exe",
            initial_command=resolved_cmd,
            cwd=self.cwd,
            id=f"term-{self.tile_id}",
            classes="tile-terminal-container",
        )
        yield self.terminal

    def on_mount(self) -> None:
        self.call_after_refresh(self.focus_terminal)

    def focus_terminal(self) -> None:
        if self.terminal:
            self.terminal.focus()

    def on_click(self, event: events.Click) -> None:
        if event.button == 3:  # Sağ tık -> Bağlam Menüsü
            event.stop()
            self._open_context_menu()
        elif event.button == 1:
            self.focus_terminal()

    def _open_context_menu(self) -> None:
        def _handle_result(result: Optional[Dict[str, Any]]) -> None:
            if not result or result.get("action") == "cancel":
                return
            action = result.get("action")
            if action == "new_window":
                if self.on_action:
                    self.on_action("new_window", self.tile_id, {})
            elif action == "open_ext_term":
                self.action_open_external_terminal()
            elif action == "open_cli_selector":
                self._open_cli_selector()
            elif action in ("split_v", "split_h", "close"):
                if self.on_action:
                    self.on_action(action, self.tile_id, {})

        self.app.push_screen(TileContextMenu(self.tile_id, self.cli_type), _handle_result)

    def _open_cli_selector(self) -> None:
        def _on_select(selected: Optional[str]) -> None:
            if selected and selected != self.cli_type:
                self.switch_cli(selected)

        self.app.push_screen(CliSelectorModal(self.tile_id, self.cli_type), _on_select)

    def switch_cli(self, new_cli: str) -> None:
        self.cli_type = new_cli
        self.initial_command = None
        cmd = self._resolve_command()
        try:
            lbl = self.query_one(f"#title-{self.tile_id}", Static)
            lbl.update(self._format_title())
        except Exception:
            pass

        if self.terminal:
            self.terminal.initial_command = cmd
            self.terminal.restart_terminal()
            self.call_after_refresh(self.focus_terminal)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == f"btn-vsplit-{self.tile_id}":
            if self.on_action:
                self.on_action("split_v", self.tile_id, {})
        elif btn_id == f"btn-hsplit-{self.tile_id}":
            if self.on_action:
                self.on_action("split_h", self.tile_id, {})
        elif btn_id == f"btn-switch-{self.tile_id}":
            self._open_cli_selector()
        elif btn_id == f"btn-ext-{self.tile_id}":
            self.action_open_external_terminal()
        elif btn_id == f"btn-close-{self.tile_id}":
            if self.on_action:
                self.on_action("close", self.tile_id, {})

    def action_open_external_terminal(self) -> None:
        """Pencereyi ayrı bir Windows CMD konsoluna taşır."""
        cmd = self._resolve_command()
        title = f"AGENT BUS: {self._format_title()}"
        try:
            if os.name == "nt":
                if cmd:
                    subprocess.Popen(f'start "{title}" cmd /k "{cmd}"', shell=True)
                else:
                    subprocess.Popen(f'start "{title}" cmd.exe', shell=True)
            else:
                if cmd:
                    subprocess.Popen(f'x-terminal-emulator -e "{cmd}" || xterm -e "{cmd}"', shell=True)
                else:
                    subprocess.Popen("x-terminal-emulator || xterm", shell=True)
            self.app.notify(f"Harici konsol açıldı: {self.cli_type}", title="HARİCİ PENCERE")
        except Exception as e:
            self.app.notify(f"Harici konsol açılamadı: {e}", severity="error")

    def terminate_terminal(self) -> None:
        if self.terminal:
            self.terminal.terminate_process()
