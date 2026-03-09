"""Unit tests for TargetStatsPanel incremental refresh behavior."""

import pytest
from tkinter import ttk

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

    def test_full_refresh_when_target_set_changes(self, target_stats_panel) -> None:
        panel, store, _ = target_stats_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh()

        initial_item_id = panel._item_ids["Goblin"]

        apply(store, damage_row(target="Orc", damage_type="Cold", total_damage=25, attacker="Woo"))
        panel.refresh()

        assert "Orc" in panel._item_ids
        assert panel._item_ids["Goblin"] != initial_item_id
