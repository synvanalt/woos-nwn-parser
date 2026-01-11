"""Test selection preservation in treeviews during refresh.

This test verifies that user selections in all treeview panels are preserved
when the treeview contents are refreshed.
"""

import tkinter as tk
from tkinter import ttk
import pytest

from datetime import datetime

from app.storage import DataStore
from app.parser import LogParser
from app.services import DPSCalculationService
from app.ui.widgets import DPSPanel, TargetStatsPanel, ImmunityPanel
from app.models import EnemyAC, TargetAttackBonus


@pytest.fixture(scope="module")
def tk_root():
    """Create a shared Tk root for all tests in this module."""
    root = tk.Tk()
    root.withdraw()  # Hide the window
    yield root
    # Cleanup after all tests
    try:
        root.destroy()
    except:
        pass


@pytest.fixture
def notebook(tk_root):
    """Create a fresh notebook widget for each test."""
    nb = ttk.Notebook(tk_root)
    yield nb
    # Cleanup widgets after each test
    try:
        for child in nb.winfo_children():
            child.destroy()
        nb.destroy()
    except:
        pass


def test_dps_panel_selection_preservation(tk_root, notebook) -> None:
    """Test that DPS panel preserves selection after refresh."""
    print("\n=== Testing DPS Panel Selection Preservation ===")

    # Setup
    data_store = DataStore()
    dps_service = DPSCalculationService(data_store)
    panel = DPSPanel(notebook, data_store, dps_service)

    # Add some test data using the correct API
    timestamp1 = datetime.now()
    data_store.insert_damage_event(
        target="Monster",
        damage_type="Physical",
        immunity=0,
        total_damage=10,
        attacker="Hero",
        timestamp=timestamp1
    )
    data_store.update_dps_data("Hero", 10, timestamp1, {"Physical": 10})

    timestamp2 = datetime.now()
    data_store.insert_damage_event(
        target="Monster",
        damage_type="Fire",
        immunity=0,
        total_damage=15,
        attacker="Hero",
        timestamp=timestamp2
    )
    data_store.update_dps_data("Hero", 15, timestamp2, {"Fire": 15})

    # Initial refresh to populate the tree
    panel.refresh()

    # Check that tree has items
    items = panel.tree.get_children()
    assert len(items) > 0, "Tree should have items after refresh"

    # Select the first item
    first_item = items[0]
    panel.tree.selection_set(first_item)
    selected_before = panel.tree.selection()
    assert len(selected_before) == 1, "Should have one item selected"

    # Get the character name of the selected item
    selected_char = panel.tree.item(first_item, "values")[0]
    print(f"Selected character: {selected_char}")

    # Refresh the panel
    panel.refresh()

    # Check that selection is preserved
    selected_after = panel.tree.selection()
    assert len(selected_after) == 1, "Should still have one item selected after refresh"

    # Verify it's the same character
    new_item = selected_after[0]
    new_char = panel.tree.item(new_item, "values")[0]
    assert new_char == selected_char, f"Selection should be preserved (was {selected_char}, now {new_char})"

    print(f"✅ DPS Panel: Selection preserved after refresh ({new_char})")


def test_target_stats_panel_selection_preservation(tk_root, notebook) -> None:
    """Test that Target Stats panel preserves selection after refresh."""
    print("\n=== Testing Target Stats Panel Selection Preservation ===")

    # Setup
    data_store = DataStore()
    parser = LogParser()
    panel = TargetStatsPanel(notebook, data_store, parser)

    # Add some test data - properly create EnemyAC and TargetAttackBonus objects
    # TargetStatsPanel shows stats about targets that were ATTACKED (not attackers)
    ac1 = EnemyAC(name="Monster1", min_hit=20)
    ac2 = EnemyAC(name="Monster2", min_hit=25)
    parser.target_ac["Monster1"] = ac1
    parser.target_ac["Monster2"] = ac2

    bonus1 = TargetAttackBonus(name="Monster1", max_bonus=15)
    bonus2 = TargetAttackBonus(name="Monster2", max_bonus=18)
    parser.target_attack_bonus["Monster1"] = bonus1
    parser.target_attack_bonus["Monster2"] = bonus2

    timestamp1 = datetime.now()
    data_store.insert_damage_event(
        target="Monster1",  # Hero attacking Monster1
        damage_type="Physical",
        immunity=0,
        total_damage=10,
        attacker="Hero",
        timestamp=timestamp1
    )

    timestamp2 = datetime.now()
    data_store.insert_damage_event(
        target="Monster2",  # Hero attacking Monster2
        damage_type="Physical",
        immunity=0,
        total_damage=12,
        attacker="Hero",
        timestamp=timestamp2
    )

    # Initial refresh to populate the tree
    panel.refresh()

    # Check that tree has items
    items = panel.tree.get_children()
    assert len(items) > 0, "Tree should have items after refresh"

    # Select the first item
    first_item = items[0]
    panel.tree.selection_set(first_item)
    selected_before = panel.tree.selection()
    assert len(selected_before) == 1, "Should have one item selected"

    # Get the target name of the selected item
    selected_target = panel.tree.item(first_item, "values")[0]
    print(f"Selected target: {selected_target}")

    # Refresh the panel
    panel.refresh()

    # Check that selection is preserved
    selected_after = panel.tree.selection()
    assert len(selected_after) == 1, "Should still have one item selected after refresh"

    # Verify it's the same target
    new_item = selected_after[0]
    new_target = panel.tree.item(new_item, "values")[0]
    assert new_target == selected_target, f"Selection should be preserved (was {selected_target}, now {new_target})"

    print(f"✅ Target Stats Panel: Selection preserved after refresh ({new_target})")


