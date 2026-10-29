"""
Embedded Native Terminal Widget (ConPTY / PTY) for Minion Fortress.
Runs a 100% genuine, unfiltered Windows console (cmd.exe / powershell.exe)
inside a miniaturized Textual pane with VT100/Xterm emulation via winpty + pyte.
"""

from __future__ import annotations
import asyncio
import os
import sys
from typing import Optional, List, Dict, Any

from textual.widget import Widget
from textual import events
from rich.text import Text
from rich.style import Style
from rich.console import Group

try:
    import pyte
    from winpty import PtyProcess
    HAS_WINPTY = True
except ImportError:
    HAS_WINPTY = False

PYTE_COLOR_MAP: Dict[str, Optional[str]] = {
    "default": None,
    "black": "black",
    "red": "red",
    "green": "green",
    "brown": "yellow",
    "yellow": "yellow",
    "blue": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "white": "white",
}


def map_color(c: Optional[str]) -> Optional[str]:
    if not c or c == "default":
        return None
    return PYTE_COLOR_MAP.get(c, c)


def row_to_rich(row_dict: Any, max_cols: int = 80, cursor_col: Optional[int] = None) -> Text:
    """Converts a pyte screen row buffer into a styled Rich Text object."""
    res = Text()
    cur_style = None
    cur_text: List[str] = []

    for x in range(max_cols):
        char = row_dict.get(x) if hasattr(row_dict, "get") else None
        ch = char.data if char and char.data else " "
        fg = map_color(char.fg) if char else None
        bg = map_color(char.bg) if char else None
        bold = bool(char.bold) if char else False
        reverse = bool(char.reverse) if char else False

        if cursor_col is not None and x == cursor_col:
            reverse = not reverse

        style_key = (fg, bg, bold, reverse)
        if style_key != cur_style:
            if cur_text:
                s_obj = Style(color=cur_style[0], bgcolor=cur_style[1], bold=cur_style[2], reverse=cur_style[3])
                res.append("".join(cur_text), style=s_obj)
                cur_text = []
            cur_style = style_key
        cur_text.append(ch)

    if cur_text:
        s_obj = Style(color=cur_style[0], bgcolor=cur_style[1], bold=cur_style[2], reverse=cur_style[3])
        res.append("".join(cur_text), style=s_obj)

    return res


