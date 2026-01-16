"""DPS display panel widget for Woo's NWN Parser UI.

This module contains the DPSPanel widget that displays DPS calculations
with time tracking modes and target filtering.
"""

import tkinter as tk
from tkinter import ttk

from ...storage import DataStore
from ...services import DPSCalculationService
from ..formatters import damage_type_to_color, apply_tag_to_tree, format_time


class DPSPanel(ttk.Frame):
    """DPS display panel with treeview and controls.

    Manages:
    - DPS treeview with parent/child structure for characters and damage types
    - First timestamp mode selector (Per Character / Global)
    - Target filter selector (All / specific target)

    This is a reusable widget that can be placed in any notebook or frame.
    """

    def __init__(
        self,
        parent: ttk.Notebook,
        data_store: DataStore,
        dps_service: DPSCalculationService,
    ) -> None:
        """Initialize the DPS panel.

        Args:
            parent: Parent notebook widget
            data_store: Reference to the data store
            dps_service: Reference to the DPS calculation service
        """
        super().__init__(parent, padding="10")
        self.data_store = data_store
        self.dps_service = dps_service
        self.setup_ui()

    def setup_ui(self) -> None:
        """Set up the panel UI components."""
        # DPS treeview frame
        dps_treeview_frame = ttk.Frame(self)
        dps_treeview_frame.pack(fill="both", expand=True, padx=0, pady=0)

        # DPS Treeview with scrollbar
        dps_scrollbar = ttk.Scrollbar(dps_treeview_frame)
        dps_scrollbar.pack(side="right", fill="y")

        dps_columns = ("Character", "DPS", "Total Damage", "Hit Rate", "Time")
        self.tree = ttk.Treeview(
            dps_treeview_frame,
            columns=dps_columns,
            show="tree headings",
            yscrollcommand=dps_scrollbar.set,
        )

        # Configure the tree column (shows expansion icons)
        self.tree.column("#0", width=25, minwidth=25, stretch=False)
        self.tree.heading("#0", text="")

        for col in dps_columns:
            self.tree.heading(col, text=col)
            if col == "Character":
                self.tree.column(col, width=150)
            elif col == "DPS":
                self.tree.column(col, width=100)
            elif col == "Total Damage":
                self.tree.column(col, width=100)
            elif col == "Hit Rate":
                self.tree.column(col, width=100)
            else:  # Time
                self.tree.column(col, width=100)

        self.tree.pack(fill="both", expand=True)
        dps_scrollbar.config(command=self.tree.yview)

        # Apply sv_ttk treeview indicator fix if available
        root = self.winfo_toplevel()
        if hasattr(root, "_fix_treeview_indicator"):
            root._fix_treeview_indicator(self.tree)

        # DPS controls frame
        dps_controls_frame = ttk.Frame(self)
        dps_controls_frame.pack(fill="x", expand=False, padx=0, pady=(10, 0))

        # First timestamp mode selector
        ttk.Label(dps_controls_frame, text="First Timestamp:").pack(
            side="left", padx=(5, 5)
        )
        self.time_tracking_var = tk.StringVar(value="Per Character")
        self.time_tracking_combo = ttk.Combobox(
            dps_controls_frame,
            textvariable=self.time_tracking_var,
            values=["Per Character", "Global"],
            state="readonly",
            width=12,
        )
        self.time_tracking_combo.pack(side="left", padx=(0, 10))
        self.time_tracking_combo.current(0)

        # Target Selector
        ttk.Label(dps_controls_frame, text="Filter Target:").pack(
            side="left", padx=(5, 5)
        )
        self.target_filter_var = tk.StringVar(value="All")
        self.target_filter_combo = ttk.Combobox(
            dps_controls_frame,
            textvariable=self.target_filter_var,
            values=["All"],
            state="readonly",
            width=40,
        )
        self.target_filter_combo.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.target_filter_combo.current(0)

    def refresh(self) -> None:
        """Refresh the DPS display with current data."""
        # Save the expanded state of all nodes
        expanded_nodes = set()
        for item in self.tree.get_children():
            if self.tree.item(item, "open"):
                values = self.tree.item(item, "values")
                if values:
                    expanded_nodes.add(values[0])

        # Save the currently selected items (by their character name)
        selected_characters = set()
        for item in self.tree.selection():
            values = self.tree.item(item, "values")
            if values and len(values) > 0:
                # Extract character name (strip leading spaces for child rows)
                char_name = values[0].strip()
                selected_characters.add(char_name)

        # Clear the tree
        self.tree.delete(*self.tree.get_children())

        # Get selected target filter
        selected_target = self.target_filter_var.get()
        dps_list = self.dps_service.get_dps_display_data(target_filter=selected_target)

        # Track items to restore selection
        items_to_select = []

        for dps_info in dps_list:
            character = dps_info["character"]
            total_damage = dps_info["total_damage"]
            time_seconds = dps_info["time_seconds"]
            dps = dps_info["dps"]
            hit_rate = dps_info["hit_rate"]

            # Format values for display
            time_display = format_time(time_seconds)
            dps_display = f"{dps:.2f}"
            hit_rate_display = f"{hit_rate:.1f}%"

            # Insert parent row for character
            parent_id = self.tree.insert(
                "",
                "end",
                text="",
                values=(character, dps_display, total_damage, hit_rate_display, time_display),
            )

            # Check if this character or any of its children should be selected
            if character in selected_characters:
                items_to_select.append(parent_id)

            # Get damage type breakdown for this character
            breakdown = self.dps_service.get_damage_type_breakdown(
                character, selected_target
            )

            # Insert child rows for each damage type
            for damage_data in breakdown:
                damage_type = damage_data["damage_type"]
                type_damage = damage_data["total_damage"]
                type_dps = damage_data["dps"]

                # Format damage type display with color tag
                color = damage_type_to_color(damage_type)
                tag = f"damage_type_{damage_type.replace(' ', '_').lower()}"
                apply_tag_to_tree(self.tree, tag, color)

                # Insert child row
                child_id = self.tree.insert(
                    parent_id,
                    "end",
                    text="",
                    values=(f"  {damage_type}", f"{type_dps:.2f}", type_damage, "", ""),
                    tags=(tag,),
                )

                # Check if this damage type should be selected
                if damage_type in selected_characters:
                    items_to_select.append(child_id)

            # Restore expanded state if this character was expanded
            if character in expanded_nodes:
                self.tree.item(parent_id, open=True)

        # Restore selection
        if items_to_select:
            self.tree.selection_set(items_to_select)

        # Update indicator images after refresh
        if hasattr(self.tree, "_update_indicators"):
            self.tree._update_indicators()

    def get_time_tracking_mode(self) -> str:
        """Get selected first timestamp mode.

        Returns:
            'per_character' or 'global'
        """
        return self.time_tracking_var.get().lower().replace(" ", "_")

    def get_target_filter(self) -> str:
        """Get selected target filter.

        Returns:
            'All' or specific target name
        """
        return self.target_filter_var.get()

    def update_target_filter_options(self, targets: list) -> None:
        """Update target filter combobox with available targets.

        Args:
            targets: List of target names
        """
        current = list(self.target_filter_combo["values"])
        new_values = ["All"] + sorted(targets)
        if current != new_values:
            self.target_filter_combo["values"] = new_values

