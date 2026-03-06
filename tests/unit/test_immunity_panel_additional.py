"""Additional tests for ImmunityPanel branch coverage."""

import tkinter as tk
from tkinter import ttk

import pytest

import app.ui.widgets.immunity_panel as immunity_module
from app.parser import LogParser
from app.storage import DataStore
from app.ui.widgets.immunity_panel import ImmunityPanel


@pytest.fixture
def panel_ctx(shared_tk_root):
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")
    notebook = ttk.Notebook(shared_tk_root)
    store = DataStore()
    parser = LogParser(parse_immunity=False)
    panel = ImmunityPanel(notebook, store, parser)
    return panel, store, parser


def _find_parse_checkbutton(panel: ImmunityPanel) -> ttk.Checkbutton:
    selector_frame = panel.winfo_children()[0]
    for widget in selector_frame.winfo_children():
        if isinstance(widget, ttk.Checkbutton):
            return widget
    raise AssertionError("Parse Immunities checkbutton not found")


def test_parse_immunity_toggle_updates_parser_and_refresh(panel_ctx) -> None:
    panel, _store, parser = panel_ctx
    check_btn = _find_parse_checkbutton(panel)

    called = {"count": 0}

    def fake_refresh_display() -> None:
        called["count"] += 1

    panel.refresh_display = fake_refresh_display  # type: ignore[assignment]

    # Simulate real user clicks: invoke() toggles the variable each time.
    assert panel.parse_immunity_var.get() is False
    check_btn.invoke()
    assert parser.parse_immunity is True
    assert called["count"] == 1

    check_btn.invoke()
    assert parser.parse_immunity is False
    assert called["count"] == 2


def test_combo_selection_event_triggers_target_refresh(panel_ctx) -> None:
    panel, store, _parser = panel_ctx
    store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
    panel.update_target_list(["Goblin"])

    called = {"target": None}

    def fake_refresh_target_details(target: str) -> None:
        called["target"] = target

    panel.refresh_target_details = fake_refresh_target_details  # type: ignore[assignment]
    panel.target_combo.set("Goblin")
    panel.target_combo.event_generate("<<ComboboxSelected>>")

    assert called["target"] == "Goblin"


def test_cached_immunity_percentage_none_displays_dash(panel_ctx, monkeypatch) -> None:
    panel, store, parser = panel_ctx
    parser.parse_immunity = True
    store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
    store.record_immunity("Goblin", "Fire", 10, 50)

    monkeypatch.setattr(immunity_module, "calculate_immunity_percentage", lambda *_args, **_kwargs: None)
    panel.refresh_target_details("Goblin")

    item_id = panel._item_ids["Fire"]
    values = panel.tree.item(item_id, "values")
    assert values[3] == "-"


def test_update_target_list_does_not_override_existing_selection(panel_ctx) -> None:
    panel, _store, _parser = panel_ctx
    panel.target_combo.set("Existing")
    panel.update_target_list(["Goblin", "Orc"])

    assert panel.target_combo.get() == "Existing"


def test_refresh_display_no_selected_target_is_noop(panel_ctx) -> None:
    panel, _store, _parser = panel_ctx
    panel.target_combo.set("")

    called = {"count": 0}

    def fake_refresh_target_details(_target: str) -> None:
        called["count"] += 1

    panel.refresh_target_details = fake_refresh_target_details  # type: ignore[assignment]
    panel.refresh_display()
    assert called["count"] == 0
