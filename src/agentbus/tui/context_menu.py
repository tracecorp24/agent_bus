"""
Sağ Tık Menüsü, CLI Seçici ve Yeni Pencere Modalleri (Context Menus & Modals).
"""

from __future__ import annotations
from typing import Dict, Any, Optional
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Button
from textual.containers import Vertical, Horizontal
from textual.binding import Binding


class NewWindowModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Yeni pencere açılışında 4 seçenek sunan modal:
    1. 🧠 Codex CLI
    2. 🎭 Claude Code
    3. 🚀 Antigravity Agent ('agy --dangerously-skip-permissions')
    4. 💻 Normal CLI (cmd.exe)
    """

    DEFAULT_CSS = """
    NewWindowModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.85);
    }
    #new-win-container {
        width: 68;
        height: auto;
        border: heavy #00FF7F;
        background: #141414;
        padding: 1 2;
    }
    .new-win-title {
        text-align: center;
        text-style: bold;
        color: #FFE135;
        background: #202020;
        padding: 1;
        margin-bottom: 1;
    }
    .new-win-subtitle {
        text-align: center;
        color: #CCCCCC;
        margin-bottom: 1;
    }
    .new-win-btn {
        width: 100%;
        margin-bottom: 1;
        background: #242424;
        color: #FFFFFF;
        border: none;
        height: 3;
        content-align: left middle;
        padding-left: 2;
    }
    .new-win-btn:hover {
        background: #FFE135;
        color: #000000;
        text-style: bold;
    }
    .new-win-btn-agy:hover {
        background: #00FF7F;
        color: #000000;
        text-style: bold;
    }
    .new-win-target-bar {
        height: 3;
        width: 100%;
        margin-top: 1;
        margin-bottom: 1;
        background: #1A1A1A;
        border: round #3E3E3E;
        padding: 0 1;
        layout: horizontal;
        align: center middle;
    }
    .new-win-target-label {
        width: auto;
        color: #AAAAAA;
        text-style: bold;
        content-align: center middle;
        padding-right: 1;
    }
    .new-win-target-btn {
        width: auto;
        min-width: 18;
        height: 1;
        background: #2D2D2D;
        color: #FFFFFF;
        border: none;
        margin: 0 1;
    }
    .new-win-target-btn:hover {
        background: #FFE135;
        color: #000000;
    }
    .new-win-target-active {
        background: #00FF7F !important;
        color: #000000 !important;
        text-style: bold;
    }
    .new-win-btn-cancel {
        width: 100%;
        margin-top: 1;
        background: #2A2A2A;
        color: #FF5555;
        border: none;
        height: 3;
    }
    .new-win-btn-cancel:hover {
        background: #FF4444;
        color: #FFFFFF;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "İptal", priority=True),
        Binding("1", "select_codex", "Codex", priority=True),
        Binding("2", "select_claude", "Claude", priority=True),
        Binding("3", "select_antigravity", "Antigravity", priority=True),
        Binding("4", "select_normal", "Normal CLI", priority=True),
        Binding("t", "toggle_target", "Hedef Değiştir", priority=True),
    ]

    def __init__(self, default_target: str = "internal") -> None:
        super().__init__()
        self.target_mode = default_target

    def compose(self) -> ComposeResult:
        with Vertical(id="new-win-container"):
            yield Static("✨ YENİ PENCERE / CLI BAŞLATICI", classes="new-win-title")
            yield Static("Açılacak ortamı seçin. İlgili komut otomatik olarak çalıştırılacaktır:", classes="new-win-subtitle")

            yield Button("🧠 [1] Codex CLI                   (Komut: codex)", id="btn-opt-codex", classes="new-win-btn")
            yield Button("🎭 [2] Claude Code                 (Komut: claude)", id="btn-opt-claude", classes="new-win-btn")
            yield Button("🚀 [3] Antigravity Agent           (Komut: agy --dangerously-skip-permissions)", id="btn-opt-antigravity", classes="new-win-btn new-win-btn-agy")
            yield Button("💻 [4] Normal CLI                  (Standart cmd.exe / PowerShell)", id="btn-opt-normal", classes="new-win-btn")

            with Horizontal(classes="new-win-target-bar"):
                yield Static("Pencere Hedefi:", classes="new-win-target-label")
                internal_cls = "new-win-target-btn new-win-target-active" if self.target_mode == "internal" else "new-win-target-btn"
                external_cls = "new-win-target-btn new-win-target-active" if self.target_mode == "external" else "new-win-target-btn"
                yield Button("📐 Dahili (Bölünmüş Pencere)", id="target-internal", classes=internal_cls)
                yield Button("🪟 Harici (Ayrı Windows Penceresi)", id="target-external", classes=external_cls)

            yield Button("❌ Vazgeç (Esc)", id="btn-win-cancel", classes="new-win-btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "target-internal":
            self.target_mode = "internal"
            self.query_one("#target-internal", Button).add_class("new-win-target-active")
            self.query_one("#target-external", Button).remove_class("new-win-target-active")
            return
        elif btn_id == "target-external":
            self.target_mode = "external"
            self.query_one("#target-external", Button).add_class("new-win-target-active")
            self.query_one("#target-internal", Button).remove_class("new-win-target-active")
            return
        elif btn_id == "btn-win-cancel":
            self.dismiss(None)
            return

        opt_map = {
            "btn-opt-codex": ("codex", "codex"),
            "btn-opt-claude": ("claude", "claude"),
            "btn-opt-antigravity": ("antigravity", "agy --dangerously-skip-permissions"),
            "btn-opt-normal": ("normal", ""),
        }
        if btn_id in opt_map:
            cli_type, cmd = opt_map[btn_id]
            self._select_and_dismiss(cli_type, cmd)

    def _select_and_dismiss(self, cli_type: str, cmd: str) -> None:
        payload = {
            "action": "open",
            "cli_type": cli_type,
            "command": cmd,
            "target": self.target_mode,
        }
        self.dismiss(payload)

    def action_select_codex(self) -> None:
        self._select_and_dismiss("codex", "codex")

    def action_select_claude(self) -> None:
        self._select_and_dismiss("claude", "claude")

    def action_select_antigravity(self) -> None:
        self._select_and_dismiss("antigravity", "agy --dangerously-skip-permissions")

    def action_select_normal(self) -> None:
        self._select_and_dismiss("normal", "")

    def action_toggle_target(self) -> None:
        if self.target_mode == "internal":
            self.target_mode = "external"
        else:
            self.target_mode = "internal"
        try:
            btn_in = self.query_one("#target-internal", Button)
            btn_ex = self.query_one("#target-external", Button)
            if self.target_mode == "internal":
                btn_in.add_class("new-win-target-active")
                btn_ex.remove_class("new-win-target-active")
            else:
                btn_ex.add_class("new-win-target-active")
                btn_in.remove_class("new-win-target-active")
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)


