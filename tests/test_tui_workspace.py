import pytest
from pathlib import Path

from agentbus.tui.app import AgentBusTuiApp
from agentbus.tui.workspace import DynamicWorkspace
from agentbus.tui.cli_tile import CliTilePane
from agentbus.tui.drag_splitter import DragSplitter
from agentbus.tui.context_menu import NewWindowModal


@pytest.mark.asyncio
async def test_dynamic_workspace_presets_and_tiles(tmp_path):
    """Çoklu terminal çalışma alanının 3 sütunlu başlangıcını, ayraçları ve düzen şablonlarını test eder."""
    home = tmp_path / ".data"
    app = AgentBusTuiApp(home, periodic_sync=False)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.is_mounted

        ws = app.query_one(DynamicWorkspace)
        assert ws is not None
        assert len(ws._active_tiles) == 3

        # Ayraç kontrolü: 3 sütun arasında en az 2 adet ayraç bulunmalı
        splitters = ws.query(DragSplitter)
        assert len(splitters) >= 2

        # 1. 'fit_all' düzenini uygula
        await ws.apply_preset("fit_all")
        await pilot.pause()
        assert ws.current_preset == "fit_all"

        # 2. 'grid_2x2' düzenini uygula
        await ws.apply_preset("grid_2x2")
        await pilot.pause()
        assert ws.current_preset == "grid_2x2"
        assert len(ws._active_tiles) == 4

        # 3. Yeni bölme ekleme
        await ws.add_new_tile(cli_type="normal", initial_command="")
        await pilot.pause()
        assert len(ws._active_tiles) == 5

        # 4. Bölme kapatma
        first_tile_id = next(iter(ws._active_tiles.keys()))
        await ws.close_tile(first_tile_id)
        await pilot.pause()
        assert first_tile_id not in ws._active_tiles


@pytest.mark.asyncio
async def test_new_window_modal_choices(tmp_path):
    """Yeni pencere modalının açıldığını ve tuş kısayolu ile Codex seçilip kapandığını test eder."""
    home = tmp_path / ".data"
    app = AgentBusTuiApp(home, periodic_sync=False)

    async with app.run_test() as pilot:
        await pilot.pause()

        result_holder = []
        def _on_dismiss(res):
            result_holder.append(res)

        modal = NewWindowModal(default_target="internal")
        app.push_screen(modal, _on_dismiss)
        await pilot.pause()

        # Modal aktifken '1' (Codex) tuşuna bas
        modal.action_select_codex()
        await pilot.pause()

        assert len(result_holder) == 1
        assert result_holder[0]["cli_type"] == "codex"
        assert result_holder[0]["command"] == "codex"
        assert result_holder[0]["target"] == "internal"