class EmbeddedTerminalWidget(Widget):
    """A real, interactive PTY terminal widget running a native shell inside Textual."""

    can_focus = True

    DEFAULT_CSS = """
    EmbeddedTerminalWidget {
        width: 100%;
        height: 1fr;
        background: #0C0C0C;
        color: #CCCCCC;
        border: none;
        padding: 0;
        margin: 0;
    }
    EmbeddedTerminalWidget:focus {
        background: #0A0A0A;
    }
    """

    def __init__(
        self,
        shell_cmd: str = "cmd.exe",
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        cols: int = 80,
        rows: int = 24,
        id: Optional[str] = None,
        classes: Optional[str] = None,
        initial_command: Optional[str] = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.shell_cmd = shell_cmd
        self.env = env
        self.cwd = cwd or os.getcwd()
        self.cols = max(20, cols)
        self.rows = max(5, rows)
        self.initial_command = initial_command
        self.running = False
        self.pty: Optional[PtyProcess] = None
        self.term_scroll_offset: int = 0
        self.cursor_visible: bool = True
        self._is_closing: bool = False

        if HAS_WINPTY:
            self.screen_model = pyte.HistoryScreen(self.cols, self.rows, history=500)
            self.stream = pyte.Stream(self.screen_model)
        else:
            self.screen_model = None
            self.stream = None

    def on_mount(self) -> None:
        if not HAS_WINPTY:
            return

        cols = max(20, self.size.width) if self.size.width > 0 else self.cols
        rows = max(5, self.size.height) if self.size.height > 0 else self.rows
        self.cols = cols
        self.rows = rows
        if self.screen_model:
            self.screen_model.resize(self.rows, self.cols)

        if self.pty and self.pty.isalive():
            self.running = True
            self.run_worker(self._pty_reader_loop, name="pty-reader", exclusive=False)
            self.set_interval(0.6, self._blink_cursor)
            if self.initial_command:
                self.run_worker(self._send_initial_command, name="send-init-cmd")
            self.refresh()
            return

        try:
            spawn_kwargs: Dict[str, Any] = {"dimensions": (self.rows, self.cols)}
            if self.env:
                spawn_kwargs["env"] = self.env
            if self.cwd:
                spawn_kwargs["cwd"] = self.cwd
            self.pty = PtyProcess.spawn(self.shell_cmd, **spawn_kwargs)
            self.running = True
            self.run_worker(self._pty_reader_loop, name="pty-reader", exclusive=False)
            self.set_interval(0.6, self._blink_cursor)
            if self.initial_command:
                self.run_worker(self._send_initial_command, name="send-init-cmd")
        except Exception:
            self.running = False

    async def _send_initial_command(self) -> None:
        """Pastes and executes the initial command into the PTY once spawned."""
        await asyncio.sleep(0.25)
        if self.running and self.pty and self.pty.isalive() and self.initial_command:
            self.write_command(self.initial_command)
            try:
                from agentbus.tui.cli_input import set_clipboard_text
                set_clipboard_text(self.initial_command)
            except Exception:
                pass

    async def _pty_reader_loop(self) -> None:
        """Background worker continually reading bytes from ConPTY and feeding pyte."""
        while self.running and self.pty and self.pty.isalive():
            try:
                data = await asyncio.to_thread(self.pty.read, 1024)
                if not data:
                    break
                self.stream.feed(data)
                self.term_scroll_offset = 0
                self.refresh()
            except Exception:
                break

        if self.running and self.stream:
            try:
                self.stream.feed("\r\n\x1b[33m[İşlem tamamlandı - Yeniden başlatmak için Enter'a basın]\x1b[0m\r\n")
                self.refresh()
            except Exception:
                pass

    def _blink_cursor(self) -> None:
        if self.has_focus:
            self.cursor_visible = not self.cursor_visible
            self.refresh()

    def on_resize(self, event: events.Resize) -> None:
        if not HAS_WINPTY or not self.screen_model:
            return

        new_cols = max(20, event.size.width)
        new_rows = max(5, event.size.height)
        if (new_cols, new_rows) != (self.cols, self.rows):
            self.cols = new_cols
            self.rows = new_rows
            try:
                self.screen_model.resize(new_rows, new_cols)
                if self.pty and self.pty.isalive():
                    self.pty.setwinsize(new_rows, new_cols)
            except Exception:
                pass
            self.refresh()

    def on_click(self, event: events.Click) -> None:
        self.focus()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.focus()

    def on_key(self, event: events.Key) -> None:
        if not self.pty or not self.pty.isalive():
            if event.key.lower() in ("enter", "return"):
                self.restart_terminal()
            return

        key = event.key.lower()
        if key in ("ctrl+v", "shift+insert"):
            try:
                from agentbus.tui.cli_input import get_clipboard_text
                text = get_clipboard_text()
                if text and self.pty and self.pty.isalive():
                    norm_text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
                    self.pty.write(norm_text)
                    self.term_scroll_offset = 0
            except Exception:
                pass
            event.stop()
            event.prevent_default()
            return

        key_map = {
            "enter": "\r",
            "return": "\r",
            "backspace": "\x08",
            "tab": "\t",
            "escape": "\x1b",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "right": "\x1b[C",
            "left": "\x1b[D",
            "home": "\x1b[H",
            "end": "\x1b[F",
            "pageup": "\x1b[5~",
            "pagedown": "\x1b[6~",
            "delete": "\x1b[3~",
            "ctrl+c": "\x03",
            "ctrl+d": "\x04",
            "ctrl+z": "\x1a",
            "ctrl+l": "\x0c",
            "ctrl+a": "\x01",
            "ctrl+e": "\x05",
            "ctrl+u": "\x15",
            "ctrl+k": "\x0b",
            "space": " ",
        }

        if key in key_map:
            self.pty.write(key_map[key])
            self.term_scroll_offset = 0
            event.stop()
            event.prevent_default()
        elif event.character:
            self.pty.write(event.character)
            self.term_scroll_offset = 0
            event.stop()
            event.prevent_default()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.screen_model and hasattr(self.screen_model, "history"):
            max_hist = len(self.screen_model.history.top)
            self.term_scroll_offset = min(max_hist, self.term_scroll_offset + 3)
            self.refresh()
            event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.term_scroll_offset > 0:
            self.term_scroll_offset = max(0, self.term_scroll_offset - 3)
            self.refresh()
            event.stop()

    def write_command(self, cmd_text: str) -> None:
        """Sends a command string followed by Enter to the PTY."""
        if self.pty and self.pty.isalive():
            self.pty.write(cmd_text + "\r\n")
            self.term_scroll_offset = 0

    def restart_terminal(self) -> None:
        """Restarts the PTY shell process with a clean screen."""
        self.running = False
        if self.pty and self.pty.isalive():
            try:
                self.pty.terminate()
            except Exception:
                pass

        if HAS_WINPTY:
            self.screen_model = pyte.HistoryScreen(self.cols, self.rows, history=500)
            self.stream = pyte.Stream(self.screen_model)
            try:
                spawn_kwargs: Dict[str, Any] = {"dimensions": (self.rows, self.cols)}
                if self.env:
                    spawn_kwargs["env"] = self.env
                if self.cwd:
                    spawn_kwargs["cwd"] = self.cwd
                self.pty = PtyProcess.spawn(self.shell_cmd, **spawn_kwargs)
                self.running = True
                self.run_worker(self._pty_reader_loop, name="pty-reader", exclusive=False)
            except Exception:
                self.running = False
        self.refresh()

    def render(self) -> Group:
        if not HAS_WINPTY or not self.screen_model:
            fallback = Text(
                "⚠ Gerçek PTY Terminal modülü (winpty/pyte) yüklenemedi.\n"
                "Standart Shell akışı devrede.",
                style="bold yellow",
            )
            return Group(fallback)

        # Dynamically adapt terminal buffer and ConPTY size when widget dimensions change
        cur_cols = max(20, self.size.width) if self.size.width > 0 else self.cols
        cur_rows = max(5, self.size.height) if self.size.height > 0 else self.rows
        if (cur_cols != self.cols or cur_rows != self.rows) and self.screen_model:
            self.cols = cur_cols
            self.rows = cur_rows
            try:
                self.screen_model.resize(self.rows, self.cols)
                if self.pty and self.pty.isalive():
                    self.pty.setwinsize(self.rows, self.cols)
            except Exception:
                pass

        lines: List[Text] = []
        cursor_y = self.screen_model.cursor.y
        cursor_x = self.screen_model.cursor.x
        show_cursor = self.has_focus and self.cursor_visible and self.term_scroll_offset == 0

        # If user scrolled back into history
        if self.term_scroll_offset > 0 and hasattr(self.screen_model, "history"):
            hist = list(self.screen_model.history.top)
            total_hist = len(hist)
            start_idx = max(0, total_hist - self.term_scroll_offset)
            visible_hist = hist[start_idx : start_idx + self.rows]
            for row in visible_hist:
                lines.append(row_to_rich(row, max_cols=self.cols, cursor_col=None))
            # Fill remaining rows from screen buffer if needed
            needed = self.rows - len(lines)
            for y in range(needed):
                row_buffer = self.screen_model.buffer[y] if y in self.screen_model.buffer else {}
                lines.append(row_to_rich(row_buffer, max_cols=self.cols, cursor_col=None))
        else:
            # Live bottom viewport
            for y in range(self.rows):
                is_cursor_row = (y == cursor_y and show_cursor)
                c_col = cursor_x if is_cursor_row else None
                row_buffer = self.screen_model.buffer[y] if y in self.screen_model.buffer else {}
                rich_line = row_to_rich(row_buffer, max_cols=self.cols, cursor_col=c_col)
                lines.append(rich_line)

        return Group(*lines)

    def on_unmount(self) -> None:
        # Check if widget or any parent is temporarily being moved during layout splitting
        is_moving = getattr(self, "_is_moving", False)
        curr = self.parent
        while curr and not is_moving:
            if getattr(curr, "_is_moving", False):
                is_moving = True
                break
            curr = curr.parent

        if not is_moving:
            self.running = False
            if self.pty:
                try:
                    if self.pty.isalive():
                        self.pty.terminate()
                    self.pty.close()
                except Exception:
                    pass