class TileContextMenu(ModalScreen[Dict[str, Any]]):
    """Bir terminal bölmesi üzerindeki sağ tık / menü butonu modalı."""

    DEFAULT_CSS = """
    TileContextMenu {
        align: center middle;
        background: rgba(0, 0, 0, 0.75);
    }
    #menu-container {
        width: 48;
        height: auto;
        border: heavy #FFE135;
        background: #181818;
        padding: 1 2;
    }
    .ctx-header {
        text-align: center;
        text-style: bold;
        color: #FFE135;
        background: #252525;
        padding: 1;
        margin-bottom: 1;
    }
    .ctx-btn {
        width: 100%;
        margin-bottom: 1;
        background: #2A2A2A;
        color: #FFFFFF;
        border: none;
        height: 3;
    }
    .ctx-btn:hover {
        background: #FFE135;
        color: #000000;
        text-style: bold;
    }
    .ctx-btn-danger {
        color: #FF5555;
    }
    .ctx-btn-danger:hover {
        background: #FF4444;
        color: #FFFFFF;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "İptal", priority=True),
    ]

    def __init__(self, tile_id: str, current_cli: str) -> None:
        super().__init__()
        self.tile_id = tile_id
        self.current_cli = current_cli

    def compose(self) -> ComposeResult:
        with Vertical(id="menu-container"):
            yield Static(f"⚡ PENCERE İŞLEMLERİ: {self.current_cli.upper()}", classes="ctx-header")
            yield Button("✨ Yeni Pencere Aç (Codex/Claude/AGY/CLI)...", id="btn-new-window", classes="ctx-btn")
            yield Button("🪟 Harici Windows Konsolunda Aç", id="btn-open-ext-term", classes="ctx-btn")
            yield Button("⬌ Dikey Böl (Sağa Yeni Pencere)", id="btn-split-v", classes="ctx-btn")
            yield Button("⬍ Yatay Böl (Aşağı Yeni Pencere)", id="btn-split-h", classes="ctx-btn")
            yield Button("🔄 CLI Türünü Değiştir...", id="btn-switch", classes="ctx-btn")
            yield Button("✖ Bu Pencereyi Kapat", id="btn-close", classes="ctx-btn ctx-btn-danger")
            yield Button("❌ Vazgeç", id="btn-cancel", classes="ctx-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        actions = {
            "btn-new-window": {"action": "new_window", "tile_id": self.tile_id},
            "btn-open-ext-term": {"action": "open_ext_term", "tile_id": self.tile_id},
            "btn-split-v": {"action": "split_v", "tile_id": self.tile_id},
            "btn-split-h": {"action": "split_h", "tile_id": self.tile_id},
            "btn-switch": {"action": "open_cli_selector", "tile_id": self.tile_id},
            "btn-close": {"action": "close", "tile_id": self.tile_id},
            "btn-cancel": {"action": "cancel", "tile_id": self.tile_id},
        }
        self.dismiss(actions.get(btn_id, {"action": "cancel", "tile_id": self.tile_id}))

    def action_cancel(self) -> None:
        self.dismiss({"action": "cancel", "tile_id": self.tile_id})


class CliSelectorModal(ModalScreen[Optional[str]]):
    """Pencereye atanacak CLI türünü seçme modalı."""

    DEFAULT_CSS = """
    CliSelectorModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.8);
    }
    #selector-container {
        width: 58;
        height: auto;
        border: heavy #00FF7F;
        background: #141414;
        padding: 1 2;
    }
    .sel-header {
        text-align: center;
        text-style: bold;
        color: #00FF7F;
        background: #1F1F1F;
        padding: 1;
        margin-bottom: 1;
    }
    .sel-btn {
        width: 100%;
        margin-bottom: 1;
        background: #222222;
        color: #FFFFFF;
        border: none;
        height: 3;
    }
    .sel-btn:hover {
        background: #00FF7F;
        color: #000000;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "İptal", priority=True),
    ]

    CLI_CHOICES = [
        ("codex", "🧠 Codex Agent CLI (Gömülü Terminal)"),
        ("claude", "🎭 Claude Code CLI (Gömülü Terminal)"),
        ("antigravity", "🚀 Antigravity Agent (agy --dangerously-skip-permissions)"),
        ("shell", "💻 Standart Shell CLI (cmd.exe)"),
    ]

    def __init__(self, tile_id: str, current_cli: str) -> None:
        super().__init__()
        self.tile_id = tile_id
        self.current_cli = current_cli

    def compose(self) -> ComposeResult:
        with Vertical(id="selector-container"):
            yield Static("🔄 BU PENCERE İÇİN YENİ CLI SEÇİN", classes="sel-header")
            for cli_id, label in self.CLI_CHOICES:
                suffix = " [MEVCUT]" if cli_id == self.current_cli else ""
                yield Button(f"{label}{suffix}", id=f"cli-opt-{cli_id}", classes="sel-btn")
            yield Button("❌ İptal", id="cli-opt-cancel", classes="sel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "cli-opt-cancel":
            self.dismiss(None)
            return

        cli_key = btn_id.replace("cli-opt-", "")
        self.dismiss(cli_key)
