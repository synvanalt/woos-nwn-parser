"""Target stats panel widget for Woo's NWN Parser UI.

This module contains the TargetStatsPanel widget that displays target
statistics including AC, AB, and save values.
"""

from tkinter import ttk

from ...storage import DataStore
from ...parser import LogParser
from .sorted_treeview import SortedTreeview


class TargetStatsPanel(ttk.Frame):
    """Target statistics display panel.

    Manages:
    - Treeview showing all targets with their AC, AB, and save values
    - Read-only display of target summary data

    This is a reusable widget that can be placed in any notebook or frame.
    """

    def __init__(
        self,
        parent: ttk.Notebook,
        data_store: DataStore,
        parser: LogParser = None,
    ) -> None:
        """Initialize the target stats panel.

        Args:
            parent: Parent notebook widget
            data_store: Reference to the data store
            parser: Reference to the log parser (optional)
        """
        super().__init__(parent, padding="10")
        self.data_store = data_store
        self.parser = parser
        self._cached_rows: dict = {}
        self._item_ids: dict = {}
        self.setup_ui()

    def setup_ui(self) -> None:
        """Setup the panel UI components."""
        # Scrollbar for target summary tree
        summary_scrollbar = ttk.Scrollbar(self)
        summary_scrollbar.pack(side="right", fill="y")

        # Treeview for displaying all targets with AB, AC, and saves
        summary_columns = ("Target", "AB", "AC", "Fortitude", "Reflex", "Will", "Dmg Taken")
        self.tree = SortedTreeview(
            self,
            columns=summary_columns,
            show="headings",
            height=8,
            yscrollcommand=summary_scrollbar.set,
        )

        for col in summary_columns:
            if col == "Target":
                self.tree.column(col, width=220)
            elif col == "Dmg Taken":
                self.tree.column(col, width=80)
            else:
                self.tree.column(col, width=70)

        self.tree.pack(fill="both", expand=True)
        summary_scrollbar.config(command=self.tree.yview)

        # Set default sort by Target name ascending
        self.tree.set_default_sort("Target", reverse=False)

    def refresh(self) -> None:
        """Refresh the target stats display with current data."""
        summary_data = self.data_store.get_all_targets_summary(self.parser)
        new_rows = {
            item["target"]: (
                item["target"],
                item["ab"],
                item["ac"],
                item["fortitude"],
                item["reflex"],
                item["will"],
                item["damage_taken"],
            )
            for item in summary_data
        }

        current_targets = set(self._cached_rows.keys())
        new_targets = set(new_rows.keys())

        needs_full_refresh = (
            not self._item_ids or
            current_targets != new_targets
        )

        if not needs_full_refresh and self.tree.get_children():
            if self.tree._last_sorted_col == "Target" and not self.tree._sort_reverse:
                tree_order = [self.tree.item(item, "values")[0] for item in self.tree.get_children()]
                summary_order = [item["target"] for item in summary_data]
                needs_full_refresh = tree_order != summary_order

        if needs_full_refresh:
            self._full_refresh(summary_data)
        else:
            self._incremental_refresh(new_rows)

    def _full_refresh(self, summary_data: list[dict]) -> None:
        """Rebuild the tree when targets are added, removed, or reordered."""
        # Save the currently selected target names
        selected_targets = set()
        for item in self.tree.selection():
            values = self.tree.item(item, "values")
            if values and len(values) > 0:
                selected_targets.add(values[0])  # Target name is first column

        # Suppress visual updates during bulk operations
        original_show = self.tree.cget("show")
        self.tree.configure(show="")

        try:
            # Clear existing data
            self.tree.delete(*self.tree.get_children())
            self._item_ids.clear()

            # Track items to restore selection
            items_to_select = []

            # Populate treeview with target data
            for item in summary_data:
                row_values = (
                    item["target"],
                    item["ab"],
                    item["ac"],
                    item["fortitude"],
                    item["reflex"],
                    item["will"],
                    item["damage_taken"],
                )
                item_id = self.tree.insert(
                    "",
                    "end",
                    values=row_values,
                )
                self._item_ids[item["target"]] = item_id

                # Check if this target should be selected
                if item["target"] in selected_targets:
                    items_to_select.append(item_id)

            # Apply sort only if needed:
            # - If user has never sorted, apply default sort
            # - If user has sorted, maintain their sort preference
            # This is efficient: only sorts when structure changes, not on every update
            if self.tree._last_sorted_col:
                self.tree.apply_current_sort()

        finally:
            # Restore visual updates
            self.tree.configure(show=original_show)

        # Restore selection (after show is restored)
        if items_to_select:
            self.tree.selection_set(items_to_select)

        self._cached_rows = {
            item["target"]: (
                item["target"],
                item["ab"],
                item["ac"],
                item["fortitude"],
                item["reflex"],
                item["will"],
                item["damage_taken"],
            )
            for item in summary_data
        }

    def _incremental_refresh(self, new_rows: dict) -> None:
        """Update existing rows without rebuilding the whole tree."""
        for target, row_values in new_rows.items():
            if row_values == self._cached_rows.get(target):
                continue

            item_id = self._item_ids.get(target)
            if item_id:
                self.tree.item(item_id, values=row_values)

        self._cached_rows = new_rows

        if self.tree._last_sorted_col and self.tree._last_sorted_col != "Target":
            self.tree.apply_current_sort()
        elif self.tree._last_sorted_col == "Target" and self.tree._sort_reverse:
            self.tree.apply_current_sort()
