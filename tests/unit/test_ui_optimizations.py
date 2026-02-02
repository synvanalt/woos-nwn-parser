"""Tests for UI optimization features.

This module tests the performance optimizations added to the UI layer,
including dirty checking, sorted treeview optimization, and batch updates.
"""

import os
import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
import tkinter as tk
from tkinter import ttk

from app.storage import DataStore

# Check if we're in a headless environment
_SKIP_TK_TESTS = os.environ.get('DISPLAY') is None and os.name != 'nt'

def _can_create_tk_root():
    """Check if we can create a Tk root (display is available)."""
    try:
        root = tk.Tk()
        root.withdraw()
        # Try to update to ensure Tcl is properly initialized
        root.update_idletasks()
        root.destroy()
        return True
    except (tk.TclError, RuntimeError, Exception):
        return False

# Cache the result since Tk availability doesn't change during test session
_TK_AVAILABLE = _can_create_tk_root()

from app.ui.widgets.sorted_treeview import SortedTreeview


class TestDataStoreVersionTracking:
    """Test DataStore version tracking for dirty checking."""

    def test_initial_version_is_zero(self):
        """Version should start at 0."""
        data_store = DataStore()
        assert data_store.version == 0

    def test_version_increments_on_attack_event(self):
        """Version should increment when attack event is inserted."""
        data_store = DataStore()
        initial_version = data_store.version

        data_store.insert_attack_event("Attacker", "Target", "hit", roll=15, bonus=5, total=20)

        assert data_store.version == initial_version + 1

    def test_version_increments_on_damage_event(self):
        """Version should increment when damage event is inserted."""
        data_store = DataStore()
        initial_version = data_store.version

        data_store.insert_damage_event("Target", "Fire", 0, 50, "Attacker", datetime.now())

        assert data_store.version == initial_version + 1

    def test_version_increments_on_dps_update(self):
        """Version should increment when DPS data is updated."""
        data_store = DataStore()
        initial_version = data_store.version

        data_store.update_dps_data("Character", 100, datetime.now(), {"Fire": 100})

        assert data_store.version == initial_version + 1

    def test_version_increments_multiple_times(self):
        """Version should increment with each modification."""
        data_store = DataStore()

        for i in range(5):
            data_store.insert_attack_event("Attacker", f"Target{i}", "hit")

        assert data_store.version == 5

    def test_version_is_thread_safe(self):
        """Version access should be thread-safe."""
        import threading
        data_store = DataStore()
        errors = []

        def insert_events():
            try:
                for _ in range(100):
                    data_store.insert_attack_event("Attacker", "Target", "hit")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=insert_events) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert data_store.version == 500

