"""Unit tests for ImmunityPanel incremental refresh behavior."""

import pytest
from tkinter import ttk
from unittest.mock import Mock

from app.parser import ParserSession
from app.services.queries import ImmunityQueryService, ImmunitySummaryRow
from app.storage import DataStore
from app.ui.widgets.immunity_panel import ImmunityPanel
from tests.helpers.store_mutations import apply, damage_row


@pytest.fixture
def immunity_panel(shared_tk_root):
    """Create an immunity panel for testing."""
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    notebook = ttk.Notebook(shared_tk_root)
    store = DataStore()
    parser = ParserSession()
    query_service = ImmunityQueryService(store)
    panel = ImmunityPanel(notebook, store, parser, query_service)
    return panel, store, query_service


class TestImmunityPanelIncrementalRefresh:
    """Test suite for incremental immunity row updates."""

    def test_refresh_populates_cache(self, immunity_panel) -> None:
        panel, store, _ = immunity_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))

        panel.refresh_target_details("Goblin")

        assert panel._tree_refresh_state.view_key == ("Goblin", bool(panel.parser.parse_immunity))
        assert "Fire" in panel._tree_refresh_state.row_tokens
        assert "Fire" in panel._tree_refresh_state.item_ids

    def test_incremental_refresh_updates_existing_row(self, immunity_panel) -> None:
        panel, store, _ = immunity_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh_target_details("Goblin")

        item_id = panel._tree_refresh_state.item_ids["Fire"]
        before = panel.tree.item(item_id, "values")

        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=75, attacker="Woo"))
        panel.refresh_target_details("Goblin")

        after = panel.tree.item(item_id, "values")
        assert before != after
        assert panel._tree_refresh_state.item_ids["Fire"] == item_id

    def test_refresh_skips_noop_when_store_version_and_view_unchanged(self, immunity_panel) -> None:
        panel, store, _ = immunity_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh_target_details("Goblin")

        panel.immunity_query_service.get_target_damage_type_summary = Mock(  # type: ignore[assignment]
            side_effect=AssertionError("should not be called")
        )
        panel.refresh_target_details("Goblin")

    def test_refresh_noop_does_not_reapply_sort(self, immunity_panel) -> None:
        panel, store, _ = immunity_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh_target_details("Goblin")
        panel.tree.sort_column("Absorbed", reverse=True)
        panel.tree.apply_current_sort = Mock()

        panel.refresh_target_details("Goblin")

        panel.tree.apply_current_sort.assert_not_called()

    def test_full_refresh_when_damage_type_set_changes(self, immunity_panel) -> None:
        panel, store, _ = immunity_panel
        apply(store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        panel.refresh_target_details("Goblin")

        initial_item_id = panel._tree_refresh_state.item_ids["Fire"]

        apply(store, damage_row(target="Goblin", damage_type="Cold", total_damage=20, attacker="Woo"))
        panel.refresh_target_details("Goblin")

        assert "Cold" in panel._tree_refresh_state.item_ids
        assert panel._tree_refresh_state.item_ids["Fire"] != initial_item_id

    def test_incremental_refresh_reorders_natural_damage_type_order_without_rebuild(self, immunity_panel) -> None:
        panel, _store, _ = immunity_panel
        initial_summary = [
            ImmunitySummaryRow("Fire", 50, 0, 0, 0, False),
            ImmunitySummaryRow("Cold", 20, 0, 0, 0, False),
        ]
        reordered_summary = [
            ImmunitySummaryRow("Cold", 20, 0, 0, 0, False),
            ImmunitySummaryRow("Fire", 50, 0, 0, 0, False),
        ]

        panel.immunity_query_service.get_target_damage_type_summary = lambda _target: initial_summary  # type: ignore[assignment]
        panel.refresh_target_details("Goblin")
        initial_item_ids = dict(panel._tree_refresh_state.item_ids)

        panel.immunity_query_service.get_target_damage_type_summary = lambda _target: reordered_summary  # type: ignore[assignment]
        panel.refresh_target_details("Goblin")

        ordered_damage_types = [
            panel.tree.item(item_id, "values")[0]
            for item_id in panel.tree.get_children()
        ]
        assert ordered_damage_types == ["Cold", "Fire"]
        assert panel._tree_refresh_state.item_ids == initial_item_ids
