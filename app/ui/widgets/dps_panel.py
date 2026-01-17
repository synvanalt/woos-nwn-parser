"""DPS display panel widget for Woo's NWN Parser UI.

This module contains the DPSPanel widget that displays DPS calculations
with time tracking modes and target filtering.
"""

import tkinter as tk
from tkinter import ttk

from ...storage import DataStore
from ...services import DPSCalculationService
from ..formatters import damage_type_to_color, apply_tag_to_tree, format_time
from .sorted_treeview import SortedTreeview


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
        # Cache for incremental updates
        self._cached_data: dict = {}  # character -> {dps, total_damage, hit_rate, time}
        self._cached_breakdown: dict = {}  # character -> [(damage_type, total_damage, dps), ...]
        self._item_ids: dict = {}  # character -> tree item id
        self._child_ids: dict = {}  # character -> {damage_type -> tree item id}
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
        self.tree = SortedTreeview(
            dps_treeview_frame,
            columns=dps_columns,
            show="tree headings",
            yscrollcommand=dps_scrollbar.set,
        )

        # Configure the tree column (shows expansion icons)
        self.tree.column("#0", width=25, minwidth=25, stretch=False)
        self.tree.heading("#0", text="")

        for col in dps_columns:
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

        # Set default sort by DPS descending (matches storage default)
        self.tree.set_default_sort("DPS", reverse=True)

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
        """Refresh the DPS display with current data using incremental updates.

        Only updates rows that have changed, avoiding full tree rebuild.
        """
        selected_target = self.target_filter_var.get()
        dps_list = self.dps_service.get_dps_display_data(target_filter=selected_target)

        # Build new data map
        new_data = {}
        new_breakdown = {}
        for dps_info in dps_list:
            character = dps_info["character"]
            new_data[character] = {
                'dps': dps_info["dps"],
                'total_damage': dps_info["total_damage"],
                'hit_rate': dps_info["hit_rate"],
                'time_seconds': dps_info["time_seconds"],
            }
            # Get breakdown for this character
            breakdown = self.dps_service.get_damage_type_breakdown(character, selected_target)
            new_breakdown[character] = [(d["damage_type"], d["total_damage"], d["dps"]) for d in breakdown]

        # Check if we need a full rebuild
        current_characters = set(self._cached_data.keys())
        new_characters = set(new_data.keys())

        needs_full_refresh = (
            current_characters != new_characters or  # Characters added/removed
            not self._item_ids  # First refresh
        )

        # If user is using the default sort (DPS descending), check if order changed
        if not needs_full_refresh and self.tree.get_children():
            if self.tree._last_sorted_col == "DPS" and self.tree._sort_reverse:
                # Quick O(n) check: compare tree order with dps_list order
                # Only valid when sorted by DPS descending (default)
                tree_order = [self.tree.item(item, "values")[0] for item in self.tree.get_children()]
                dps_list_order = [item["character"] for item in dps_list]
                needs_full_refresh = tree_order != dps_list_order

        if needs_full_refresh:
            # Full rebuild needed
            self._full_refresh(dps_list, new_data, new_breakdown, selected_target)
        else:
            # Incremental update - only update changed values
            self._incremental_refresh(new_data, new_breakdown, selected_target)

    def _full_refresh(self, dps_list: list, new_data: dict, new_breakdown: dict, selected_target: str) -> None:
        """Perform a full tree rebuild when structure changes.

        Args:
            dps_list: List of DPS data dicts
            new_data: New data cache
            new_breakdown: New breakdown cache
            selected_target: Currently selected target filter
        """
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
                char_name = values[0].strip()
                selected_characters.add(char_name)

        # Clear the tree and caches
        self.tree.delete(*self.tree.get_children())
        self._item_ids.clear()
        self._child_ids.clear()

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
            self._item_ids[character] = parent_id
            self._child_ids[character] = {}

            if character in selected_characters:
                items_to_select.append(parent_id)

            # Get damage type breakdown for this character
            breakdown = self.dps_service.get_damage_type_breakdown(character, selected_target)

            # Insert child rows for each damage type
            for damage_data in breakdown:
                damage_type = damage_data["damage_type"]
                type_damage = damage_data["total_damage"]
                type_dps = damage_data["dps"]

                color = damage_type_to_color(damage_type)
                tag = f"damage_type_{damage_type.replace(' ', '_').lower()}"
                apply_tag_to_tree(self.tree, tag, color)

                child_id = self.tree.insert(
                    parent_id,
                    "end",
                    text="",
                    values=(f"  {damage_type}", f"{type_dps:.2f}", type_damage, "", ""),
                    tags=(tag,),
                )
                self._child_ids[character][damage_type] = child_id

                if damage_type in selected_characters:
                    items_to_select.append(child_id)

            # Restore expanded state
            if character in expanded_nodes:
                self.tree.item(parent_id, open=True)

        # Restore selection
        if items_to_select:
            self.tree.selection_set(items_to_select)

        # Update caches
        self._cached_data = new_data
        self._cached_breakdown = new_breakdown

        # Update indicator images after refresh
        if hasattr(self.tree, "_update_indicators"):
            self.tree._update_indicators()

    def _incremental_refresh(self, new_data: dict, new_breakdown: dict, selected_target: str) -> None:
        """Update only changed values without rebuilding the tree.

        Args:
            new_data: New data for all characters
            new_breakdown: New breakdown data for all characters
            selected_target: Currently selected target filter
        """
        for character, data in new_data.items():
            cached = self._cached_data.get(character, {})

            # Check if parent row needs update
            if (data['dps'] != cached.get('dps') or
                data['total_damage'] != cached.get('total_damage') or
                data['hit_rate'] != cached.get('hit_rate') or
                data['time_seconds'] != cached.get('time_seconds')):

                # Update parent row values
                parent_id = self._item_ids.get(character)
                if parent_id:
                    time_display = format_time(data['time_seconds'])
                    dps_display = f"{data['dps']:.2f}"
                    hit_rate_display = f"{data['hit_rate']:.1f}%"

                    self.tree.item(
                        parent_id,
                        values=(character, dps_display, data['total_damage'], hit_rate_display, time_display)
                    )

            # Check if child rows need update
            new_bd = new_breakdown.get(character, [])
            cached_bd = self._cached_breakdown.get(character, [])

            # Convert to dicts for comparison
            new_bd_dict = {dt: (dmg, dps) for dt, dmg, dps in new_bd}
            cached_bd_dict = {dt: (dmg, dps) for dt, dmg, dps in cached_bd}

            # Check for new damage types or changed values
            if new_bd_dict != cached_bd_dict:
                parent_id = self._item_ids.get(character)
                if parent_id:
                    # Check if we need to add new damage types
                    existing_types = set(self._child_ids.get(character, {}).keys())
                    new_types = set(new_bd_dict.keys())

                    if existing_types != new_types:
                        # Structure changed - rebuild children
                        for child_id in self._child_ids.get(character, {}).values():
                            self.tree.delete(child_id)
                        self._child_ids[character] = {}

                        for dt, dmg, dps in new_bd:
                            color = damage_type_to_color(dt)
                            tag = f"damage_type_{dt.replace(' ', '_').lower()}"
                            apply_tag_to_tree(self.tree, tag, color)

                            child_id = self.tree.insert(
                                parent_id,
                                "end",
                                text="",
                                values=(f"  {dt}", f"{dps:.2f}", dmg, "", ""),
                                tags=(tag,),
                            )
                            self._child_ids[character][dt] = child_id
                    else:
                        # Just update values
                        for dt, dmg, dps in new_bd:
                            child_id = self._child_ids.get(character, {}).get(dt)
                            if child_id:
                                cached_dmg, cached_dps = cached_bd_dict.get(dt, (None, None))
                                if dmg != cached_dmg or dps != cached_dps:
                                    self.tree.item(
                                        child_id,
                                        values=(f"  {dt}", f"{dps:.2f}", dmg, "", "")
                                    )

        # Update caches
        self._cached_data = new_data
        self._cached_breakdown = new_breakdown

        # Reapply current sort if user has sorted by a column
        # (maintains user's sort preference after data updates)
        if self.tree._last_sorted_col and self.tree._last_sorted_col != "DPS":
            # Only reapply if user sorted by something other than DPS
            # (DPS is already sorted correctly from storage)
            self.tree.apply_current_sort()
        elif self.tree._last_sorted_col == "DPS" and not self.tree._sort_reverse:
            # User sorted DPS ascending (non-default)
            self.tree.apply_current_sort()

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

    def clear_cache(self) -> None:
        """Clear the cached data to force a full refresh on next update."""
        self._cached_data.clear()
        self._cached_breakdown.clear()
        self._item_ids.clear()
        self._child_ids.clear()

