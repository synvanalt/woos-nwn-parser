"""Unit tests for ImmunityPanel incremental refresh behavior."""

import pytest
from tkinter import ttk

from app.parser import LogParser
from app.storage import DataStore
from app.ui.widgets.immunity_panel import ImmunityPanel


@pytest.fixture
def immunity_panel(shared_tk_root):
    """Create an immunity panel for testing."""
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    notebook = ttk.Notebook(shared_tk_root)
    store = DataStore()
    parser = LogParser()
    panel = ImmunityPanel(notebook, store, parser)
    return panel, store, parser


class TestImmunityPanelIncrementalRefresh:
    """Test suite for incremental immunity row updates."""

    def test_refresh_populates_cache(self, immunity_panel) -> None:
        panel, store, _ = immunity_panel
        store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")

        panel.refresh_target_details("Goblin")

        assert panel._cached_target == "Goblin"
        assert "Fire" in panel._cached_rows
        assert "Fire" in panel._item_ids

    def test_incremental_refresh_updates_existing_row(self, immunity_panel) -> None:
        panel, store, _ = immunity_panel
        store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
        panel.refresh_target_details("Goblin")

        item_id = panel._item_ids["Fire"]
        before = panel.tree.item(item_id, "values")

        store.insert_damage_event("Goblin", "Fire", 0, 75, "Woo")
        panel.refresh_target_details("Goblin")

        after = panel.tree.item(item_id, "values")
        assert before != after
        assert panel._item_ids["Fire"] == item_id

    def test_full_refresh_when_damage_type_set_changes(self, immunity_panel) -> None:
        panel, store, _ = immunity_panel
        store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
        panel.refresh_target_details("Goblin")

        initial_item_id = panel._item_ids["Fire"]

        store.insert_damage_event("Goblin", "Cold", 0, 20, "Woo")
        panel.refresh_target_details("Goblin")

        assert "Cold" in panel._item_ids
        assert panel._item_ids["Fire"] != initial_item_id
