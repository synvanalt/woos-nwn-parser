"""Edge-case tests for ImmunityPanel internal refresh paths."""

from unittest.mock import Mock

import pytest
from tkinter import ttk

from app.parser import ParserSession
from app.services.queries import ImmunityQueryService
from app.storage import DataStore
from app.ui.widgets.immunity_panel import ImmunityPanel
from tests.helpers.store_mutations import apply, damage_row, immunity


@pytest.fixture
def immunity_panel_ctx(shared_tk_root):
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    notebook = ttk.Notebook(shared_tk_root)
    store = DataStore()
    parser = ParserSession(parse_immunity=False)
    panel = ImmunityPanel(notebook, store, parser, ImmunityQueryService(store))
    return panel, store, parser


def test_get_selected_target_returns_combobox_value(immunity_panel_ctx) -> None:
    panel, _store, _parser = immunity_panel_ctx
    panel.target_combo.set("Goblin")
    assert panel.get_selected_target() == "Goblin"


def test_clear_cache_resets_internal_structures(immunity_panel_ctx) -> None:
    panel, _store, _parser = immunity_panel_ctx
    panel.immunity_pct_cache["Goblin"] = {"Fire": 50}
    panel._cached_target = "Goblin"
    panel._cached_rows = {"Fire": ("Fire", "10", "5", "50%", "1")}
    panel._item_ids = {"Fire": "iid1"}
    panel._cached_row_tokens = {"Fire": ("Fire", "10", "5", "50%", "1")}
    panel._cached_order_token = ("Fire",)
    panel._cached_view_key = ("Goblin", False)
    panel._last_refresh_version = 3

    panel.clear_cache()

    assert panel.immunity_pct_cache == {}
    assert panel._cached_target == ""
    assert panel._cached_rows == {}
    assert panel._item_ids == {}
    assert panel._cached_row_tokens == {}
    assert panel._cached_order_token == ()
    assert panel._cached_view_key == ("", False)
    assert panel._last_refresh_version == -1


def test_refresh_uses_cached_immunity_pct_when_parse_disabled(immunity_panel_ctx) -> None:
    panel, store, parser = immunity_panel_ctx
    target = "Goblin"
    parser.parse_immunity = False
    panel.immunity_pct_cache[target] = {"Fire": 60}
    apply(store, damage_row(target=target, damage_type="Fire", immunity_absorbed=10, total_damage=50, attacker="Woo"))

    panel.refresh_target_details(target)

    row = panel.tree.item(panel._item_ids["Fire"], "values")
    assert row[3] == "60%"


def test_incremental_refresh_applies_sort_when_non_damage_column_sorted(immunity_panel_ctx) -> None:
    panel, store, _parser = immunity_panel_ctx
    apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
    panel.refresh_target_details("Goblin")
    panel.tree._last_sorted_col = "Absorbed"
    panel.tree.apply_current_sort = Mock()

    apply(store, damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=10, total_damage=50, attacker="Woo"))
    panel.refresh_target_details("Goblin")

    panel.tree.apply_current_sort.assert_called_once()


def test_incremental_refresh_applies_sort_when_damage_type_descending(immunity_panel_ctx) -> None:
    panel, store, _parser = immunity_panel_ctx
    apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
    panel.refresh_target_details("Goblin")
    panel.tree._last_sorted_col = "Damage Type"
    panel.tree._sort_reverse = True
    panel.tree.apply_current_sort = Mock()

    apply(store, damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=10, total_damage=50, attacker="Woo"))
    panel.refresh_target_details("Goblin")

    panel.tree.apply_current_sort.assert_called_once()


def test_refresh_shows_zero_damage_immunity_match(immunity_panel_ctx) -> None:
    panel, store, parser = immunity_panel_ctx
    parser.parse_immunity = True
    apply(
        store,
        damage_row(target="DRAMMAGAR", damage_type="Acid", total_damage=0, attacker="Woo"),
        immunity(target="DRAMMAGAR", damage_type="Acid", immunity_points=50, damage_dealt=0),
    )

    panel.refresh_target_details("DRAMMAGAR")

    row = panel.tree.item(panel._item_ids["Acid"], "values")
    assert row == ("Acid", "0", "50", "100%", "1")


def test_refresh_shows_highest_absorbed_for_zero_damage_tie(immunity_panel_ctx) -> None:
    panel, store, parser = immunity_panel_ctx
    parser.parse_immunity = True
    apply(
        store,
        damage_row(target="DRAMMAGAR", damage_type="Acid", total_damage=0, attacker="Woo"),
        immunity(target="DRAMMAGAR", damage_type="Acid", immunity_points=50, damage_dealt=0),
        immunity(target="DRAMMAGAR", damage_type="Acid", immunity_points=55, damage_dealt=0),
    )

    panel.refresh_target_details("DRAMMAGAR")

    row = panel.tree.item(panel._item_ids["Acid"], "values")
    assert row == ("Acid", "0", "55", "100%", "2")


def test_refresh_suppresses_temporary_full_immunity_after_later_positive_damage(
    immunity_panel_ctx,
) -> None:
    panel, store, parser = immunity_panel_ctx
    parser.parse_immunity = True
    apply(
        store,
        damage_row(target="DRAMMAGAR", damage_type="Acid", total_damage=45, attacker="Woo"),
        immunity(target="DRAMMAGAR", damage_type="Acid", immunity_points=50, damage_dealt=0),
    )

    panel.refresh_target_details("DRAMMAGAR")

    row = panel.tree.item(panel._item_ids["Acid"], "values")
    assert row == ("Acid", "45", "-", "-", "1")


def test_full_refresh_restores_selection_for_surviving_damage_type(immunity_panel_ctx) -> None:
    panel, store, _parser = immunity_panel_ctx
    target = "Goblin"
    apply(
        store,
        damage_row(target=target, damage_type="Fire", total_damage=50, attacker="Woo"),
        damage_row(target=target, damage_type="Cold", total_damage=30, attacker="Woo"),
    )
    panel.refresh_target_details(target)

    fire_id = panel._item_ids["Fire"]
    panel.tree.selection_set((fire_id,))

    apply(store, damage_row(target=target, damage_type="Acid", total_damage=20, attacker="Woo"))
    panel.refresh_target_details(target)

    selected_items = panel.tree.selection()
    selected_damage_types = {panel.tree.item(item, "values")[0] for item in selected_items}
    assert "Fire" in selected_damage_types
