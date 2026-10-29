"""
Dynamic Tiling Workspace for Minion Fortress v3.0.
Supports recursive horizontal/vertical splitting, draggable divider resizing,
per-tile CLI selection, detaching to independent OS windows, and layout presets.
"""

from __future__ import annotations
import os
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from textual.app import ComposeResult
from textual import events
from textual.widgets import Static, Button
from textual.containers import Vertical, Horizontal
from rich.text import Text

from minion_fortress.core.state import FortressState
from minion_fortress.core.event_bus import EventBus
from minion_fortress.plugins.manager import PluginManager
from minion_fortress.ui.cli_tile import CliTilePane
from minion_fortress.ui.drag_splitter import DragSplitter
from minion_fortress.ui.context_menu import NewWindowModal


class DynamicWorkspace(Vertical):
    """Dynamic Tiling Canvas containing interactive CLI panes and preset toolbars."""

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
        background: #161616;
        border-bottom: heavy #FFE135;
        padding: 0 1;
        layout: horizontal;
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
    }
    .preset-btn:hover {
        background: #FFE135;
        color: #000000;
        text-style: bold;
    }
    .preset-btn-active {
        background: #00FF7F;
        color: #000000;
        text-style: bold;
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
        state: FortressState,
        event_bus: EventBus,
        plugin_manager: Optional[PluginManager] = None,
        initial_preset: str = "single",
    ) -> None:
        super().__init__(id="right-canvas")
        self.state = state
        self.event_bus = event_bus
        self.plugin_manager = plugin_manager
        self.current_preset = initial_preset
        self._tile_counter: int = 1
        self._active_tiles: Dict[str, CliTilePane] = {}
        self._tile_initial_commands: Dict[str, Optional[str]] = {}
        self.last_focused_tile_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        # Layout Presets Quick Toolbar (Çok Pencereli Sistem Düzenleri)
        with Horizontal(id="preset-toolbar"):
            yield Static("📐 ÇOKLU DÜZEN:", classes="preset-label")
            yield Button("🗖 Tümünü Sığdır", id="preset-fit-all", classes="preset-btn preset-btn-active", tooltip="Tüm Açık Pencereleri Ekrana Otomatik Sığdır")
            yield Button("⫴ 3 Sütun", id="preset-three-cols", classes="preset-btn", tooltip="Tüm Açık Pencereleri 3 Dikey Sütuna Dağıt")
            yield Button("◰ Ana + Yan Yığın", id="preset-main-stack", classes="preset-btn", tooltip="Sol Ana Pencere + Sağ Yan Yığın")
            yield Button("➕ Yeni Pencere", id="preset-add-tile", classes="preset-btn", tooltip="Yeni CLI Bölmesi Ekle")

        # Dynamic Tiling Container Canvas
        yield Vertical(id="workspace-canvas")

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Track which tile has focus for seamless tab switching."""
        for tid, tile in self._active_tiles.items():
            if tile.has_focus or any(c.has_focus for c in tile.walk_children()):
                self.last_focused_tile_id = tid
                break

    async def switch_active_or_first_tile(self, cli_type: str) -> None:
        """Switches the active or first CLI tile to the specified cli_type."""
        if not self._active_tiles:
            await self.apply_preset("single")

        target_tile = None
        if self.last_focused_tile_id and self.last_focused_tile_id in self._active_tiles:
            target_tile = self._active_tiles[self.last_focused_tile_id]
        elif self._active_tiles:
            target_tile = next(iter(self._active_tiles.values()))

        if target_tile:
            await target_tile.switch_cli(cli_type)

    async def on_mount(self) -> None:
        await self.apply_preset(self.current_preset)

    def _next_tile_id(self) -> str:
        tid = f"tile_{self._tile_counter}"
        self._tile_counter += 1
        return tid

    def _create_tile(
        self,
        cli_type: str,
        tile_id: Optional[str] = None,
        initial_command: Optional[str] = None,
    ) -> CliTilePane:
        tid = tile_id or self._next_tile_id()
        cmd = initial_command or self._tile_initial_commands.pop(cli_type, None)
        tile = CliTilePane(
            tile_id=tid,
            cli_type=cli_type,
            state=self.state,
            event_bus=self.event_bus,
            plugin_manager=self.plugin_manager,
            on_action=self.handle_tile_action,
            initial_command=cmd,
        )
        self._active_tiles[tid] = tile
        return tile

    async def apply_preset(self, preset_name: str, target_tiles: Optional[List[str]] = None) -> None:
        """Instantly rearranges workspace panes into a chosen preset layout."""
        self.current_preset = preset_name
        canvas = self.query_one("#workspace-canvas", Vertical)
        existing_types = [t.cli_type for t in self._active_tiles.values()]
        for child in list(canvas.children):
            await child.remove()
        self._active_tiles.clear()

        # Update button highlights
        for btn in self.query(".preset-btn"):
            btn.remove_class("preset-btn-active")
        try:
            active_btn = self.query_one(f"#preset-{preset_name.replace('_', '-')}", Button)
            active_btn.add_class("preset-btn-active")
        except Exception:
            pass

        if preset_name == "single":
            chosen = "minion-01"
            if target_tiles:
                chosen = target_tiles[0]
            elif self.last_focused_tile_id and self.last_focused_tile_id in self._active_tiles:
                chosen = self._active_tiles[self.last_focused_tile_id].cli_type
            elif existing_types:
                chosen = existing_types[0]

            tile = self._create_tile(chosen)
            col = Horizontal(tile, classes="split-col")
            await canvas.mount(col)

        elif preset_name == "split_v":
            t1 = self._create_tile("minion-01")
            t2 = self._create_tile("shell")
            splitter = DragSplitter(direction="horizontal")
            container = Horizontal(t1, splitter, t2, classes="split-col")
            await canvas.mount(container)

        elif preset_name == "split_h":
            t1 = self._create_tile("minion-01")
            t2 = self._create_tile("minion-02")
            splitter = DragSplitter(direction="vertical")
            container = Vertical(t1, splitter, t2, classes="split-row")
            await canvas.mount(container)

        elif preset_name == "grid_2x2":
            t1 = self._create_tile("minion-01")
            t2 = self._create_tile("minion-02")
            t3 = self._create_tile("minion-03")
            t4 = self._create_tile("shell")

            h_split1 = DragSplitter(direction="horizontal")
            h_split2 = DragSplitter(direction="horizontal")
            v_splitter = DragSplitter(direction="vertical")

            top_row = Horizontal(t1, h_split1, t2, classes="split-col")
            bot_row = Horizontal(t3, h_split2, t4, classes="split-col")
            container = Vertical(top_row, v_splitter, bot_row, classes="split-row")
            await canvas.mount(container)

        elif preset_name == "main_stack":
            types_to_arrange = target_tiles or (existing_types if existing_types else [])
            if not types_to_arrange:
                types_to_arrange = ["minion-01", "minion-02", "shell"]
            elif len(types_to_arrange) < 2:
                types_to_arrange = [types_to_arrange[0], "minion-02", "shell"]
            await self._build_main_stack_layout(canvas, types_to_arrange)

        elif preset_name == "three_cols":
            types_to_arrange = target_tiles or (existing_types if existing_types else [])
            if not types_to_arrange:
                types_to_arrange = ["minion-01", "minion-02", "shell"]
            elif len(types_to_arrange) < 3:
                pool = ["minion-01", "shell", "minion-02", "minion-03", "minion-04", "minion-05"]
                for p in pool:
                    if p not in types_to_arrange:
                        types_to_arrange.append(p)
                    if len(types_to_arrange) >= 3:
                        break
            await self._build_three_cols_layout(canvas, types_to_arrange)

        elif preset_name == "fit_all":
            # Fits active agent windows into optimal row/col grid
            if target_tiles:
                types_to_fit = target_tiles
            elif len(existing_types) > 1:
                types_to_fit = existing_types
            else:
                types_to_fit = ["minion-01", "minion-02", "minion-03", "shell"]

            await self._build_grid_layout(canvas, types_to_fit)

        if self._active_tiles:
            first_tile = next(iter(self._active_tiles.values()))
            first_tile.call_after_refresh(first_tile.focus_input)

        self.app.notify(f"Düzen uygulandı: {preset_name}", title="LAYOUT DEĞİŞTİ", severity="information")

    async def _build_grid_layout(self, canvas: Vertical, cli_types: List[str]) -> None:
        """Arranges any list of cli_types into an optimal grid of rows and columns with splitters."""
        tiles = [self._create_tile(ctype) for ctype in cli_types]
        n = len(tiles)
        if n == 0:
            return

        if n == 1:
            col = Horizontal(tiles[0], classes="split-col")
            await canvas.mount(col)
            return

        if n in (2, 3):
            # 1 row with columns
            h_children = []
            for i, t in enumerate(tiles):
                if i > 0:
                    h_children.append(DragSplitter(direction="horizontal"))
                h_children.append(t)
            container = Horizontal(*h_children, classes="split-col")
            await canvas.mount(container)
            return

        # n >= 4: distribute into optimal rows
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

    async def _build_three_cols_layout(self, canvas: Vertical, cli_types: List[str]) -> None:
        """Distributes all cli_types across 3 vertical columns with drag splitters,
        stacking extra windows vertically within columns so no active window is lost.
        """
        n = len(cli_types)
        if n == 0:
            return

        if n == 1:
            col = Horizontal(self._create_tile(cli_types[0]), classes="split-col")
            await canvas.mount(col)
            return

        if n == 2:
            t1 = self._create_tile(cli_types[0])
            s = DragSplitter(direction="horizontal")
            t2 = self._create_tile(cli_types[1])
            col = Horizontal(t1, s, t2, classes="split-col")
            await canvas.mount(col)
            return

        # n >= 3: distribute all n windows into 3 columns
        num_cols = 3
        base = n // num_cols
        rem = n % num_cols

        cols_tiles: List[List[str]] = []
        idx = 0
        for c in range(num_cols):
            count = base + (1 if c < rem else 0)
            cols_tiles.append(cli_types[idx : idx + count])
            idx += count

        col_widgets = []
        for c_types in cols_tiles:
            tiles = [self._create_tile(ctype) for ctype in c_types]
            if len(tiles) == 1:
                col_widgets.append(tiles[0])
            else:
                v_children = []
                for t_idx, t in enumerate(tiles):
                    if t_idx > 0:
                        v_children.append(DragSplitter(direction="vertical"))
                    v_children.append(t)
                v_box = Vertical(*v_children, classes="split-row")
                v_box.styles.width = "1fr"
                v_box.styles.height = "100%"
                col_widgets.append(v_box)

        h_children = []
        for i, col_w in enumerate(col_widgets):
            if i > 0:
                h_children.append(DragSplitter(direction="horizontal"))
            h_children.append(col_w)

        container = Horizontal(*h_children, classes="split-col")
        container.styles.width = "100%"
        container.styles.height = "100%"
        await canvas.mount(container)

    async def _build_main_stack_layout(self, canvas: Vertical, cli_types: List[str]) -> None:
        """Arranges all cli_types into Main (left column) + Stack (right column with vertical splitters)."""
        n = len(cli_types)
        if n == 0:
            return
        if n == 1:
            col = Horizontal(self._create_tile(cli_types[0]), classes="split-col")
            await canvas.mount(col)
            return

        main_tile = self._create_tile(cli_types[0])
        h_splitter = DragSplitter(direction="horizontal")

        stack_tiles = [self._create_tile(ctype) for ctype in cli_types[1:]]
        v_children = []
        for i, t in enumerate(stack_tiles):
            if i > 0:
                v_children.append(DragSplitter(direction="vertical"))
            v_children.append(t)

        right_stack = Vertical(*v_children, classes="split-row")
        right_stack.styles.width = "1fr"
        right_stack.styles.height = "100%"

        container = Horizontal(main_tile, h_splitter, right_stack, classes="split-col")
        container.styles.width = "100%"
        container.styles.height = "100%"
        await canvas.mount(container)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "preset-single":
            self.run_worker(self.apply_preset("single"))
        elif btn_id == "preset-split-v":
            self.run_worker(self.apply_preset("split_v"))
        elif btn_id == "preset-split-h":
            self.run_worker(self.apply_preset("split_h"))
        elif btn_id == "preset-grid-2x2":
            self.run_worker(self.apply_preset("grid_2x2"))
        elif btn_id == "preset-main-stack":
            self.run_worker(self.apply_preset("main_stack"))
        elif btn_id == "preset-three-cols":
            self.run_worker(self.apply_preset("three_cols"))
        elif btn_id == "preset-fit-all":
            self.run_worker(self.apply_preset("fit_all"))
        elif btn_id == "preset-add-tile":
            if getattr(self.app, "is_headless", False) and not getattr(self, "_test_modal_mode", False):
                self.run_worker(self.add_new_tile("minion-02" if "minion-02" not in [t.cli_type for t in self._active_tiles.values()] else "shell"))
            else:
                self.prompt_new_window()

    def prompt_new_window(self, default_target: str = "internal") -> None:
        """Presents the 4-choice iconic modal (Codex, Claude, Antigravity, Normal CLI) to open a new window."""
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
        """Launches an external native OS console window running the selected CLI."""
        title_map = {
            "codex": "MINION-FORTRESS: Codex Agent CLI",
            "claude": "MINION-FORTRESS: Claude Code CLI",
            "antigravity": "MINION-FORTRESS: Antigravity Agent (agy)",
            "normal": "MINION-FORTRESS: Normal CLI",
            "shell": "MINION-FORTRESS: Normal CLI",
        }
        title = title_map.get(cli_type, f"MINION-FORTRESS: {cli_type.upper()}")
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
                    subprocess.Popen('x-terminal-emulator || xterm', shell=True)
            self.app.notify(
                f"🪟 Harici konsol açıldı: [{cli_type.upper()}] (Komut: {cmd or 'cmd.exe'})",
                title="HARİCİ PENCERE",
                severity="information",
            )
        except Exception as e:
            self.app.notify(f"Harici pencere açılamadı: {e}", severity="error")

    async def add_new_tile(
        self,
        cli_type: Optional[str] = None,
        initial_command: Optional[str] = None,
    ) -> None:
        """Adds a new CLI tile to the current layout."""
        if len(self._active_tiles) >= 8:
            self.app.notify("Maksimum 8 bölme sınırına ulaşıldı!", title="DAHA FAZLA EKLENEMEZ", severity="warning")
            return

        if cli_type is None:
            self.prompt_new_window()
            return

        canvas = self.query_one("#workspace-canvas", Vertical)
        existing_types = {t.cli_type for t in self._active_tiles.values()}
        new_cli = cli_type

        if initial_command is None:
            if new_cli == "codex":
                initial_command = "codex"
            elif new_cli == "claude":
                initial_command = "claude"
            elif new_cli in ("antigravity", "agy"):
                initial_command = "agy --dangerously-skip-permissions"
            elif new_cli == "shell" and "shell" in existing_types:
                options = ["minion-02", "minion-03", "minion-04", "minion-05", "agy", "shell"]
                for opt in options:
                    if opt not in existing_types:
                        new_cli = opt
                        break

        new_tile = self._create_tile(new_cli, initial_command=initial_command)
        splitter = DragSplitter(direction="vertical")
        await canvas.mount(splitter)
        await canvas.mount(new_tile)
        new_tile.call_after_refresh(new_tile.focus_active_widget)
        cmd_info = f" (Komut: '{initial_command}')" if initial_command else ""
        self.app.notify(f"Yeni CLI bölmesi eklendi: [{new_cli.upper()}]{cmd_info}", title="YENİ PENCERE")

    def handle_tile_action(self, action: str, tile_id: str, data: Dict[str, Any]) -> None:
        """Dispatches right-click and header actions from tiles."""
        if action == "split_v":
            self.run_worker(self.split_tile(tile_id, direction="horizontal"))
        elif action == "split_h":
            self.run_worker(self.split_tile(tile_id, direction="vertical"))
        elif action == "close":
            self.run_worker(self.close_tile(tile_id))
        elif action == "detach":
            cli_type = data.get("cli_type", "all")
            self.detach_tile(tile_id, cli_type)
        elif action == "new_window":
            self.prompt_new_window()

    async def split_tile(self, tile_id: str, direction: str = "horizontal") -> bool:
        """Splits an active tile either horizontally (columns) or vertically (rows)."""
        target_tile = self._active_tiles.get(tile_id)
        if not target_tile or not target_tile.parent:
            return False

        # Guard 1: Maximum active tiles limit
        if len(self._active_tiles) >= 8:
            self.app.notify("Maksimum 8 bölme sınırına ulaşıldı, daha fazla bölünemez!", title="DAHA FAZLA BÖLÜNEMEZ", severity="warning")
            return False

        # Guard 2: Minimum size check to prevent collapsing or invisible tiles
        w = target_tile.outer_size.width or target_tile.size.width
        h = target_tile.outer_size.height or target_tile.size.height

        if direction == "horizontal":
            # Requires at least 18 columns so each sub-pane has usable space
            if w > 0 and w < 18:
                self.app.notify("Pencere çok dar, daha fazla bölünemez! (En az 18 sütun gerekli)", title="DAHA FAZLA BÖLÜNEMEZ", severity="warning")
                return False
        else:
            # Requires at least 8 rows so each sub-pane has usable space
            if h > 0 and h < 8:
                self.app.notify("Pencere çok basık, daha fazla bölünemez! (En az 8 satır gerekli)", title="DAHA FAZLA BÖLÜNEMEZ", severity="warning")
                return False

        parent = target_tile.parent
        cli_options = ["shell", "minion-02", "minion-03", "minion-04", "minion-05"]
        # Pick next unused CLI type
        new_cli = "shell"
        for opt in cli_options:
            if not any(t.cli_type == opt for t in self._active_tiles.values()):
                new_cli = opt
                break

        new_tile = self._create_tile(new_cli)
        splitter = DragSplitter(direction=direction)

        if direction == "horizontal":
            # If parent is already Horizontal (and not canvas), insert after target
            if isinstance(parent, Horizontal) and parent.id != "workspace-canvas":
                await parent.mount(splitter, after=target_tile)
                await parent.mount(new_tile, after=splitter)
            else:
                # Wrap target_tile and new_tile inside a new Horizontal container
                h_box = Horizontal(classes="split-col")
                h_box.styles.height = "1fr"
                h_box.styles.width = "100%"
                await parent.mount(h_box, after=target_tile)
                target_tile._is_moving = True
                try:
                    await target_tile.remove()
                    await h_box.mount(target_tile)
                    await h_box.mount(splitter)
                    await h_box.mount(new_tile)
                finally:
                    target_tile._is_moving = False
        else:
            # Vertical split
            if isinstance(parent, Vertical) and parent.id != "workspace-canvas":
                await parent.mount(splitter, after=target_tile)
                await parent.mount(new_tile, after=splitter)
            else:
                v_box = Vertical(classes="split-row")
                v_box.styles.width = "1fr"
                v_box.styles.height = "100%"
                await parent.mount(v_box, after=target_tile)
                target_tile._is_moving = True
                try:
                    await target_tile.remove()
                    await v_box.mount(target_tile)
                    await v_box.mount(splitter)
                    await v_box.mount(new_tile)
                finally:
                    target_tile._is_moving = False

        new_tile.call_after_refresh(new_tile.focus_input)
        self.app.notify(f"Pencere bölündü: Yeni [{new_cli}] açıldı.", title="PENCERE BÖLÜNDÜ")
        return True

    async def close_tile(self, tile_id: str) -> None:
        """Closes a tile and adjusts layout."""
        if len(self._active_tiles) <= 1:
            self.app.notify("En az bir CLI bölmesi açık kalmalıdır!", severity="warning")
            return

        target_tile = self._active_tiles.pop(tile_id, None)
        if not target_tile:
            return

        # Explicitly terminate active background processes and PTY on close
        if hasattr(target_tile, "_current_widget") and target_tile._current_widget:
            w = target_tile._current_widget
            setattr(w, "_is_closing", True)
            if hasattr(w, "active_proc") and w.active_proc:
                try:
                    w.active_proc.kill()
                except Exception:
                    pass
            # Terminate PTY if w is an EmbeddedTerminalWidget or has a pty
            if hasattr(w, "pty") and w.pty:
                try:
                    if w.pty.isalive():
                        w.pty.terminate()
                    w.pty.close()
                except Exception:
                    pass
            if hasattr(w, "_current_terminal") and w._current_terminal:
                term = w._current_terminal
                term._is_closing = True
                if term.pty and term.pty.isalive():
                    try:
                        term.pty.terminate()
                        term.pty.close()
                    except Exception:
                        pass

        parent = target_tile.parent
        await target_tile.remove()

        # Also remove adjacent splitter if any
        if parent:
            for child in list(parent.children):
                if isinstance(child, DragSplitter):
                    await child.remove()
                    break
            # Remove container if empty
            if len(parent.children) == 0 and parent.parent:
                await parent.remove()

        self.app.notify(f"CLI bölmesi kapatıldı: {tile_id}", title="KAPATILDI")

    def detach_tile(self, tile_id: str, cli_type: str) -> None:
        """Spawns an independent OS console window hosting this specific CLI."""
        root_path = Path(__file__).resolve().parent.parent.parent
        script_path = root_path / "detached_monitor.py"
        py_exec = sys.executable

        try:
            target_arg = f"--target {cli_type}"
            if os.name == "nt":
                cmd = f'start "MINION-FORTRESS: Detached [{cli_type.upper()}]" "{py_exec}" "{script_path}" {target_arg}'
                subprocess.Popen(cmd, shell=True)
            else:
                for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
                    if shutil.which(term):
                        subprocess.Popen([term, "-e", f"{py_exec} {script_path} {target_arg}"])
                        break
                else:
                    subprocess.Popen([py_exec, str(script_path), "--target", cli_type])

            self.app.notify(
                f"🗗 [{cli_type.upper()}] bağımsız Windows penceresi olarak ayrıldı!",
                title="BİRLEŞİK DÜZENDEN AYRILDI",
                severity="information",
            )
        except Exception as e:
            self.app.notify(f"Pencere ayrılamadı: {e}", severity="error")
