"""Target immunity panel widget for Woo's NWN Parser UI.

This module contains the ImmunityPanel widget that displays immunity
tracking and percentage calculations for each target and damage type.
"""

import re
import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional

from ...storage import DataStore
from ...parser import LogParser
from ...utils import calculate_immunity_percentage
from ..formatters import damage_type_to_color, apply_tag_to_tree


class ImmunityPanel(ttk.Frame):
    """Target immunity display panel.

    Manages:
    - Target selection via combobox
    - Parse Immunities toggle checkbox
    - Treeview showing damage type immunity data
    - Immunity percentage calculations and caching

    This is a reusable widget that can be placed in any notebook or frame.
    """

    def __init__(
        self,
        parent: ttk.Notebook,
        data_store: DataStore,
        parser: LogParser,
    ) -> None:
        """Initialize the immunity panel.

        Args:
            parent: Parent notebook widget
            data_store: Reference to the data store
            parser: Reference to the log parser
        """
        super().__init__(parent, padding="10")
        self.data_store = data_store
        self.parser = parser
        self.immunity_pct_cache: Dict[str, Dict[str, Optional[int]]] = {}
        self.setup_ui()

    def setup_ui(self) -> None:
        """Setup the panel UI components."""
        # Target selector with Parse Immunities checkbox
        selector_frame = ttk.Frame(self)
        selector_frame.pack(fill="x", padx=(10, 10), pady=(8, 10))

        # Switcher to toggle parsing of immunity numbers
        self.parse_immunity_var = tk.BooleanVar(value=False)

        def _on_toggle_immunity() -> None:
            val = bool(self.parse_immunity_var.get())
            self.parser.parse_immunity = val
            # Refresh the display when Parse Immunities is toggled
            self.refresh_display()

        ttk.Checkbutton(
            selector_frame,
            text="Parse Immunities",
            variable=self.parse_immunity_var,
            command=_on_toggle_immunity,
            style="Switch.TCheckbutton",
        ).pack(side="left", padx=0, pady=0)

        def _on_target_selected(event: tk.Event) -> None:
            """Handle target selection change."""
            selected = self.target_combo.get()
            if selected:
                self.refresh_target_details(selected)

        self.target_combo = ttk.Combobox(selector_frame, state="readonly", width=30)
        self.target_combo.pack(side="right", padx=5, fill="x", expand=False)
        self.target_combo.bind("<<ComboboxSelected>>", _on_target_selected)
        ttk.Label(selector_frame, text="Select Target:").pack(side="right", padx=5)

        # Scrollbar
        scrollbar = ttk.Scrollbar(self)
        scrollbar.pack(side="right", fill="y")

        # Treeview for displaying damage type breakdown
        columns = ("Damage Type", "Max Damage", "Absorbed", "Immunity %", "Samples")
        self.tree = ttk.Treeview(
            self, columns=columns, show="headings", yscrollcommand=scrollbar.set
        )

        for col in columns:
            self.tree.heading(col, text=col)
            if col == "Damage Type":
                self.tree.column(col, width=140)
            elif col == "Max Damage":
                self.tree.column(col, width=120)
            elif col == "Absorbed":
                self.tree.column(col, width=120)
            elif col == "Immunity %":
                self.tree.column(col, width=120)
            elif col == "Samples":
                self.tree.column(col, width=80)

        self.tree.pack(fill="both", expand=True)
        scrollbar.config(command=self.tree.yview)

    def refresh_target_details(self, target: str) -> None:
        """Display detailed resist data for selected target.

        Args:
            target: Name of the target to display details for
        """
        # Save the currently selected damage types
        selected_damage_types = set()
        for item in self.tree.selection():
            values = self.tree.item(item, "values")
            if values and len(values) > 0:
                selected_damage_types.add(values[0])  # Damage type is first column

        # Clear existing data
        self.tree.delete(*self.tree.get_children())

        # Initialize cache for this target if needed
        if target not in self.immunity_pct_cache:
            self.immunity_pct_cache[target] = {}

        # Get resist data (damage types with immunity records)
        # Returns: (damage_type, max_damage, immunity_absorbed, sample_count)
        # where max_damage and immunity_absorbed are from the same hit
        resists = self.data_store.get_target_resists(target)
        resist_dict = {
            damage_type: (max_damage, immunity_absorbed, sample_count)
            for damage_type, max_damage, immunity_absorbed, sample_count in resists
        }

        # Get all damage types for this target from events (whether or not they have immunity)
        all_damage_types_for_target = set()
        for event in self.data_store.events:
            if event.target == target:
                all_damage_types_for_target.add(event.damage_type)

        # Combine: use all damage types found, filling in immunity data where available
        all_damage_types = sorted(all_damage_types_for_target)

        # Track items to restore selection
        items_to_select = []

        for damage_type in all_damage_types:
            tag_name = f"dt_{re.sub(r'[^0-9a-zA-Z]+', '_', damage_type.lower())}"
            color = damage_type_to_color(damage_type)
            apply_tag_to_tree(self.tree, tag_name, color)

            # Get immunity data if available, otherwise use defaults
            # resist_dict values are: (max_damage, immunity_absorbed, sample_count) - all coupled from same hit
            if damage_type in resist_dict:
                max_damage_from_immunity, immunity_absorbed, sample_count = resist_dict[damage_type]
            else:
                max_damage_from_immunity = 0
                immunity_absorbed = 0
                sample_count = 0

            # For immunity percentage calculation, we MUST use the coupled data from immunity_data
            # (max_damage_from_immunity and immunity_absorbed are from the same hit)
            #
            # For display purposes:
            # - When Parse Immunities is enabled: show the coupled max_damage from immunity tracking
            # - When disabled: fall back to showing max damage from all events
            if self.parser.parse_immunity and max_damage_from_immunity > 0:
                max_damage = max_damage_from_immunity
            else:
                # Fall back to max damage from events for display when immunity parsing disabled
                max_damage = self.data_store.get_max_damage_from_events_for_target_and_type(
                    target, damage_type
                )

            # Format the display strings
            max_damage_display = str(max_damage) if max_damage > 0 else "-"
            absorbed_display = str(immunity_absorbed) if immunity_absorbed > 0 else "-"
            samples_display = str(sample_count) if sample_count > 0 else "-"

            # Calculate and cache immunity percentage
            immunity_pct_display = "-"

            # Check if we have a cached value for this damage type
            if damage_type in self.immunity_pct_cache[target]:
                cached_pct = self.immunity_pct_cache[target][damage_type]
                if cached_pct is not None:
                    immunity_pct_display = f"{cached_pct}%"

            # Update cache if Parse Immunities is enabled
            if self.parser.parse_immunity and max_damage > 0 and immunity_absorbed > 0:
                immunity_pct = calculate_immunity_percentage(max_damage, immunity_absorbed)
                if immunity_pct is not None:
                    immunity_pct_display = f"{immunity_pct}%"
                    self.immunity_pct_cache[target][damage_type] = immunity_pct
                else:
                    self.immunity_pct_cache[target][damage_type] = None

            # Display in simplified column format
            item_id = self.tree.insert(
                "",
                "end",
                values=(damage_type, max_damage_display, absorbed_display, immunity_pct_display, samples_display),
                tags=(tag_name,),
            )

            # Check if this damage type should be selected
            if damage_type in selected_damage_types:
                items_to_select.append(item_id)

        # Restore selection
        if items_to_select:
            self.tree.selection_set(items_to_select)

    def update_target_list(self, targets: list) -> None:
        """Update the target selector combobox.

        Args:
            targets: List of target names
        """
        self.target_combo["values"] = targets
        if targets and not self.target_combo.get():
            self.target_combo.current(0)
            self.refresh_target_details(targets[0])

    def get_selected_target(self) -> str:
        """Get the currently selected target.

        Returns:
            Target name or empty string if none selected
        """
        return self.target_combo.get()

    def refresh_display(self) -> None:
        """Refresh the display with the currently selected target.

        This can be called externally when data changes to refresh the panel.
        Directly refreshes the target details without throttling.
        """
        selected = self.target_combo.get()
        if selected:
            self.refresh_target_details(selected)

    def clear_cache(self) -> None:
        """Clear the immunity percentage cache.

        Called when data is reset to ensure old cached values don't persist.
        """
        self.immunity_pct_cache.clear()

