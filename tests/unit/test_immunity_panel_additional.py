"""Additional tests for ImmunityPanel branch coverage."""

import tkinter as tk
from tkinter import ttk

import pytest

import app.services.queries.immunity_query_service as immunity_query_module
from app.parser import ParserSession
from app.services.queries import ImmunityQueryService
from app.storage import DataStore
from app.ui.widgets.immunity_panel import ImmunityPanel
from tests.helpers.store_mutations import apply, damage_row, immunity


@pytest.fixture
def panel_ctx(shared_tk_root):
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")
    notebook = ttk.Notebook(shared_tk_root)
    store = DataStore()
    parser = ParserSession(parse_immunity=False)
    panel = ImmunityPanel(notebook, store, parser, ImmunityQueryService(store))
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


def test_parse_immunity_var_initializes_from_parser(shared_tk_root) -> None:
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    notebook = ttk.Notebook(shared_tk_root)
    store = DataStore()
    parser = ParserSession(parse_immunity=True)
    panel = ImmunityPanel(notebook, store, parser, ImmunityQueryService(store))

    assert panel.parse_immunity_var.get() is True


def test_parse_immunity_toggle_notifies_callback(panel_ctx) -> None:
    panel, _store, _parser = panel_ctx
    observed: list[bool] = []
    panel.on_parse_immunity_changed = observed.append
    check_btn = _find_parse_checkbutton(panel)

    check_btn.invoke()

    assert observed == [True]


def test_combo_selection_event_triggers_target_refresh(panel_ctx) -> None:
    panel, store, _parser = panel_ctx
    apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
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
    apply(
        store,
        damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
        immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50),
    )

    monkeypatch.setattr(
        immunity_query_module,
        "calculate_immunity_percentage",
        lambda *_args, **_kwargs: None,
    )
    panel.refresh_target_details("Goblin")

    item_id = panel._tree_refresh_state.item_ids["Fire"]
    values = panel.tree.item(item_id, "values")
    assert values[3] == "-"


def test_refresh_uses_best_effort_immunity_percentage_when_exact_match_missing(panel_ctx) -> None:
    panel, store, parser = panel_ctx
    parser.parse_immunity = True
    apply(
        store,
        damage_row(target="Goblin", damage_type="Physical", total_damage=146, attacker="Woo"),
        immunity(target="Goblin", damage_type="Physical", immunity_points=33, damage_dealt=146),
    )

    panel.refresh_target_details("Goblin")

    item_id = panel._tree_refresh_state.item_ids["Physical"]
    values = panel.tree.item(item_id, "values")
    assert values[3] == "18%"


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


def test_disclaimer_label_is_present_and_persistent(panel_ctx) -> None:
    panel, _store, parser = panel_ctx

    assert panel.disclaimer_label.cget("text") == ImmunityPanel.DISCLAIMER_TEXT
    assert panel.disclaimer_label.winfo_manager() == "pack"

    parser.parse_immunity = True
    panel.refresh_display()

    assert panel.disclaimer_label.cget("text") == ImmunityPanel.DISCLAIMER_TEXT


def test_disclaimer_label_is_below_tree(panel_ctx) -> None:
    panel, _store, _parser = panel_ctx

    children = panel.winfo_children()

    assert panel.disclaimer_label in children
    assert panel.tree.master in children
    assert children.index(panel.disclaimer_label) > children.index(panel.tree.master)
