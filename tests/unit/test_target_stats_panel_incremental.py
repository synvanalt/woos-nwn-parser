"""Unit tests for TargetStatsPanel incremental refresh behavior."""

import pytest
import tkinter as tk
from tkinter import ttk
from unittest.mock import Mock

from app.parser import LogParser
from app.storage import DataStore
from app.ui.widgets.target_stats_panel import TargetStatsPanel
from tests.helpers.store_mutations import apply, damage_row


@pytest.fixture
def target_stats_panel(shared_tk_root):
    """Create a target stats panel for testing."""
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    notebook = ttk.Notebook(shared_tk_root)
    store = DataStore()
    parser = LogParser()
    panel = TargetStatsPanel(notebook, store, parser)
    return panel, store, parser


class TestTargetStatsIncrementalRefresh:
    """Test suite for incremental row updates in target stats panel."""

    def test_refresh_populates_cache(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))

        panel.refresh()

        assert "Goblin" in panel._cached_rows
        assert "Goblin" in panel._item_ids

    def test_incremental_refresh_updates_existing_row(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh()

        item_id = panel._item_ids["Goblin"]
        before = panel.tree.item(item_id, "values")

        apply(store, damage_row(target="Goblin", damage_type="Cold", total_damage=25, attacker="Woo"))
        panel.refresh()

        after = panel.tree.item(item_id, "values")
        assert before != after
        assert item_id == panel._item_ids["Goblin"]

    def test_refresh_skips_noop_when_store_version_unchanged(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh()

        panel._can_use_store_version_fast_path = Mock(return_value=True)  # type: ignore[method-assign]
        panel.data_store.get_all_targets_summary = Mock(  # type: ignore[assignment]
            side_effect=AssertionError("should not be called")
        )
        panel.refresh()

    def test_full_refresh_when_target_set_changes(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh()

        initial_item_id = panel._item_ids["Goblin"]

        apply(store, damage_row(target="Orc", damage_type="Cold", total_damage=25, attacker="Woo"))
        panel.refresh()

        assert "Orc" in panel._item_ids
        assert panel._item_ids["Goblin"] != initial_item_id

    def test_incremental_refresh_reorders_natural_target_order_without_rebuild(self, target_stats_panel) -> None:
        panel, _store, _ = target_stats_panel
        initial_summary = [
            {"target": "Goblin", "ab": "-", "ac": "-", "fortitude": "-", "reflex": "-", "will": "-", "damage_taken": "50"},
            {"target": "Orc", "ab": "-", "ac": "-", "fortitude": "-", "reflex": "-", "will": "-", "damage_taken": "25"},
        ]
        reordered_summary = [
            {"target": "Orc", "ab": "-", "ac": "-", "fortitude": "-", "reflex": "-", "will": "-", "damage_taken": "25"},
            {"target": "Goblin", "ab": "-", "ac": "-", "fortitude": "-", "reflex": "-", "will": "-", "damage_taken": "50"},
        ]

        panel.data_store.get_all_targets_summary = lambda: initial_summary  # type: ignore[assignment]
        panel.refresh()
        initial_item_ids = dict(panel._item_ids)

        panel.data_store.get_all_targets_summary = lambda: reordered_summary  # type: ignore[assignment]
        panel.refresh()

        ordered_targets = [
            panel.tree.item(item_id, "values")[0]
            for item_id in panel.tree.get_children()
        ]
        assert ordered_targets == ["Orc", "Goblin"]
        assert panel._item_ids == initial_item_ids

    def test_clear_cache_resets_all_cached_state(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh()

        panel.clear_cache()

        assert panel._cached_rows == {}
        assert panel._item_ids == {}
        assert panel._cached_row_tokens == {}
        assert panel._cached_order_token == ()
        assert panel._last_refresh_version == -1

    def test_refresh_falls_back_to_full_rebuild_when_cached_item_is_stale(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh()

        stale_item_id = panel._item_ids["Goblin"]
        panel.tree.delete(*panel.tree.get_children())

        apply(store, damage_row(target="Goblin", damage_type="Cold", total_damage=25, attacker="Woo"))
        panel.refresh()

        assert panel.tree.get_children()
        assert panel._item_ids["Goblin"] != stale_item_id
        values = panel.tree.item(panel._item_ids["Goblin"], "values")
        assert values[0] == "Goblin"

    def test_refresh_handles_missing_tree_item_without_tclerror(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh()

        item_id = panel._item_ids["Goblin"]
        panel.tree.delete(item_id)

        apply(store, damage_row(target="Goblin", damage_type="Cold", total_damage=25, attacker="Woo"))

        try:
            panel.refresh()
        except tk.TclError as exc:  # pragma: no cover - regression guard
            pytest.fail(f"refresh should recover from stale tree item ids, got {exc}")

    def test_refresh_uses_case_insensitive_default_target_order(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(
            store,
            damage_row(target="zombie", damage_type="Fire", total_damage=50, attacker="Woo"),
            damage_row(target="TYRMON risen", damage_type="Cold", total_damage=40, attacker="Rogue"),
            damage_row(target="Tyrmon scout", damage_type="Physical", total_damage=30, attacker="Woo"),
        )

        panel.refresh()

        ordered_targets = [
            panel.tree.item(item_id, "values")[0]
            for item_id in panel.tree.get_children()
        ]
        assert ordered_targets == ["TYRMON risen", "Tyrmon scout", "zombie"]
