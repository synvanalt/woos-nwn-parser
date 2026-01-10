"""Test selection preservation in treeviews during refresh.

This test verifies that user selections in all treeview panels are preserved
when the treeview contents are refreshed.
"""

import tkinter as tk
from tkinter import ttk

from app.storage import DataStore
from app.parser import LogParser
from app.services import DPSCalculationService
from app.ui.widgets import DPSPanel, TargetStatsPanel, ImmunityPanel
from app.models import DamageEvent


def test_dps_panel_selection_preservation() -> None:
    """Test that DPS panel preserves selection after refresh."""
    print("\n=== Testing DPS Panel Selection Preservation ===")

    root = tk.Tk()
    root.withdraw()  # Hide the window

    # Setup
    data_store = DataStore()
    dps_service = DPSCalculationService(data_store)
    notebook = ttk.Notebook(root)
    panel = DPSPanel(notebook, data_store, dps_service)

    # Add some test data
    data_store.add_event(DamageEvent(
        timestamp=1.0,
        attacker="Hero",
        target="Monster",
        damage=10,
        damage_type="Physical",
        is_critical=False,
        miss=False
    ))
    data_store.add_event(DamageEvent(
        timestamp=2.0,
        attacker="Hero",
        target="Monster",
        damage=15,
        damage_type="Fire",
        is_critical=False,
        miss=False
    ))

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

    root.destroy()


def test_target_stats_panel_selection_preservation() -> None:
    """Test that Target Stats panel preserves selection after refresh."""
    print("\n=== Testing Target Stats Panel Selection Preservation ===")

    root = tk.Tk()
    root.withdraw()

    # Setup
    data_store = DataStore()
    parser = LogParser()
    notebook = ttk.Notebook(root)
    panel = TargetStatsPanel(notebook, data_store, parser)

    # Add some test data
    parser.target_ac["Monster1"] = 20
    parser.target_ac["Monster2"] = 25
    parser.target_attack_bonus["Monster1"] = 15
    parser.target_attack_bonus["Monster2"] = 18

    data_store.add_event(DamageEvent(
        timestamp=1.0,
        attacker="Monster1",
        target="Hero",
        damage=10,
        damage_type="Physical",
        is_critical=False,
        miss=False
    ))
    data_store.add_event(DamageEvent(
        timestamp=2.0,
        attacker="Monster2",
        target="Hero",
        damage=12,
        damage_type="Physical",
        is_critical=False,
        miss=False
    ))

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

    root.destroy()


def test_immunity_panel_selection_preservation() -> None:
    """Test that Immunity panel preserves selection after refresh."""
    print("\n=== Testing Immunity Panel Selection Preservation ===")

    root = tk.Tk()
    root.withdraw()

    # Setup
    data_store = DataStore()
    parser = LogParser()
    notebook = ttk.Notebook(root)
    panel = ImmunityPanel(notebook, data_store, parser)

    # Add some test data
    data_store.add_event(DamageEvent(
        timestamp=1.0,
        attacker="Hero",
        target="Monster",
        damage=10,
        damage_type="Physical",
        is_critical=False,
        miss=False
    ))
    data_store.add_event(DamageEvent(
        timestamp=2.0,
        attacker="Hero",
        target="Monster",
        damage=15,
        damage_type="Fire",
        is_critical=False,
        miss=False
    ))

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

    root.destroy()


def test_multiple_selection_preservation() -> None:
    """Test that multiple selections are preserved."""
    print("\n=== Testing Multiple Selection Preservation ===")

    root = tk.Tk()
    root.withdraw()

    # Setup Target Stats Panel for multi-select test
    data_store = DataStore()
    parser = LogParser()
    notebook = ttk.Notebook(root)
    panel = TargetStatsPanel(notebook, data_store, parser)

    # Add test data for multiple targets
    for i in range(1, 4):
        target = f"Monster{i}"
        parser.target_ac[target] = 20 + i
        parser.target_attack_bonus[target] = 15 + i
        data_store.add_event(DamageEvent(
            timestamp=float(i),
            attacker=target,
            target="Hero",
            damage=10 + i,
            damage_type="Physical",
            is_critical=False,
            miss=False
        ))

    # Initial refresh
    panel.refresh()

    # Select multiple items
    items = panel.tree.get_children()
    assert len(items) >= 2, "Should have at least 2 items"

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

    root.destroy()


if __name__ == "__main__":
    print("Testing Selection Preservation in All Treeview Panels")
    print("=" * 60)

    try:
        test_dps_panel_selection_preservation()
        test_target_stats_panel_selection_preservation()
        test_immunity_panel_selection_preservation()
        test_multiple_selection_preservation()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("Selection preservation is working correctly in all panels.")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        raise

