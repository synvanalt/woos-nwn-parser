"""Target stats panel widget for Woo's NWN Parser UI.

This module contains the TargetStatsPanel widget that displays target
statistics including AC, AB, and save values.
"""

from tkinter import ttk

from ...storage import DataStore
from ...parser import LogParser


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
        self.setup_ui()

    def setup_ui(self) -> None:
        """Setup the panel UI components."""
        # Scrollbar for target summary tree
        summary_scrollbar = ttk.Scrollbar(self)
        summary_scrollbar.pack(side="right", fill="y")

        # Treeview for displaying all targets with AB, AC, and saves
        summary_columns = ("Target", "AB", "AC", "Fortitude", "Reflex", "Will")
        self.tree = ttk.Treeview(
            self,
            columns=summary_columns,
            show="headings",
            height=8,
            yscrollcommand=summary_scrollbar.set,
        )

        for col in summary_columns:
            self.tree.heading(col, text=col)
            if col == "Target":
                self.tree.column(col, width=275)
            else:
                self.tree.column(col, width=75)

        self.tree.pack(fill="both", expand=True)
        summary_scrollbar.config(command=self.tree.yview)

    def refresh(self) -> None:
        """Refresh the target stats display with current data."""
        # Save the currently selected target names
        selected_targets = set()
        for item in self.tree.selection():
            values = self.tree.item(item, "values")
            if values and len(values) > 0:
                selected_targets.add(values[0])  # Target name is first column

        # Clear existing data
        self.tree.delete(*self.tree.get_children())

        # Get summary data for all targets
        summary_data = self.data_store.get_all_targets_summary(self.parser)

        # Track items to restore selection
        items_to_select = []

        # Populate treeview with target data
        for item in summary_data:
            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    item["target"],
                    item["ab"],
                    item["ac"],
                    item["fortitude"],
                    item["reflex"],
                    item["will"],
                ),
            )

            # Check if this target should be selected
            if item["target"] in selected_targets:
                items_to_select.append(item_id)

        # Restore selection
        if items_to_select:
            self.tree.selection_set(items_to_select)

