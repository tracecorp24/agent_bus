"""
Visual theme, color palettes, CSS definitions, and ASCII art
for Minion Fortress v3.0.
"""

from __future__ import annotations

# Minion Palette
BANANA_YELLOW = "#FFE135"
BANANA_GOLD = "#FFD700"
DARK_BG = "#121212"
PANEL_BG = "#1A1A1A"
BORDER_YELLOW = "#FFE135"
BORDER_GRAY = "#333333"
ERROR_RED = "#FF4444"
WARN_ORANGE = "#FFA500"
HEAL_GREEN = "#00FF7F"
INFO_CYAN = "#00E5FF"
TEXT_WHITE = "#EDEDED"
TEXT_MUTED = "#888888"

# ASCII Art Minion
MINION_ASCII_ACTIVE = """
  (o) > Task: {task}
 |█| > [PROGRESS] [{bar}] {progress}%
  / \\ > Status: {status} | CPU: {cpu}% | RAM: {mem}MB
"""

MINION_ASCII_BANANA = """
  (♥_♥) 🍌 BANANA! BANANA! BANANA! 🍌
   |█|  > EMERGENCY PANIC MODE ENGAGED <
   / \\  > ALL PROCESSORS SAFE-LOCKED <
"""

FORTRESS_CSS = f"""
Screen {{
    background: {DARK_BG};
    color: {TEXT_WHITE};
}}

Header {{
    dock: top;
    height: 1;
    background: #181818;
    color: {BANANA_YELLOW};
    text-style: bold;
}}

Footer {{
    dock: bottom;
    height: 1;
    background: #181818;
    color: {BANANA_YELLOW};
}}

#app-grid {{
    layout: horizontal;
    height: 1fr;
}}

#left-sidebar {{
    width: 38;
    border-right: heavy {BORDER_YELLOW};
    background: {PANEL_BG};
    padding: 0 1;
    overflow-y: auto;
}}

#sidebar-tabs-container {{
    height: auto;
    margin-bottom: 1;
    background: #141414;
    border: solid {BORDER_GRAY};
    padding: 0;
}}

.sidebar-tab-btn {{
    width: 100%;
    min-width: 100%;
    height: 1;
    margin: 0;
    background: #1E1E1E;
    color: #E0E0E0;
    border: none;
    text-align: left;
    padding-left: 1;
}}

.sidebar-tab-btn:hover {{
    background: {BANANA_YELLOW};
    color: #000000;
    text-style: bold;
}}

.sidebar-tab-active {{
    background: #00FF7F !important;
    color: #000000 !important;
    text-style: bold;
}}

#right-canvas {{
    width: 1fr;
    layout: vertical;
    padding: 0;
}}

.grid-row {{
    height: 1fr;
    layout: horizontal;
}}

.pane-container {{
    width: 1fr;
    height: 100%;
    border: heavy {BORDER_YELLOW};
    background: {PANEL_BG};
    margin: 0;
    padding: 0;
}}

.pane-title {{
    height: 1;
    background: {BANANA_YELLOW};
    color: #000000;
    text-style: bold;
    padding-left: 1;
}}

.error-title {{
    background: {ERROR_RED};
    color: #FFFFFF;
}}

.sniper-title {{
    background: {BANANA_GOLD};
    color: #000000;
}}

.plugin-title {{
    background: #9D00FF;
    color: #FFFFFF;
}}

.log-stream {{
    height: 1fr;
    background: #0D0D0D;
    color: #C0C0C0;
    padding: 0 1;
    scrollbar-color: {BANANA_YELLOW} #222222;
    overflow-x: hidden;
}}

RichLog {{
    overflow-x: hidden;
}}

#repl-container {{
    dock: bottom;
    height: 3;
    border-top: heavy {BORDER_YELLOW};
    background: #181818;
    padding: 0 1;
}}

#repl-input {{
    background: #0F0F0F;
    border: none;
    height: 1;
    color: {BANANA_YELLOW};
}}

.telemetry-card {{
    background: #202020;
    border: solid {BORDER_GRAY};
    padding: 1;
    margin-bottom: 1;
}}

.section-header {{
    text-style: bold;
    color: {BANANA_YELLOW};
    margin-top: 1;
    margin-bottom: 0;
}}

.minion-avatar-box {{
    background: #141414;
    border: solid #444444;
    color: {BANANA_YELLOW};
    padding: 0 1;
    margin-bottom: 1;
}}

.action-bar {{
    layout: horizontal;
    height: 3;
    padding: 0 1;
    background: #181818;
    align: center middle;
}}

.shell-action-bar {{
    layout: horizontal;
    height: 1;
    min-height: 1;
    background: #181818;
    padding: 0 1;
    margin: 0;
}}

.shell-status-label {{
    width: 1fr;
    height: 1;
    color: #FFE135;
    text-style: bold;
}}

.shell-hdr-btn {{
    width: auto;
    min-width: 8;
    height: 1;
    margin: 0 0 0 1;
    padding: 0 1;
    background: #252525;
    color: #00FF7F;
    border: none;
}}

.shell-hdr-btn:hover {{
    background: #00FF7F;
    color: #000000;
    text-style: bold;
}}

#shell-view-container {{
    height: 1fr;
    width: 100%;
    padding: 0;
    margin: 0;
}}

#embedded-pty-terminal {{
    height: 1fr;
    width: 100%;
    display: block;
}}

.shell-stream-active #embedded-pty-terminal {{
    display: none;
}}

.shell-stream-active #shell-stream {{
    display: block;
}}

#shell-stream {{
    height: 1fr;
    width: 100%;
    display: none;
}}

Button {{
    background: #2A2A2A;
    color: {BANANA_YELLOW};
    border: solid {BORDER_YELLOW};
    min-width: 12;
    margin-right: 1;
}}

Button:hover {{
    background: {BANANA_YELLOW};
    color: #000000;
}}

Button.active-btn {{
    background: {HEAL_GREEN};
    color: #000000;
}}

Button.paused-btn {{
    background: #444444;
    color: #AAAAAA;
}}

/* Dynamic Workspace and Tiling Styles */
#workspace-canvas {{
    width: 100%;
    height: 1fr;
    padding: 0;
    margin: 0;
    overflow: hidden;
}}

.split-col {{
    layout: horizontal;
    height: 1fr;
    width: 100%;
    overflow: hidden;
}}

.split-row {{
    layout: vertical;
    height: 1fr;
    width: 100%;
    overflow: hidden;
}}

Horizontal > .split-row {{
    width: 1fr !important;
    height: 100% !important;
}}

Vertical > .split-col {{
    height: 1fr !important;
    width: 100% !important;
}}

Horizontal > CliTilePane {{
    width: 1fr !important;
    height: 100% !important;
}}

Vertical > CliTilePane {{
    height: 1fr !important;
    width: 100% !important;
}}

#preset-toolbar {{
    height: 3;
    background: #141414;
    border-bottom: heavy {BORDER_YELLOW};
    padding: 0 1;
    layout: horizontal;
}}

.preset-label {{
    width: auto;
    color: {BANANA_YELLOW};
    text-style: bold;
    content-align: center middle;
    padding-right: 1;
}}

.preset-btn {{
    width: auto;
    min-width: 9;
    height: 1;
    margin: 0 1 0 0;
    background: #252525;
    color: #E0E0E0;
    border: none;
}}

.preset-btn:hover {{
    background: {BANANA_YELLOW};
    color: #000000;
    text-style: bold;
}}

.preset-btn-active {{
    background: {HEAL_GREEN};
    color: #000000;
    text-style: bold;
}}

CliTilePane {{
    border: heavy {BORDER_YELLOW};
    background: {PANEL_BG};
    height: 1fr;
    width: 1fr;
    min-width: 12;
    min-height: 5;
    margin: 0;
    padding: 0;
    overflow: hidden;
}}

CliTilePane:focus-within {{
    border: heavy {HEAL_GREEN};
}}

.tile-header-bar {{
    height: 1;
    background: #202020;
    padding: 0 1;
    layout: horizontal;
}}

.tile-title-text {{
    width: 1fr;
    height: 1;
    color: {BANANA_YELLOW};
    text-style: bold;
    overflow-x: hidden;
    text-overflow: ellipsis;
}}

.tile-actions-strip {{
    width: auto;
    layout: horizontal;
}}

.tile-hdr-btn {{
    width: 4;
    min-width: 4;
    height: 1;
    padding: 0;
    margin: 0 0 0 1;
    background: #333333;
    color: #FFFFFF;
    border: none;
}}

.tile-hdr-btn:hover {{
    background: {BANANA_YELLOW};
    color: #000000;
    text-style: bold;
}}

.tile-hdr-btn-danger:hover {{
    background: {ERROR_RED};
    color: #FFFFFF;
}}

.tile-inner-container {{
    height: 1fr;
    width: 100%;
    padding: 0;
    margin: 0;
    overflow: hidden;
}}

.tile-input-container {{
    dock: bottom;
    height: 3;
    min-height: 3;
    max-height: 3;
    background: #141414;
    border-top: heavy {BANANA_YELLOW};
    padding: 0 1;
    layout: horizontal;
}}

CliTilePane:focus-within .tile-input-container {{
    border-top: heavy {HEAL_GREEN};
    background: #181818;
}}

.tile-prompt-tag {{
    width: auto;
    height: 1;
    color: {HEAL_GREEN};
    text-style: bold;
    content-align: center middle;
    padding-right: 1;
}}

.tile-cli-input {{
    width: 1fr;
    height: 1;
    background: #0A0A0A;
    border: none;
    padding: 0;
    color: #FFFFFF;
}}

.tile-cli-input:focus {{
    background: #000000;
    color: {BANANA_YELLOW};
}}

CliTilePane .pane-container {{
    border: none !important;
    margin: 0 !important;
    padding: 0 !important;
    height: 1fr !important;
    width: 100% !important;
}}

CliTilePane .pane-title {{
    display: none !important;
}}

CliTilePane .minion-avatar-box {{
    border: none !important;
    padding: 0 1 !important;
    margin: 0 !important;
    height: auto !important;
    max-height: 2 !important;
    background: #141414 !important;
    color: {BANANA_YELLOW} !important;
}}

CliTilePane .action-bar {{
    height: 1 !important;
    padding: 0 1 !important;
    margin: 0 !important;
    background: #181818 !important;
}}

CliTilePane .action-bar Button {{
    height: 1 !important;
    min-width: 5 !important;
    border: none !important;
    padding: 0 !important;
    margin-right: 1 !important;
}}

CliTilePane .log-stream {{
    height: 1fr !important;
    min-height: 2 !important;
}}

CliTilePane #sniper-regex-input {{
    height: 1 !important;
    border: none !important;
    padding: 0 1 !important;
}}

CliTilePane #sniper-status-bar {{
    height: 1 !important;
    padding: 0 1 !important;
}}

CliTilePane #error-telemetry-badge {{
    height: 1 !important;
    padding: 0 1 !important;
}}

DragSplitter {{
    background: #222222;
    color: {BANANA_YELLOW};
    text-align: center;
    content-align: center middle;
}}

DragSplitter:hover {{
    background: {HEAL_GREEN};
    color: #000000;
}}

DragSplitter.active-drag {{
    background: {BANANA_YELLOW};
    color: #000000;
}}

.splitter-h {{
    width: 1;
    height: 100%;
}}

.splitter-v {{
    height: 1;
    width: 100%;
}}

.shell-container {{
    height: 100%;
    width: 100%;
}}

.shell-title {{
    background: {INFO_CYAN};
    color: #000000;
}}

/* Sidebar Watchdog & Live Log Sniper Collapsible Styling */
#left-sidebar Collapsible {{
    background: #151515;
    border-top: solid {BORDER_GRAY};
    border-bottom: solid {BORDER_GRAY};
    margin-top: 1;
    margin-bottom: 1;
    padding: 0;
}}

#left-sidebar Collapsible:focus-within {{
    border-top: solid #00FF7F;
    border-bottom: solid #00FF7F;
}}

#left-sidebar .pane-container {{
    border: none !important;
    background: transparent !important;
    padding: 0 !important;
    height: auto !important;
    max-height: 14 !important;
}}

#left-sidebar .pane-title {{
    display: none !important;
}}

#left-sidebar .log-stream {{
    height: 8 !important;
    min-height: 5 !important;
    max-height: 12 !important;
}}

#left-sidebar #error-telemetry-badge {{
    height: 1 !important;
    padding: 0 1 !important;
    color: #00FF7F;
}}

#left-sidebar #sniper-regex-input {{
    height: 1 !important;
    border: none !important;
    padding: 0 1 !important;
    background: #0A0A0A;
}}

#left-sidebar #sniper-status-bar {{
    height: 1 !important;
    padding: 0 1 !important;
    color: {BANANA_GOLD};
}}

#minion-roster-table {{
    height: auto;
    max-height: 9;
    border: solid {BORDER_GRAY};
    background: #0E0E0E;
    margin-bottom: 1;
}}

#minion-roster-table:focus {{
    border: solid #00FF7F;
}}

#minion-roster-table > .datatable--cursor {{
    background: #252525;
    color: #00FF7F;
    text-style: bold;
}}
"""
