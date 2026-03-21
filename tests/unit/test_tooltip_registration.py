"""Regression tests for tooltip registration wiring."""

from tkinter import ttk

import pytest

from app.services.queries import DpsQueryService, ImmunityQueryService, TargetSummaryQueryService
from app.storage import DataStore
from app.ui.widgets.debug_console_panel import DebugConsolePanel
from app.ui.widgets.death_snippet_panel import DeathSnippetPanel
from app.ui.widgets.dps_panel import DPSPanel
from app.ui.widgets.immunity_panel import ImmunityPanel


class _TooltipRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def register(self, widget, text: str, **_kwargs) -> None:
        self.calls.append(("one", id(widget), text))

    def register_many(self, widgets, text: str, **_kwargs) -> None:
        self.calls.append(("many", len(tuple(widgets)), text))


@pytest.fixture
def notebook(shared_tk_root):
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")
    nb = ttk.Notebook(shared_tk_root)
    nb.pack()
    yield nb
    try:
        nb.destroy()
    except Exception:
        pass


def test_dps_panel_registers_only_configured_widget_tooltips(notebook) -> None:
    recorder = _TooltipRecorder()
    store = DataStore()
    panel = DPSPanel(notebook, store, DpsQueryService(store), tooltip_manager=recorder)

    assert len(recorder.calls) == 2
    assert all("DPS" in call[2] or "target" in call[2].lower() for call in recorder.calls)

    before = list(recorder.calls)
    panel.refresh()
    assert recorder.calls == before


def test_immunity_panel_registers_two_tooltips(notebook) -> None:
    recorder = _TooltipRecorder()
    parser = type("ParserStub", (), {"parse_immunity": True})()
    store = DataStore()
    ImmunityPanel(
        notebook,
        store,
        parser,
        ImmunityQueryService(store),
        tooltip_manager=recorder,
    )

    assert len(recorder.calls) == 2


def test_death_and_debug_panels_register_expected_tooltips(notebook) -> None:
    recorder = _TooltipRecorder()

    DeathSnippetPanel(notebook, tooltip_manager=recorder)
    DebugConsolePanel(notebook, tooltip_manager=recorder)

    assert len(recorder.calls) == 7
