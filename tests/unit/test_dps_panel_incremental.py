"""Unit tests for DPS panel incremental refresh optimization.

Tests the new incremental tree update logic that avoids full rebuilds.
"""

import pytest
import tkinter as tk
from tkinter import ttk
from collections.abc import Iterator
from unittest.mock import Mock

from app.services.queries import DpsBreakdownRow, DpsRow
from app.ui.widgets.dps_panel import DPSPanel
from app.storage import DataStore
from app.services.queries import DpsQueryService
from tests.helpers.store_mutations import apply, attack


@pytest.fixture
def notebook(shared_tk_root):
    """Create a notebook for the panel using the shared Tk root."""
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    nb = ttk.Notebook(shared_tk_root)
    yield nb
    # Cleanup widgets after each test
    try:
        for child in nb.winfo_children():
            child.destroy()
        nb.destroy()
    except:
        pass


@pytest.fixture
def dps_panel(notebook):
    """Create a DPS panel for testing."""
    store = DataStore()
    service = DpsQueryService(store)
    panel = DPSPanel(notebook, store, service)
    return panel


class TestIncrementalRefresh:
    """Test suite for incremental refresh optimization."""

    def test_cache_initialized_empty(self, dps_panel) -> None:
        """Test that cache structures are initialized empty."""
        assert len(dps_panel._cached_data) == 0
        assert len(dps_panel._cached_breakdown) == 0
        assert len(dps_panel._tree_refresh_state.item_ids) == 0
        assert len(dps_panel._child_ids) == 0

    def test_full_refresh_on_first_call(self, dps_panel) -> None:
        """Test that first refresh triggers full rebuild."""
        # Mock the service to return data
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(
                character='Woo',
                total_damage=500,
                time_seconds=10,
                dps=50.0,
                hit_rate=75.0,
                breakdown_token=(('Physical', 500),),
            )
        ])

        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [
                DpsBreakdownRow(damage_type='Physical', total_damage=300, dps=30.0),
                DpsBreakdownRow(damage_type='Fire', total_damage=200, dps=20.0),
            ]
        })

        # First refresh should populate cache
        dps_panel.refresh()

        # Cache should now be populated
        assert 'Woo' in dps_panel._cached_data
        assert 'Woo' in dps_panel._cached_breakdown
        assert 'Woo' in dps_panel._tree_refresh_state.item_ids

        # Tree should have items
        children = dps_panel.tree.get_children()
        assert len(children) == 1

    def test_incremental_refresh_when_values_change(self, dps_panel) -> None:
        """Test that incremental refresh updates only changed values."""
        # Initial data
        initial_data = [
            DpsRow(
                character='Woo',
                total_damage=500,
                time_seconds=10,
                dps=50.0,
                hit_rate=75.0,
                breakdown_token=(),
            )
        ]

        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=initial_data)
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [DpsBreakdownRow(damage_type='Physical', total_damage=500, dps=50.0)]
        })

        # First refresh
        dps_panel.refresh()
        initial_tree_size = len(dps_panel.tree.get_children())

        # Update data (damage increased)
        updated_data = [
            DpsRow(
                character='Woo',
                total_damage=600,
                time_seconds=10,
                dps=60.0,
                hit_rate=75.0,
                breakdown_token=(),
            )
        ]

        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=updated_data)
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [DpsBreakdownRow(damage_type='Physical', total_damage=600, dps=60.0)]
        })

        # Second refresh should use incremental update
        dps_panel.refresh()

        # Tree structure should remain the same
        assert len(dps_panel.tree.get_children()) == initial_tree_size

        # Cache should be updated
        assert dps_panel._cached_data['Woo']['total_damage'] == 600
        assert dps_panel._cached_data['Woo']['dps'] == 60.0

    def test_full_refresh_when_characters_added(self, dps_panel) -> None:
        """Test that full refresh occurs when new characters appear."""
        # Initial data - one character
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=())
        ])
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={})

        # First refresh
        dps_panel.refresh()
        assert len(dps_panel._cached_data) == 1

        # Add second character
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=()),
            DpsRow(character='Ally', total_damage=300, time_seconds=10, dps=30.0, hit_rate=80.0, breakdown_token=()),
        ])

        # Second refresh should trigger full rebuild
        dps_panel.refresh()

        # Cache should have both characters
        assert len(dps_panel._cached_data) == 2
        assert 'Woo' in dps_panel._cached_data
        assert 'Ally' in dps_panel._cached_data

    def test_full_refresh_when_characters_removed(self, dps_panel) -> None:
        """Test that full refresh occurs when characters are removed."""
        # Initial data - two characters
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=()),
            DpsRow(character='Ally', total_damage=300, time_seconds=10, dps=30.0, hit_rate=80.0, breakdown_token=()),
        ])
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={})

        # First refresh
        dps_panel.refresh()
        assert len(dps_panel._cached_data) == 2

        # Remove one character
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=())
        ])

        # Second refresh should trigger full rebuild
        dps_panel.refresh()

        # Cache should only have Woo
        assert len(dps_panel._cached_data) == 1
        assert 'Woo' in dps_panel._cached_data
        assert 'Ally' not in dps_panel._cached_data

    def test_incremental_refresh_damage_type_added(self, dps_panel) -> None:
        """Test handling when new damage type is added."""
        # Initial data - one damage type
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=())
        ])
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [DpsBreakdownRow(damage_type='Physical', total_damage=500, dps=50.0)]
        })

        # First refresh
        dps_panel.refresh()

        # Add new damage type
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(
                character='Woo',
                total_damage=500,
                time_seconds=10,
                dps=50.0,
                hit_rate=75.0,
                breakdown_token=(('Fire', 200), ('Physical', 300)),
            )
        ])
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [
                DpsBreakdownRow(damage_type='Physical', total_damage=300, dps=30.0),
                DpsBreakdownRow(damage_type='Fire', total_damage=200, dps=20.0),
            ]
        })

        # Second refresh should handle new damage type
        dps_panel.refresh()

        # Cache should include both damage types
        breakdown = dps_panel._cached_breakdown['Woo']
        assert len(breakdown) == 2

    def test_clear_cache_resets_all_caches(self, dps_panel) -> None:
        """Test that clear_cache resets all cache structures."""
        # Populate cache
        dps_panel._cached_data['Woo'] = {'dps': 50.0}
        dps_panel._cached_breakdown['Woo'] = []
        dps_panel._tree_refresh_state.item_ids['Woo'] = 'item1'
        dps_panel._child_ids['Woo'] = {}
        dps_panel._tree_refresh_state.row_tokens['Woo'] = (50.0, 500, 75.0, 10)
        dps_panel._cached_breakdown_tokens['Woo'] = (('Physical', 500),)
        dps_panel._tree_refresh_state.order_token = ('Woo',)
        dps_panel._tree_refresh_state.last_refresh_version = 3

        # Clear cache
        dps_panel.clear_cache()

        # All caches should be empty
        assert len(dps_panel._cached_data) == 0
        assert len(dps_panel._cached_breakdown) == 0
        assert len(dps_panel._tree_refresh_state.item_ids) == 0
        assert len(dps_panel._child_ids) == 0
        assert len(dps_panel._tree_refresh_state.row_tokens) == 0
        assert len(dps_panel._cached_breakdown_tokens) == 0
        assert dps_panel._tree_refresh_state.order_token == ()
        assert dps_panel._tree_refresh_state.last_refresh_version == -1

    def test_incremental_refresh_no_changes(self, dps_panel) -> None:
        """Test that no updates occur when data hasn't changed."""
        # Initial data
        data = [
            DpsRow(
                character='Woo',
                total_damage=500,
                time_seconds=10,
                dps=50.0,
                hit_rate=75.0,
                breakdown_token=(('Physical', 500),),
            )
        ]

        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=data)
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={})

        # First refresh
        dps_panel.refresh()
        cache_snapshot = dps_panel._cached_data.copy()
        dps_panel.dps_query_service.get_damage_type_breakdowns.reset_mock()

        # Second refresh with same data
        dps_panel.refresh()

        # Cache should be identical (data not changed)
        assert dps_panel._cached_data == cache_snapshot
        dps_panel.dps_query_service.get_damage_type_breakdowns.assert_not_called()

    def test_incremental_refresh_skips_breakdown_fetch_for_unchanged_character(self, dps_panel) -> None:
        """Unchanged characters should reuse cached breakdowns."""
        data = [
            DpsRow(
                character='Woo',
                total_damage=500,
                time_seconds=10,
                dps=50.0,
                hit_rate=75.0,
                breakdown_token=(('Physical', 500),),
            )
        ]

        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=data)
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [DpsBreakdownRow(damage_type='Physical', total_damage=500, dps=50.0)]
        })

        dps_panel.refresh()
        assert dps_panel.dps_query_service.get_damage_type_breakdowns.call_count == 1

        dps_panel.dps_query_service.get_damage_type_breakdowns.reset_mock()
        dps_panel.refresh()

        dps_panel.dps_query_service.get_damage_type_breakdowns.assert_not_called()

    def test_refresh_skips_unchanged_view_after_unrelated_store_change(self, dps_panel) -> None:
        """Store version bumps with identical DPS view should not rebuild caches."""
        data = [
            DpsRow(
                character='Woo',
                total_damage=500,
                time_seconds=10,
                dps=50.0,
                hit_rate=75.0,
                breakdown_token=(('Physical', 500),),
            )
        ]

        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=data)
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [DpsBreakdownRow(damage_type='Physical', total_damage=500, dps=50.0)]
        })

        dps_panel.refresh()
        cached_snapshot = dict(dps_panel._cached_data)
        item_id = dps_panel._tree_refresh_state.item_ids['Woo']

        apply(dps_panel.data_store, attack(attacker="Ally", target="Goblin", outcome="miss"))

        dps_panel.dps_query_service.get_damage_type_breakdowns.reset_mock()
        dps_panel.refresh()

        assert dps_panel._cached_data == cached_snapshot
        assert dps_panel._tree_refresh_state.item_ids['Woo'] == item_id
        dps_panel.dps_query_service.get_damage_type_breakdowns.assert_not_called()

    def test_incremental_refresh_reorders_natural_dps_order_without_rebuild(self, dps_panel) -> None:
        """Natural DPS ordering should move existing rows instead of rebuilding them."""
        initial_data = [
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=(('Physical', 500),)),
            DpsRow(character='Ally', total_damage=300, time_seconds=10, dps=30.0, hit_rate=80.0, breakdown_token=(('Fire', 300),)),
        ]

        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=initial_data)
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [DpsBreakdownRow(damage_type='Physical', total_damage=500, dps=50.0)],
            'Ally': [DpsBreakdownRow(damage_type='Fire', total_damage=300, dps=30.0)],
        })
        dps_panel.refresh()
        initial_item_ids = dict(dps_panel._tree_refresh_state.item_ids)

        reordered_data = [
            DpsRow(character='Ally', total_damage=600, time_seconds=10, dps=60.0, hit_rate=80.0, breakdown_token=(('Fire', 600),)),
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=(('Physical', 500),)),
        ]

        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=reordered_data)
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Ally': [DpsBreakdownRow(damage_type='Fire', total_damage=600, dps=60.0)],
        })
        dps_panel.refresh()

        ordered_names = [
            dps_panel.tree.item(item_id, "values")[0]
            for item_id in dps_panel.tree.get_children()
        ]
        assert ordered_names == ["Ally", "Woo"]
        assert dps_panel._tree_refresh_state.item_ids == initial_item_ids

    def test_refresh_rebuilds_when_view_key_changes(self, dps_panel) -> None:
        """Changing target filter or mode should force a safe full refresh."""
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=(('Physical', 500),))
        ])
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={
            'Woo': [DpsBreakdownRow(damage_type='Physical', total_damage=500, dps=50.0)]
        })

        dps_panel.refresh()
        initial_item_id = dps_panel._tree_refresh_state.item_ids['Woo']

        dps_panel.target_filter_var.set("Goblin")
        dps_panel.refresh()

        assert dps_panel._tree_refresh_state.view_key[0] == "Goblin"
        assert dps_panel._tree_refresh_state.item_ids['Woo'] != initial_item_id

    def test_full_refresh_does_not_rescan_dps_rows_per_character(self, dps_panel) -> None:
        """Full refresh should iterate DPS rows linearly, not rescan them per insert."""

        class CountingList(list[DpsRow]):
            def __init__(self, items: list[DpsRow]) -> None:
                super().__init__(items)
                self.iterations = 0
                self.items_yielded = 0

            def __iter__(self) -> Iterator[DpsRow]:
                self.iterations += 1
                for item in super().__iter__():
                    self.items_yielded += 1
                    yield item

        rows = CountingList([
            DpsRow(
                character=f'Player {index}',
                total_damage=500 - index,
                time_seconds=10,
                dps=50.0 - index,
                hit_rate=75.0,
                breakdown_token=(),
            )
            for index in range(25)
        ])

        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=rows)
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={})

        dps_panel.refresh()

        assert rows.iterations <= 6
        assert rows.items_yielded <= len(rows) * 6


class TestRefreshSelectionPreservation:
    """Test suite for selection preservation during refresh."""

    def test_selection_preserved_during_incremental_refresh(self, dps_panel) -> None:
        """Test that selection is preserved when using incremental refresh."""
        # This is implicitly tested but we can verify the mechanism
        # The _incremental_refresh doesn't recreate items, so selection persists

        # Initial data
        dps_panel.dps_query_service.get_dps_display_data = Mock(return_value=[
            DpsRow(character='Woo', total_damage=500, time_seconds=10, dps=50.0, hit_rate=75.0, breakdown_token=())
        ])
        dps_panel.dps_query_service.get_damage_type_breakdowns = Mock(return_value={})

        # First refresh
        dps_panel.refresh()

        # Select item
        selected_before = ()
        children = dps_panel.tree.get_children()
        if children:
            dps_panel.tree.selection_set(children[0])
            selected_before = dps_panel.tree.selection()

        # Incremental refresh
        dps_panel.refresh()

        # Selection should still exist (item ID didn't change)
        selected_after = dps_panel.tree.selection()
        assert selected_before == selected_after