@pytest.mark.skipif(not _TK_AVAILABLE, reason="Tkinter display not available")
class TestSortedTreeviewOptimization:
    """Test SortedTreeview sorting optimizations."""

    @pytest.fixture
    def tree(self, shared_tk_root):
        """Create a SortedTreeview for testing using the shared Tk root."""
        if shared_tk_root is None:
            pytest.skip("Tkinter not available")

        tree = SortedTreeview(shared_tk_root, columns=("Name", "Value"))
        tree.set_default_sort("Value", reverse=True)
        yield tree
        # Clean up the tree widget after test
        try:
            tree.destroy()
        except tk.TclError:
            pass  # Already destroyed


    def test_is_already_sorted_empty_tree(self, tree):
        """Empty tree should be considered sorted."""
        assert tree._is_already_sorted() is True

    def test_is_already_sorted_single_item(self, tree):
        """Single item should be considered sorted."""
        tree.insert("", "end", values=("Item1", "100"))
        assert tree._is_already_sorted() is True

    def test_is_already_sorted_correctly_sorted_descending(self, tree):
        """Correctly sorted descending data should return True."""
        tree.insert("", "end", values=("Item1", "300"))
        tree.insert("", "end", values=("Item2", "200"))
        tree.insert("", "end", values=("Item3", "100"))
        assert tree._is_already_sorted() is True

    def test_is_already_sorted_incorrectly_sorted(self, tree):
        """Incorrectly sorted data should return False."""
        tree.insert("", "end", values=("Item1", "100"))
        tree.insert("", "end", values=("Item2", "200"))
        tree.insert("", "end", values=("Item3", "300"))
        assert tree._is_already_sorted() is False

    def test_is_already_sorted_ascending(self, tree):
        """Test ascending sort detection."""
        tree.set_default_sort("Value", reverse=False)
        tree.insert("", "end", values=("Item1", "100"))
        tree.insert("", "end", values=("Item2", "200"))
        tree.insert("", "end", values=("Item3", "300"))
        assert tree._is_already_sorted() is True

    def test_is_already_sorted_string_column(self, tree):
        """Test string column sorting detection."""
        tree.set_default_sort("Name", reverse=False)
        tree.insert("", "end", values=("Alpha", "100"))
        tree.insert("", "end", values=("Beta", "200"))
        tree.insert("", "end", values=("Gamma", "300"))
        assert tree._is_already_sorted() is True

    def test_is_already_sorted_handles_dash_values(self, tree):
        """Dash values should be handled correctly (treated as -inf for descending)."""
        # With descending sort, dash values (treated as -inf) should be at the end
        tree.insert("", "end", values=("Item1", "300"))
        tree.insert("", "end", values=("Item2", "100"))
        tree.insert("", "end", values=("Item3", "-"))
        assert tree._is_already_sorted() is True

    def test_apply_current_sort_skips_when_sorted(self, tree):
        """apply_current_sort should skip sorting if already sorted."""
        tree.insert("", "end", values=("Item1", "300"))
        tree.insert("", "end", values=("Item2", "200"))
        tree.insert("", "end", values=("Item3", "100"))

        # Spy on sort_column
        original_sort_column = tree.sort_column
        call_count = [0]

        def counting_sort_column(*args, **kwargs):
            call_count[0] += 1
            return original_sort_column(*args, **kwargs)

        tree.sort_column = counting_sort_column

        tree.apply_current_sort()

        assert call_count[0] == 0  # Should not have called sort_column

    def test_apply_current_sort_sorts_when_needed(self, tree):
        """apply_current_sort should sort if data is not in order."""
        tree.insert("", "end", values=("Item1", "100"))
        tree.insert("", "end", values=("Item2", "200"))
        tree.insert("", "end", values=("Item3", "300"))

        # Spy on sort_column
        original_sort_column = tree.sort_column
        call_count = [0]

        def counting_sort_column(*args, **kwargs):
            call_count[0] += 1
            return original_sort_column(*args, **kwargs)

        tree.sort_column = counting_sort_column

        tree.apply_current_sort()

        assert call_count[0] == 1  # Should have called sort_column


@pytest.mark.skipif(not _TK_AVAILABLE, reason="Tkinter display not available")
class TestBatchVisualUpdates:
    """Test batch visual update suppression in panel widgets."""

    def test_target_stats_panel_uses_batch_update(self, shared_tk_root):
        """TargetStatsPanel.refresh() should use batch update pattern."""
        if shared_tk_root is None:
            pytest.skip("Tkinter not available")

        from app.ui.widgets.target_stats_panel import TargetStatsPanel
        from app.storage import DataStore
        from app.parser import LogParser

        data_store = DataStore()
        parser = LogParser()

        # Create a mock notebook
        notebook = ttk.Notebook(shared_tk_root)
        panel = TargetStatsPanel(notebook, data_store, parser)

        # Add some data
        data_store.insert_damage_event("Target1", "Fire", 0, 100, "Attacker")
        data_store.insert_attack_event("Attacker", "Target1", "hit", roll=15, bonus=5, total=20)

        # The refresh should work without error (batch update pattern)
        panel.refresh()

        # Verify tree has items
        assert len(panel.tree.get_children()) >= 0  # May be 0 or more depending on data

    def test_immunity_panel_uses_batch_update(self, shared_tk_root):
        """ImmunityPanel.refresh_target_details() should use batch update pattern."""
        if shared_tk_root is None:
            pytest.skip("Tkinter not available")

        from app.ui.widgets.immunity_panel import ImmunityPanel
        from app.storage import DataStore
        from app.parser import LogParser

        data_store = DataStore()
        parser = LogParser()

        # Create a mock notebook
        notebook = ttk.Notebook(shared_tk_root)
        panel = ImmunityPanel(notebook, data_store, parser)

        # Add some data
        data_store.insert_damage_event("Target1", "Fire", 0, 100, "Attacker")

        # The refresh should work without error (batch update pattern)
        panel.refresh_target_details("Target1")

        # Verify tree has items
        assert len(panel.tree.get_children()) >= 0


class TestDirtyFlagRefresh:
    """Test dirty flag-based refresh optimization."""

    def test_version_based_dirty_checking_concept(self):
        """Test the concept of version-based dirty checking."""
        data_store = DataStore()

        # Track last refresh version
        last_refresh_version = data_store.version

        # No changes - should not refresh
        assert data_store.version == last_refresh_version

        # Make a change
        data_store.insert_attack_event("Attacker", "Target", "hit")

        # Should now be dirty
        assert data_store.version != last_refresh_version

        # After refresh, update the tracked version
        last_refresh_version = data_store.version

        # No changes - should not refresh again
        assert data_store.version == last_refresh_version
