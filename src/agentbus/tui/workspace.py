"""
AGENT BUS - Dinamik Çoklu Terminal Çalışma Alanı (DynamicWorkspace).
Yatay/dikey bölme, fareyle sürüklenebilir ayraçlar (DragSplitter),
çoklu sütun/satır düzen şablonları (3 Sütun, Sığdır, Ana+Yan, Izgara),
ve yeni CLI pencere sihirbazı (Codex, Claude, Antigravity, Normal CLI) sunar.
"""

from __future__ import annotations
import os
import math
import subprocess
from typing import Optional, Dict, Any, List

from textual.app import ComposeResult
from textual import events
from textual.widgets import Static, Button
from textual.containers import Vertical, Horizontal

from agentbus.tui.cli_tile import CliTilePane
from agentbus.tui.drag_splitter import DragSplitter
from agentbus.tui.context_menu import NewWindowModal


class DynamicWorkspace(Vertical):
    """Etkileşimli CLI panelleri ve ayraçları barındıran çalışma tuvali."""

    DEFAULT_CSS = """
    DynamicWorkspace {
        width: 1fr;
        height: 100%;
        layout: vertical;
        padding: 0;
        margin: 0;
    }
    #preset-toolbar {
        height: 3;
        background: #181818;
        border-bottom: heavy #FFE135;
        padding: 0 1;
        layout: horizontal;
        align: left middle;
    }
    .preset-label {
        width: auto;
        color: #FFE135;
        text-style: bold;
        content-align: center middle;
        padding-right: 1;
    }
    .preset-btn {
        width: auto;
        min-width: 10;
        height: 1;
        margin: 0 1 0 0;
        background: #252525;
        color: #E0E0E0;
        border: none;
        padding: 0 1;
    }
    .preset-btn:hover {
        background: #FFE135;
        color: #000000;
        text-style: bold;
    }
    .preset-btn-active {
        background: #00FF7F !important;
        color: #000000 !important;
        text-style: bold;
    }
    #preset-add-tile {
        background: #2A4020;
        color: #00FF7F;
        text-style: bold;
    }
    #preset-add-tile:hover {
        background: #00FF7F;
        color: #000000;
    }
    #workspace-canvas {
        width: 100%;
        height: 1fr;
        padding: 0;
        margin: 0;
        overflow: hidden;
    }
    .split-col {
        layout: horizontal;
        height: 1fr;
        width: 100%;
        overflow: hidden;
    }
    .split-row {
        layout: vertical;
        height: 1fr;
        width: 100%;
        overflow: hidden;
    }
    Horizontal > .split-row {
        width: 1fr !important;
        height: 100% !important;
    }
    Vertical > .split-col {
        height: 1fr !important;
        width: 100% !important;
    }
    Horizontal > CliTilePane {
        width: 1fr !important;
        height: 100% !important;
    }
    Vertical > CliTilePane {
        height: 1fr !important;
        width: 100% !important;
    }
    """

    def __init__(
        self,
        initial_preset: str = "three_cols",
        initial_tiles: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        super().__init__(id="right-workspace")
        self.current_preset = initial_preset
        self._tile_counter: int = 1
        self._active_tiles: Dict[str, CliTilePane] = {}
        self._initial_tiles_config = initial_tiles or [
            {"cli_type": "codex", "command": "codex"},
            {"cli_type": "claude", "command": "claude"},
            {"cli_type": "antigravity", "command": "agy --dangerously-skip-permissions"},
        ]
        self.last_focused_tile_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="preset-toolbar"):
            yield Static("📐 DÜZEN:", classes="preset-label")
            yield Button("⫴ 3 Sütun", id="preset-three-cols", classes="preset-btn", tooltip="Pencereleri 3 dikey sütuna dağıt (Görsel Düzeni)")
            yield Button("🗖 Sığdır", id="preset-fit-all", classes="preset-btn", tooltip="Tüm pencereleri ekrana dengeli sığdır")
            yield Button("◰ Ana + Yan", id="preset-main-stack", classes="preset-btn", tooltip="Sol ana pencere + Sağ dikey yığın")
            yield Button("⊞ 2x2 Izgara", id="preset-grid-2x2", classes="preset-btn", tooltip="2 satır x 2 sütun ızgara")
            yield Button("⬌ Dikey Böl", id="preset-split-v", classes="preset-btn", tooltip="İki eşit dikey sütun")
            yield Button("⬍ Yatay Böl", id="preset-split-h", classes="preset-btn", tooltip="İki eşit yatay satır")
            yield Button("➕ Yeni Pencere (+)", id="preset-add-tile", classes="preset-btn", tooltip="Yeni CLI Penceresi Başlat (Codex, Claude, AGY, Normal)")

        yield Vertical(id="workspace-canvas")

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        for tid, tile in self._active_tiles.items():
            if tile.has_focus or any(c.has_focus for c in tile.walk_children()):
                self.last_focused_tile_id = tid
                break

    async def on_mount(self) -> None:
        # Initial tiles setup
        specs = self._initial_tiles_config
        await self.apply_preset(self.current_preset, target_specs=specs)

    def _next_tile_id(self) -> str:
        tid = f"tile_{self._tile_counter}"
        self._tile_counter += 1
        return tid

    def _create_tile(
        self,
        cli_type: str,
        initial_command: Optional[str] = None,
        tile_id: Optional[str] = None,
    ) -> CliTilePane:
        tid = tile_id or self._next_tile_id()
        tile = CliTilePane(
            tile_id=tid,
            cli_type=cli_type,
            initial_command=initial_command,
            on_action=self.handle_tile_action,
        )
        self._active_tiles[tid] = tile
        return tile

    async def apply_preset(
        self,
        preset_name: str,
        target_specs: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        """Pencereleri seçilen şablona göre anında yeniden yerleştirir."""
        self.current_preset = preset_name
        canvas = self.query_one("#workspace-canvas", Vertical)

        # Mevcut pencerelerin durumlarını kaydet
        existing_specs: List[Dict[str, str]] = []
        if target_specs:
            existing_specs = target_specs
        elif self._active_tiles:
            for t in self._active_tiles.values():
                existing_specs.append({
                    "cli_type": t.cli_type,
                    "command": t.initial_command or "",
                })
        else:
            existing_specs = [
                {"cli_type": "codex", "command": "codex"},
                {"cli_type": "claude", "command": "claude"},
                {"cli_type": "antigravity", "command": "agy --dangerously-skip-permissions"},
            ]

        # Eski widget'ları temizle
        for child in list(canvas.children):
            await child.remove()
        for t in self._active_tiles.values():
            t.terminate_terminal()
        self._active_tiles.clear()

        # Toolbar buton vurgusunu güncelle
        for btn in self.query(".preset-btn"):
            btn.remove_class("preset-btn-active")
        try:
            active_btn = self.query_one(f"#preset-{preset_name.replace('_', '-')}", Button)
            active_btn.add_class("preset-btn-active")
        except Exception:
            pass

        tiles = [self._create_tile(s.get("cli_type", "normal"), s.get("command", None)) for s in existing_specs]
        n = len(tiles)

        if n == 0:
            tiles = [self._create_tile("normal", "")]
            n = 1

        if preset_name == "single" or n == 1:
            col = Horizontal(tiles[0], classes="split-col")
            await canvas.mount(col)

        elif preset_name == "split_v":
            if n == 1:
                t2 = self._create_tile("normal", "")
                tiles.append(t2)
            s = DragSplitter(direction="horizontal")
            container = Horizontal(tiles[0], s, tiles[1], classes="split-col")
            await canvas.mount(container)

        elif preset_name == "split_h":
            if n == 1:
                t2 = self._create_tile("normal", "")
                tiles.append(t2)
            s = DragSplitter(direction="vertical")
            container = Vertical(tiles[0], s, tiles[1], classes="split-row")
            await canvas.mount(container)

        elif preset_name == "grid_2x2":
            while len(tiles) < 4:
                types = ["codex", "claude", "antigravity", "normal"]
                next_t = types[len(tiles) % len(types)]
                tiles.append(self._create_tile(next_t))

            h_s1 = DragSplitter(direction="horizontal")
            h_s2 = DragSplitter(direction="horizontal")
            v_s = DragSplitter(direction="vertical")

            top_row = Horizontal(tiles[0], h_s1, tiles[1], classes="split-col")
            bot_row = Horizontal(tiles[2], h_s2, tiles[3], classes="split-col")
            container = Vertical(top_row, v_s, bot_row, classes="split-row")
            await canvas.mount(container)

        elif preset_name == "main_stack":
            main_tile = tiles[0]
            h_split = DragSplitter(direction="horizontal")
            stack_tiles = tiles[1:] if len(tiles) > 1 else [self._create_tile("normal", "")]

            v_children = []
            for i, t in enumerate(stack_tiles):
                if i > 0:
                    v_children.append(DragSplitter(direction="vertical"))
                v_children.append(t)

            right_stack = Vertical(*v_children, classes="split-row")
            container = Horizontal(main_tile, h_split, right_stack, classes="split-col")
            await canvas.mount(container)

        elif preset_name == "three_cols":
            await self._build_three_cols_layout(canvas, tiles)

        else:  # fit_all fallback
            await self._build_grid_layout(canvas, tiles)

        if self._active_tiles:
            first_t = next(iter(self._active_tiles.values()))
            first_t.call_after_refresh(first_t.focus_terminal)

        self.app.notify(f"Düzen: {preset_name.replace('_', ' ').upper()}", title="AGENT BUS", severity="information")

    async def _build_three_cols_layout(self, canvas: Vertical, tiles: List[CliTilePane]) -> None:
        """Pencereleri 3 dikey sütuna dağıtır (kullanıcı ekran görüntüsü gibi)."""
        n = len(tiles)
        if n == 1:
            col = Horizontal(tiles[0], classes="split-col")
            await canvas.mount(col)
            return

        if n == 2:
            s = DragSplitter(direction="horizontal")
            col = Horizontal(tiles[0], s, tiles[1], classes="split-col")
            await canvas.mount(col)
            return

        if n == 3:
            s1 = DragSplitter(direction="horizontal")
            s2 = DragSplitter(direction="horizontal")
            col = Horizontal(tiles[0], s1, tiles[1], s2, tiles[2], classes="split-col")
            await canvas.mount(col)
            return

        # n > 3: 3 dikey sütuna böl, arta kalanları dikeyde yığ
        num_cols = 3
        base = n // num_cols
        rem = n % num_cols

        cols_tiles: List[List[CliTilePane]] = []
        idx = 0
        for c in range(num_cols):
            count = base + (1 if c < rem else 0)
            cols_tiles.append(tiles[idx : idx + count])
            idx += count

        col_widgets = []
        for c_tiles in cols_tiles:
            if len(c_tiles) == 1:
                col_widgets.append(c_tiles[0])
            else:
                v_children = []
                for t_idx, t in enumerate(c_tiles):
                    if t_idx > 0:
                        v_children.append(DragSplitter(direction="vertical"))
                    v_children.append(t)
                v_box = Vertical(*v_children, classes="split-row")
                col_widgets.append(v_box)

        h_children = []
        for i, col_w in enumerate(col_widgets):
            if i > 0:
                h_children.append(DragSplitter(direction="horizontal"))
            h_children.append(col_w)

        container = Horizontal(*h_children, classes="split-col")
        await canvas.mount(container)

    async def _build_grid_layout(self, canvas: Vertical, tiles: List[CliTilePane]) -> None:
        """Tüm pencereleri optimal satır ve sütun ızgarasına eşit dağıtır."""
        n = len(tiles)
        if n == 1:
            col = Horizontal(tiles[0], classes="split-col")
            await canvas.mount(col)
            return

        if n in (2, 3):
            h_children = []
            for i, t in enumerate(tiles):
                if i > 0:
                    h_children.append(DragSplitter(direction="horizontal"))
                h_children.append(t)
            container = Horizontal(*h_children, classes="split-col")
            await canvas.mount(container)
            return

        num_rows = max(2, round(math.sqrt(n)))
        base = n // num_rows
        rem = n % num_rows
        rows: List[List[CliTilePane]] = []
        idx = 0
        for r in range(num_rows):
            count = base + (1 if r < rem else 0)
            rows.append(tiles[idx : idx + count])
            idx += count

        row_widgets = []
        for r_idx, row_tiles in enumerate(rows):
            if r_idx > 0:
                row_widgets.append(DragSplitter(direction="vertical"))

            if len(row_tiles) == 1:
                row_widgets.append(row_tiles[0])
            else:
                h_children = []
                for c_idx, t in enumerate(row_tiles):
                    if c_idx > 0:
                        h_children.append(DragSplitter(direction="horizontal"))
                    h_children.append(t)
                row_widgets.append(Horizontal(*h_children, classes="split-col"))

        container = Vertical(*row_widgets, classes="split-row")
        await canvas.mount(container)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        presets = {
            "preset-three-cols": "three_cols",
            "preset-fit-all": "fit_all",
            "preset-main-stack": "main_stack",
            "preset-grid-2x2": "grid_2x2",
            "preset-split-v": "split_v",
            "preset-split-h": "split_h",
        }
        if btn_id in presets:
            self.run_worker(self.apply_preset(presets[btn_id]))
        elif btn_id == "preset-add-tile":
            self.prompt_new_window()

    def prompt_new_window(self, default_target: str = "internal") -> None:
        """4 seçenekli modal penceresini (Codex, Claude, AGY, Normal) açar."""
        def _on_selection(result: Optional[Dict[str, Any]]) -> None:
            if not result or result.get("action") != "open":
                return
            cli_type = result.get("cli_type", "normal")
            cmd = result.get("command", "")
            target = result.get("target", "internal")

            if target == "external":
                self.open_external_window(cli_type, cmd)
            else:
                self.run_worker(self.add_new_tile(cli_type=cli_type, initial_command=cmd))

        self.app.push_screen(NewWindowModal(default_target=default_target), _on_selection)

    def open_external_window(self, cli_type: str, cmd: str = "") -> None:
        """Harici bağımsız bir Windows CMD konsolunda başlatır."""
        title_map = {
            "codex": "AGENT BUS: Codex Agent CLI",
            "claude": "AGENT BUS: Claude Code CLI",
            "antigravity": "AGENT BUS: Antigravity Agent (agy)",
            "normal": "AGENT BUS: Normal CLI",
        }
        title = title_map.get(cli_type, f"AGENT BUS: {cli_type.upper()}")
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
            self.app.notify(
                f"Harici konsol açıldı: [{cli_type.upper()}]",
                title="HARİCİ PENCERE",
                severity="information",
            )
        except Exception as e:
            self.app.notify(f"Harici konsol açılamadı: {e}", severity="error")

    async def add_new_tile(
        self,
        cli_type: str = "normal",
        initial_command: Optional[str] = None,
    ) -> None:
        """Mevcut düzene yeni bir CLI bölmesi ekler."""
        if len(self._active_tiles) >= 8:
            self.app.notify("En fazla 8 bölme açılabilir!", severity="warning")
            return

        specs = []
        for t in self._active_tiles.values():
            specs.append({"cli_type": t.cli_type, "command": t.initial_command or ""})

        specs.append({"cli_type": cli_type, "command": initial_command or ""})
        await self.apply_preset(self.current_preset, target_specs=specs)
        self.app.notify(f"Yeni pencere eklendi: [{cli_type.upper()}]", title="PENCERE AÇILDI")

    def handle_tile_action(self, action: str, tile_id: str, data: Dict[str, Any]) -> None:
        if action == "split_v":
            self.run_worker(self.split_tile(tile_id, direction="horizontal"))
        elif action == "split_h":
            self.run_worker(self.split_tile(tile_id, direction="vertical"))
        elif action == "close":
            self.run_worker(self.close_tile(tile_id))
        elif action == "new_window":
            self.prompt_new_window()

    async def split_tile(self, tile_id: str, direction: str = "horizontal") -> None:
        """Belirli bir bölmeyi yatay veya dikey olarak ikiye böler."""
        if len(self._active_tiles) >= 8:
            self.app.notify("Maksimum bölme sınırına ulaşıldı!", severity="warning")
            return

        specs = []
        for tid, t in self._active_tiles.items():
            specs.append({"cli_type": t.cli_type, "command": t.initial_command or ""})
            if tid == tile_id:
                # Yeni eş bölme ekle
                specs.append({"cli_type": "normal", "command": ""})

        await self.apply_preset("fit_all", target_specs=specs)

    async def close_tile(self, tile_id: str) -> None:
        """Bölmeyi kapatır ve kalanları yeniden dengeler."""
        if tile_id not in self._active_tiles:
            return

        closing_tile = self._active_tiles[tile_id]
        closing_tile.terminate_terminal()

        remaining_specs = []
        for tid, t in self._active_tiles.items():
            if tid != tile_id:
                remaining_specs.append({"cli_type": t.cli_type, "command": t.initial_command or ""})

        if not remaining_specs:
            remaining_specs = [{"cli_type": "normal", "command": ""}]

        await self.apply_preset(self.current_preset, target_specs=remaining_specs)
        self.app.notify("Pencere kapatıldı", title="AGENT BUS", severity="information")
