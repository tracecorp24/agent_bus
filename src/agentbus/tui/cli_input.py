"""
Enhanced CLI Command Input Widget for Minion Fortress.
Provides:
- Native OS clipboard paste (Ctrl+V, Shift+Insert, and right-click)
- Select All (Ctrl+A)
- Native OS clipboard copy (Ctrl+C)
- Native OS clipboard cut (Ctrl+X)
"""

from __future__ import annotations
import os
import shutil
import subprocess
from typing import Optional
from textual.widgets import Input
from textual.binding import Binding
from textual import events


def get_clipboard_text() -> str:
    """Safely retrieves text from the system clipboard across OS platforms."""
    # 1. Tkinter standard library (Windows / macOS / Linux with Tk)
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        val = r.clipboard_get()
        r.destroy()
        if val is not None:
            return str(val)
    except Exception:
        pass

    # 2. Windows PowerShell fallback
    if os.name == "nt":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if res.stdout:
                return res.stdout.strip("\r\n")
        except Exception:
            pass
    else:
        # 3. Linux/Unix utilities fallback (wl-paste, xclip, pbpaste)
        for tool, args in [("wl-paste", []), ("xclip", ["-selection", "clipboard", "-o"]), ("pbpaste", [])]:
            if shutil.which(tool):
                try:
                    res = subprocess.run([tool] + args, capture_output=True, text=True, timeout=1)
                    if res.stdout:
                        return res.stdout.strip("\r\n")
                except Exception:
                    pass

    return ""


def set_clipboard_text(text: str) -> bool:
    """Safely writes text to the system clipboard across OS platforms."""
    # 1. Tkinter standard library
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        pass

    # 2. Windows PowerShell fallback
    if os.name == "nt":
        try:
            proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", "Set-Clipboard"], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode("utf-8"), timeout=1)
            return True
        except Exception:
            pass
    else:
        # 3. Linux/Unix fallback (wl-copy, xclip, pbcopy)
        for tool, args in [("wl-copy", []), ("xclip", ["-selection", "clipboard"]), ("pbcopy", [])]:
            if shutil.which(tool):
                try:
                    proc = subprocess.Popen([tool] + args, stdin=subprocess.PIPE)
                    proc.communicate(input=text.encode("utf-8"), timeout=1)
                    return True
                except Exception:
                    pass

    return False


class CliCommandInput(Input):
    """Custom CLI Input widget with native OS clipboard paste and full Ctrl+A select-all support."""

    BINDINGS = [
        Binding("ctrl+a", "select_all", "Tümünü Seç", priority=True),
        Binding("ctrl+v", "os_paste", "Yapıştır", priority=True),
        Binding("ctrl+shift+v", "os_paste", "Yapıştır", priority=True),
        Binding("shift+insert", "os_paste", "Yapıştır", priority=True),
        Binding("ctrl+c", "os_copy", "Kopyala", priority=True),
        Binding("ctrl+x", "os_cut", "Kes", priority=True),
    ]

    def action_select_all(self) -> None:
        """Selects all text currently in the input."""
        self.select_all()

    def action_os_paste(self) -> None:
        """Pastes text from the OS system clipboard into the input, replacing selection if any."""
        text = get_clipboard_text().strip("\r\n")
        if text:
            if self.selection and self.selection.start != self.selection.end:
                self.delete_selection()
            self.insert_text_at_cursor(text)
            self.focus()
            try:
                self.app.notify(f"📋 Panodan yapıştırıldı: {text[:28]}...", title="YAPIŞTIRILDI", timeout=1.5)
            except Exception:
                pass

    def action_os_copy(self) -> None:
        """Copies selected text (or all text if none selected) to the OS system clipboard."""
        text = self.selected_text or self.value
        if text:
            set_clipboard_text(text)
            try:
                self.app.notify(f"📋 Panoya kopyalandı: {text[:28]}...", title="KOPYALANDI", timeout=1.5)
            except Exception:
                pass

    def action_os_cut(self) -> None:
        """Cuts selected text (or all text if none selected) to the OS system clipboard."""
        text = self.selected_text or self.value
        if text:
            set_clipboard_text(text)
            if self.selection and self.selection.start != self.selection.end:
                self.delete_selection()
            else:
                self.value = ""
            try:
                self.app.notify(f"✂ Kesildi ve kopyalandı", title="KESİLDİ", timeout=1.5)
            except Exception:
                pass

    def on_click(self, event: events.Click) -> None:
        """Right-click on the input field pastes clipboard text directly."""
        if event.button == 3:
            event.stop()
            self.action_os_paste()