def test_immunity_panel_selection_preservation(tk_root, notebook) -> None:
    """Test that Immunity panel preserves selection after refresh."""
    print("\n=== Testing Immunity Panel Selection Preservation ===")

    # Setup
    data_store = DataStore()
    parser = LogParser()
    panel = ImmunityPanel(notebook, data_store, parser)

    # Add some test data with immunity
    timestamp1 = datetime.now()
    data_store.insert_damage_event(
        target="Monster",
        damage_type="Physical",
        immunity=5,
        total_damage=10,
        attacker="Hero",
        timestamp=timestamp1
    )
    data_store.record_immunity("Monster", "Physical", 5, 10)

    timestamp2 = datetime.now()
    data_store.insert_damage_event(
        target="Monster",
        damage_type="Fire",
        immunity=3,
        total_damage=15,
        attacker="Hero",
        timestamp=timestamp2
    )
    data_store.record_immunity("Monster", "Fire", 3, 15)

    # Update target list and select a target
    targets = data_store.get_all_targets()
    panel.update_target_list(targets)

    # Refresh to populate the tree
    panel.refresh_target_details("Monster")

    # Check that tree has items
    items = panel.tree.get_children()
    assert len(items) > 0, "Tree should have items after refresh"

    # Select the first item (damage type)
    first_item = items[0]
    panel.tree.selection_set(first_item)
    selected_before = panel.tree.selection()
    assert len(selected_before) == 1, "Should have one item selected"

    # Get the damage type of the selected item
    selected_damage_type = panel.tree.item(first_item, "values")[0]
    print(f"Selected damage type: {selected_damage_type}")

    # Refresh the panel
    panel.refresh_target_details("Monster")

    # Check that selection is preserved
    selected_after = panel.tree.selection()
    assert len(selected_after) == 1, "Should still have one item selected after refresh"

    # Verify it's the same damage type
    new_item = selected_after[0]
    new_damage_type = panel.tree.item(new_item, "values")[0]
    assert new_damage_type == selected_damage_type, f"Selection should be preserved (was {selected_damage_type}, now {new_damage_type})"

    print(f"✅ Immunity Panel: Selection preserved after refresh ({new_damage_type})")


def test_multiple_selection_preservation(tk_root, notebook) -> None:
    """Test that multiple selections are preserved."""
    print("\n=== Testing Multiple Selection Preservation ===")

    # Setup Target Stats Panel for multi-select test
    data_store = DataStore()
    parser = LogParser()
    panel = TargetStatsPanel(notebook, data_store, parser)

    # Add test data for multiple targets - Hero attacking multiple Monsters
    for i in range(1, 4):
        target = f"Monster{i}"
        ac = EnemyAC(name=target, min_hit=20 + i)
        parser.target_ac[target] = ac
        bonus = TargetAttackBonus(name=target, max_bonus=15 + i)
        parser.target_attack_bonus[target] = bonus
        timestamp = datetime.now()
        data_store.insert_damage_event(
            target=target,  # Hero attacking Monster
            damage_type="Physical",
            immunity=0,
            total_damage=10 + i,
            attacker="Hero",
            timestamp=timestamp
        )

    # Initial refresh
    panel.refresh()

    # Select multiple items
    items = panel.tree.get_children()
    assert len(items) >= 2, f"Should have at least 2 items, got {len(items)}"

    panel.tree.selection_set([items[0], items[1]])
    selected_before = panel.tree.selection()
    assert len(selected_before) == 2, "Should have two items selected"

    # Get the target names
    selected_targets = {panel.tree.item(item, "values")[0] for item in selected_before}
    print(f"Selected targets: {selected_targets}")

    # Refresh
    panel.refresh()

    # Check that both selections are preserved
    selected_after = panel.tree.selection()
    assert len(selected_after) == 2, "Should still have two items selected after refresh"

    # Verify they're the same targets
    new_targets = {panel.tree.item(item, "values")[0] for item in selected_after}
    assert new_targets == selected_targets, f"Multiple selections should be preserved (was {selected_targets}, now {new_targets})"

    print(f"✅ Multiple Selection: All selections preserved after refresh ({new_targets})")


if __name__ == "__main__":
    # This file should be run with pytest, not directly
    print("Please run with: pytest tests/test_selection_preservation.py -v")
    print("These tests require pytest fixtures for proper Tkinter instance management.")
