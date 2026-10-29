"""
Interactive Shell CLI Pane for Minion Fortress.
Allows running OS shell commands, interactive agents (e.g. agy), Python snippets,
and fortress commands with non-blocking real-time streaming output or external window spawning.
"""

from __future__ import annotations
import asyncio
import json
import os
import shutil
import subprocess
import sys
from typing import Optional, Callable, List

from textual.app import ComposeResult
from textual.widgets import Static, RichLog, Button
from textual.containers import Vertical, Horizontal
from rich.markup import escape
from rich.text import Text

from minion_fortress.core.state import FortressState
from minion_fortress.core.event_bus import EventBus, Event, EventType
from minion_fortress.ui.panes.embedded_terminal import EmbeddedTerminalWidget


class InteractiveShellPane(Vertical):
    """An interactive system, agent (agy) and fortress shell pane with live streaming execution."""

    def __init__(
        self,
        state: FortressState,
        event_bus: EventBus,
        initial_agy_mode: bool = False,
        on_mode_change: Optional[Callable[[str, str], None]] = None,
        initial_command: Optional[str] = None,
    ) -> None:
        super().__init__(classes="pane-container shell-container")
        self.state = state
        self.event_bus = event_bus
        self.agy_mode = initial_agy_mode
        self.agy_flags: List[str] = ["--dangerously-skip-permissions"]
        self.on_mode_change = on_mode_change
        self.initial_command = initial_command
        self.active_proc: Optional[asyncio.subprocess.Process] = None
        self.log_history: List[Any] = []
        self._is_closing: bool = False
        self._current_terminal: Optional[EmbeddedTerminalWidget] = None
        self._current_log: Optional[RichLog] = None

    def _write_log(self, item: Any) -> None:
        """Stores output into memory history and renders to RichLog widget safely."""
        self.log_history.append(item)
        try:
            log = self.query_one("#shell-stream", RichLog)
            log.write(item)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        title = "🤖 ANTIGRAVITY AGENT CLI" if self.agy_mode else "💻 GERÇEK GÖMÜLÜ TERMİNAL (ConPTY)"
        with Horizontal(classes="action-bar shell-action-bar"):
            yield Static(f"{title}", classes="shell-status-label", id="shell-title-static")
            yield Button("🖥️ Term", id="btn-mode-terminal", classes="shell-hdr-btn active-btn", tooltip="Gerçek Gömülü ConPTY Konsolu")
            yield Button("🤖 Akış", id="btn-mode-stream", classes="shell-hdr-btn", tooltip="Canlı Agent Ara Adım Akışı")
            yield Button("🪟 Harici", id="btn-open-terminal", classes="shell-hdr-btn", tooltip="Yeni Windows Konsolunda Aç")

        with Vertical(id="shell-view-container"):
            if self._current_terminal is None:
                self._current_terminal = EmbeddedTerminalWidget(id="embedded-pty-terminal")
            yield self._current_terminal

            if self._current_log is None:
                self._current_log = RichLog(id="shell-stream", classes="log-stream", highlight=True, markup=True, wrap=True, min_width=0)
            yield self._current_log

    def on_mount(self) -> None:
        try:
            log = self.query_one("#shell-stream", RichLog)
        except Exception:
            return
        # If widget is remounted after layout split or DOM move, replay entire log history seamlessly!
        if self.log_history:
            if len(log.lines) == 0:
                for item in self.log_history:
                    log.write(item)
            if self.agy_mode:
                self.switch_to_stream_view()
            else:
                self.switch_to_terminal_view()
            return

        cwd = os.getcwd()
        py_ver = sys.version.split()[0]
        if self.agy_mode:
            self.switch_to_stream_view()
            banner = (
                f"[bold #00FF7F]🤖 Antigravity AI Agent CLI Aktif[/bold #00FF7F]\n"
                f"[dim]Working directory: {escape(cwd)} │ Parametreler: {' '.join(self.agy_flags)}[/dim]\n"
                f"[cyan]• Canlı ara adımlar (tool çağrıları, dosya okuma/yazma, komutlar) anında bu ekranda akar.[/cyan]\n"
                f"[dim]• Durdurmak için 'stop', standart kabuğa dönmek için 'exit' yazabilirsiniz.\n"
                f"• Yeni bağımsız Windows konsolunda tam TUI açmak için yukarıdaki butona tıklayın veya 'open agy' yazın.[/dim]\n"
            )
        else:
            self.switch_to_terminal_view()
            banner = (
                f"[bold #00FF7F]Minion-Fortress Shell v3.0[/bold #00FF7F] (Python {py_ver})\n"
                f"[dim]Working directory: {escape(cwd)}[/dim]\n"
                f"[cyan]Kullanılabilir: agy, python, dir, git, curl, fortress komutları, 'open <komut>' veya 'stop'.[/cyan]\n"
            )
        self._write_log(banner)
        if self.initial_command:
            self.run_worker(self._send_shell_initial_command, name="shell-init-cmd")

    async def _send_shell_initial_command(self) -> None:
        await asyncio.sleep(0.3)
        if self.initial_command and not self._is_closing:
            await self.execute_command(self.initial_command)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-open-terminal":
            self.action_open_external_terminal()
        elif btn_id == "btn-mode-terminal":
            self.switch_to_terminal_view()
        elif btn_id == "btn-mode-stream":
            self.switch_to_stream_view()

    def switch_to_terminal_view(self) -> None:
        """Switches view to the real embedded ConPTY terminal."""
        self.remove_class("shell-stream-active")
        try:
            title = self.query_one("#shell-title-static", Static)
            title.update("💻 GERÇEK GÖMÜLÜ TERMİNAL (ConPTY Live)")
            self.query_one("#btn-mode-terminal", Button).add_class("active-btn")
            self.query_one("#btn-mode-stream", Button).remove_class("active-btn")
            term = self.query_one("#embedded-pty-terminal", EmbeddedTerminalWidget)
            term.focus()
        except Exception:
            pass

    def switch_to_stream_view(self) -> None:
        """Switches view to the live stream log."""
        self.add_class("shell-stream-active")
        try:
            title = self.query_one("#shell-title-static", Static)
            title.update("🤖 ANTIGRAVITY AGENT AKIŞI (Canlı Adımlar)")
            self.query_one("#btn-mode-terminal", Button).remove_class("active-btn")
            self.query_one("#btn-mode-stream", Button).add_class("active-btn")
        except Exception:
            pass

    def action_open_external_terminal(self, cmd_target: Optional[str] = None) -> None:
        """Launches a full, unfiltered, raw native OS terminal window with native ConPTY."""
        target = cmd_target or ("agy" if self.agy_mode else "cmd.exe")
        try:
            if os.name == "nt":
                subprocess.Popen(f'start "MINION-FORTRESS: Tam Terminal [{target}]" cmd /k "{target}"', shell=True)
            else:
                subprocess.Popen(f'x-terminal-emulator -e "{target}" || xterm -e "{target}"', shell=True)
            self._write_log(f"[bold green]✔ Harici filtresiz işletim sistemi terminali açıldı:[/bold green] [yellow]{target}[/yellow]")
        except Exception as e:
            self._write_log(f"[bold red]Harici terminal açılamadı:[/bold red] {escape(str(e))}")

    async def execute_command(self, cmd_str: str) -> None:
        """Executes a command safely without blocking the Textual event loop."""
        cmd_str = cmd_str.strip()
        if not cmd_str:
            return

        cmd_lower = cmd_str.lower()

        # -------------------------------------------------------------
        # A. AGY AGENT MODE ACTIVE
        # -------------------------------------------------------------
        if self.agy_mode:
            # 1. AGY Stop / Exit commands
            if cmd_lower in ("stop", "kill", "durdur"):
                if self.active_proc and self.active_proc.returncode is None:
                    pid = self.active_proc.pid
                    try:
                        if os.name == "nt":
                            subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
                        else:
                            self.active_proc.kill()
                        self._write_log(f"[bold red]🛑 Aktif Antigravity işlemi (PID: {pid}) durduruldu.[/bold red]")
                    except Exception as e:
                        self._write_log(f"[red]İşlem durdurulamadı: {escape(str(e))}[/red]")
                    self.active_proc = None
                else:
                    self._write_log("[dim yellow]Şu anda çalışan bir arka plan işlemi yok.[/dim yellow]")
                return

            if cmd_lower in ("exit", "quit", "q", "/exit", "/quit", "exit()"):
                if self.active_proc and self.active_proc.returncode is None:
                    try:
                        if os.name == "nt":
                            subprocess.run(f"taskkill /F /T /PID {self.active_proc.pid}", shell=True, capture_output=True)
                        else:
                            self.active_proc.kill()
                    except Exception:
                        pass
                    self.active_proc = None

                self.agy_mode = False
                self.switch_to_terminal_view()
                if self.on_mode_change:
                    self.on_mode_change("shell", "Shell Komutu: dir, git, python, banana, heal, help...")
                self._write_log("[dim yellow]Antigravity oturumu sonlandırıldı. Standart terminal moduna dönüldü.[/dim yellow]")
                return

            if cmd_lower in ("clear", "cls"):
                self.log_history.clear()
                try:
                    self.query_one("#shell-stream", RichLog).clear()
                except Exception:
                    pass
                return

            if cmd_lower in ("help", "?"):
                help_text = (
                    "[bold cyan]Antigravity Agent CLI Komutları:[/bold cyan]\n"
                    "• [yellow]Mesaj / Prompt:[/yellow] Doğrudan görevi yazın; ara adımlar (araçlar, çıktılar) canlı olarak akar.\n"
                    "• [yellow]stop / durdur:[/yellow] Çalışmakta olan model yanıtını anında durdurur.\n"
                    "• [yellow]exit / quit:[/yellow] Agent oturumundan çıkıp standart kabuğa döner.\n"
                    "• [yellow]open agy:[/yellow] Ayrı bir Windows konsolunda tam BubbleTea TUI olarak açar.\n"
                    "• [yellow]clear / cls:[/yellow] Ekranı temizler."
                )
                self._write_log(help_text)
                return

            if cmd_lower.startswith("open") or cmd_lower.startswith("start"):
                tokens = cmd_str.split()
                target_cmd = " ".join(tokens[1:]) or "agy --dangerously-skip-permissions"
                self.action_open_external_terminal(target_cmd)
                return

            # Check if previous turn is still running
            if self.active_proc and self.active_proc.returncode is None:
                self._write_log("[dim yellow]⚠ Önceki Antigravity görevi hala çalışıyor. Durdurmak için 'stop' yazın.[/dim yellow]")
                return

            # Strip leading 'agy' if user typed 'agy <prompt>'
            prompt_text = cmd_str
            if prompt_text.lower().startswith("agy "):
                prompt_text = prompt_text[4:].strip()

            await self._stream_agy_command(prompt_text)
            return

        # -------------------------------------------------------------
        # B. STANDARD SHELL MODE
        # -------------------------------------------------------------
        self._write_log(f"\n[bold #FFE135]shell>[/bold #FFE135] [white]{escape(cmd_str)}[/white]")

        # 1. Process termination commands
        if cmd_lower in ("stop", "kill", "quit", "exit", "^c", "c"):
            if self.active_proc and self.active_proc.returncode is None:
                pid = self.active_proc.pid
                try:
                    if os.name == "nt":
                        subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
                    else:
                        self.active_proc.kill()
                    self._write_log(f"[bold red]🛑 Process (PID: {pid}) sonlandırıldı.[/bold red]")
                except Exception as e:
                    self._write_log(f"[red]Process sonlandırılamadı: {escape(str(e))}[/red]")
                self.active_proc = None
                return

        # 2. If a non-agent process is already running, pipe input to its stdin
        if self.active_proc and self.active_proc.returncode is None:
            try:
                if self.active_proc.stdin and not self.active_proc.stdin.is_closing():
                    self.active_proc.stdin.write(cmd_str.encode("utf-8") + b"\n")
                    await self.active_proc.stdin.drain()
                    self._write_log(f"[dim yellow]→ [stdin]: {escape(cmd_str)}[/dim yellow]")
                    return
            except Exception as e:
                self._write_log(f"[dim red]Stdin iletilemedi: {escape(str(e))}[/dim red]")

        # 3. Built-in quick commands
        if cmd_lower in ("clear", "cls"):
            self.log_history.clear()
            try:
                self.query_one("#shell-stream", RichLog).clear()
            except Exception:
                pass
            return

        if cmd_lower in ("help", "?"):
            help_text = (
                "[bold cyan]Kullanılabilir Shell Komutları:[/bold cyan]\n"
                "• [yellow]Antigravity AI:[/yellow] 'agy' yazarak canlı AI agent başlatın (ara adımlar canlı akar).\n"
                "• [yellow]Herhangi Bir Sistem Komutu:[/yellow] python, dir, ping, git, npm, curl, echo...\n"
                "• [yellow]Harici Konsol:[/yellow] 'open <komut>' veya 'start <komut>' ile yeni Windows konsolunda açabilirsiniz.\n"
                "• [yellow]Fortress Komutları:[/yellow] @01 pause, @01 resume, banana, heal 01, export, detach\n"
                "• [yellow]Durdurma:[/yellow] Çalışan bir komutu 'stop' veya 'kill' yazarak sonlandırabilirsiniz.\n"
                "• [yellow]clear / cls:[/yellow] Ekranı temizler."
            )
            self._write_log(help_text)
            return

        # 4. Fortress direct commands
        tokens = cmd_str.split()
        first = tokens[0].lower()
        if tokens[0].startswith("@") or first in ("banana", "heal", "export", "detach", "spawn", "layout", "preset"):
            await self.event_bus.publish(
                Event(
                    type=EventType.COMMAND,
                    source="shell_pane",
                    data={"command": cmd_str},
                )
            )
            self._write_log(f"[dim green]✔ Fortress Core'a iletildi: {escape(cmd_str)}[/dim green]")
            return

        # 5. Harici Pencerede Başlatma
        if first in ("start", "open"):
            target_cmd = " ".join(tokens[1:]) or "cmd.exe"
            self.action_open_external_terminal(target_cmd)
            return

        # 6. Agy Komutu Tespiti: agy / agy.exe
        if first in ("agy", "agy.exe"):
            has_print = any(t in tokens for t in ("-p", "--print", "--prompt"))
            is_subcmd = any(t in tokens for t in ("--version", "-v", "--help", "-h", "update", "models", "agents", "help"))
            
            # Parametreleri ve prompt'u ayıkla
            remaining = tokens[1:]
            flags = [t for t in remaining if t.startswith("-") and not t.startswith("-p")]
            if "--dangerously-skip-permissions" not in flags:
                flags.append("--dangerously-skip-permissions")
            self.agy_flags = flags
            self.agy_mode = True
            self.switch_to_stream_view()
            if self.on_mode_change:
                self.on_mode_change("agy", "Antigravity'ye prompt yazın (Durdurmak için 'stop')...")

            # Eğer kullanıcı 'agy <mesaj>' şeklinde doğrudan prompt yazdıysa hemen çalıştır
            prompt_parts = []
            skip_next = False
            for t in remaining:
                if skip_next:
                    skip_next = False
                    continue
                if t in ("-p", "--print", "--prompt"):
                    skip_next = True
                    continue
                if not t.startswith("-"):
                    prompt_parts.append(t)

            if prompt_parts:
                immediate_prompt = " ".join(prompt_parts)
                await self._stream_agy_command(immediate_prompt)
                return

            banner = (
                f"\n[bold #00FF7F]🤖 ANTIGRAVITY AGENT CLI AKTİF[/bold #00FF7F] [dim](Canlı Filtresiz Akış Modu)[/dim]\n"
                f"[dim]• Parametreler: {escape(' '.join(self.agy_flags))}[/dim]\n"
                f"[cyan]• Mesaj veya görevinizi aşağıya yazıp Enter'a basın (ara adımlar ve araç çağrıları canlı akar).[/cyan]\n"
                f"[dim]• Çıkmak için: 'exit' veya 'stop' yazın.\n"
                f"• Harici tam TUI penceresinde açmak isterseniz: 'open agy' veya yukarıdaki butona tıklayın.[/dim]\n"
            )
            self._write_log(banner)
            return

        # 7. Doğrudan bu Bölmede (In-Pane) Canlı Akışlı Asenkron Çalıştırma
        try:
            term = self.query_one("#embedded-pty-terminal", EmbeddedTerminalWidget)
            if term and term.pty and term.pty.isalive() and not self.has_class("shell-stream-active"):
                term.write_command(cmd_str)
                return
        except Exception:
            pass

        run_cmd = cmd_str
        if first == "python" and len(tokens) == 1:
            run_cmd = "python -i -q"

        try:
            proc = await asyncio.create_subprocess_shell(
                run_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self.active_proc = proc
            self._write_log(f"[dim cyan]▶ Çalışıyor (PID: {proc.pid}) — Durdurmak için 'stop' yazabilirsiniz.[/dim cyan]")
            asyncio.create_task(self._stream_proc(proc, cmd_str))
        except Exception as e:
            self._write_log(f"[bold red]Process başlatılamadı:[/bold red] {escape(str(e))}")

    async def _stream_agy_command(self, prompt_text: str) -> None:
        """Executes agy with --output-format stream-json to capture and render every intermediate step live."""
        self.switch_to_stream_view()
        self._write_log(f"\n[bold #00FF7F]agy>[/bold #00FF7F] [white]{escape(prompt_text)}[/white]")
        self._write_log("[dim cyan]⚡ Antigravity çalışıyor (canlı ara adımlar aktarılıyor)...[/dim cyan]")

        agy_bin = shutil.which("agy") or "agy"
        cmd_args = [agy_bin] + self.agy_flags + ["-c", "-p", prompt_text, "--output-format", "stream-json"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self.active_proc = proc
            asyncio.create_task(self._process_agy_stream(proc, prompt_text))
        except Exception as e:
            self._write_log(f"[bold red]Antigravity başlatılamadı:[/bold red] {escape(str(e))}")

    async def _process_agy_stream(self, proc: asyncio.subprocess.Process, prompt_text: str) -> None:
        """Parses and renders live stream-json events from agy."""
        response_buffer = ""

        def flush_buffer():
            nonlocal response_buffer
            if response_buffer:
                buf = response_buffer
                response_buffer = ""
                self.app.call_later(self._write_log, Text.from_ansi(buf))

        async def read_stdout():
            nonlocal response_buffer
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                raw_text = line.decode("utf-8", errors="replace").strip()
                if not raw_text:
                    continue

                try:
                    data = json.loads(raw_text)
                except Exception:
                    flush_buffer()
                    self.app.call_later(self._write_log, Text.from_ansi(raw_text))
                    continue

                ev = data.get("event")
                if ev == "init":
                    flush_buffer()
                    init_data = data.get("init", {})
                    tools_count = len(init_data.get("tools", []))
                    self.app.call_later(
                        self._write_log,
                        f"[dim cyan]🚀 [OTURUM BAŞLADI] Aktif Araç Sayısı: {tools_count}[/dim cyan]"
                    )

                elif ev == "step_update":
                    su = data.get("step_update", {})
                    st = su.get("step_type")
                    state = su.get("state")
                    tool_name = su.get("tool_name")
                    tool_info = su.get("tool_info", {})
                    text_delta = su.get("text_delta")

                    if st == "tool":
                        flush_buffer()
                        if state == "ACTIVE":
                            params = tool_info.get("parameters", {})
                            summary_parts = []
                            for k, v in params.items():
                                val_s = str(v).replace("\n", " ")
                                if len(val_s) > 80:
                                    val_s = val_s[:77] + "..."
                                summary_parts.append(f"{k}={val_s}")
                            summary = " ".join(summary_parts)
                            self.app.call_later(
                                self._write_log,
                                f"[bold yellow]🔧 [ARA ADIM: {tool_name}][/bold yellow] [dim cyan]{escape(summary)}[/dim cyan]"
                            )
                        elif state == "DONE":
                            dur = su.get("duration_seconds", 0)
                            out = tool_info.get("output", "")
                            if out:
                                clean_out = str(out).strip()
                                lines = clean_out.splitlines()
                                if len(lines) > 12:
                                    lines = lines[:10] + [f"... (+{len(lines)-10} satır daha)"]
                                for l in lines:
                                    self.app.call_later(self._write_log, f"  [dim white]│ {escape(l)}[/dim white]")
                            self.app.call_later(
                                self._write_log,
                                f"  [dim green]✔ Araç tamamlandı ({dur:.2f}s)[/dim green]"
                            )

                    elif st == "agent_response":
                        if text_delta:
                            # Accumulate tokens and flush completed lines on newline so words aren't split
                            response_buffer += str(text_delta)
                            if "\n" in response_buffer:
                                parts = response_buffer.split("\n")
                                for completed in parts[:-1]:
                                    self.app.call_later(self._write_log, Text.from_ansi(completed))
                                response_buffer = parts[-1]

                elif ev == "result":
                    flush_buffer()
                    res = data.get("result", {})
                    dur = res.get("duration_seconds", 0)
                    usage = res.get("usage", {})
                    tokens = usage.get("total_tokens", 0)
                    status = res.get("status", "SUCCESS")
                    color = "green" if status == "SUCCESS" else "red"
                    self.app.call_later(
                        self._write_log,
                        f"[bold {color}]✔ Antigravity görevi tamamlandı[/bold {color}] [dim]({dur:.1f}s • {tokens} token)[/dim]\n"
                    )

            flush_buffer()

        async def read_stderr():
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self.app.call_later(self._write_log, f"[dim red][agy-stderr] {escape(text)}[/dim red]")

        try:
            await asyncio.gather(read_stdout(), read_stderr())
            await proc.wait()
        except asyncio.CancelledError:
            if self._is_closing and proc.returncode is None:
                proc.kill()
        finally:
            if proc.returncode is not None and self.active_proc == proc:
                self.active_proc = None

    async def _stream_proc(self, proc: asyncio.subprocess.Process, cmd_str: str) -> None:
        """Streams standard subprocess output with ANSI color support."""
        async def read_stream(stream, is_err: bool = False):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = ""
                for enc in ("utf-8", "cp1254", "cp857", "latin1"):
                    try:
                        text = line.decode(enc).rstrip("\r\n")
                        break
                    except Exception:
                        continue
                if not text:
                    text = line.decode("utf-8", errors="replace").rstrip("\r\n")

                if text:
                    ansi_text = Text.from_ansi(text)
                    if is_err:
                        err_prefix = Text("[ERR] ", style="bold red")
                        ansi_text = err_prefix + ansi_text
                    self.app.call_later(self._write_log, ansi_text)

        try:
            await asyncio.gather(
                read_stream(proc.stdout, is_err=False),
                read_stream(proc.stderr, is_err=True),
            )
            code = await proc.wait()
            if code == 0:
                self.app.call_later(self._write_log, f"[dim green]✔ Tamamlandı ({escape(cmd_str)})[/dim green]")
            else:
                self.app.call_later(self._write_log, f"[dim red]Process sonlandı: exit code {code}[/dim red]")
        except asyncio.CancelledError:
            if self._is_closing and proc.returncode is None:
                proc.kill()
        finally:
            if proc.returncode is not None and self.active_proc == proc:
                self.active_proc = None


