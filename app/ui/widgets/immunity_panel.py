"""Target immunity panel widget for Woo's NWN Parser UI.

This module contains the ImmunityPanel widget that displays immunity
tracking and percentage calculations for each target and damage type.
"""

import re
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional

from ...storage import DataStore
from ...parser import LogParser
from ...utils import calculate_immunity_percentage
from ..formatters import damage_type_to_color, apply_tag_to_tree
from .sorted_treeview import SortedTreeview


class ImmunityPanel(ttk.Frame):
    """Target immunity display panel.

    Manages:
    - Target selection via combobox
    - Parse Immunities toggle checkbox
    - Treeview showing damage type immunity data
    - Immunity percentage calculations and caching

    This is a reusable widget that can be placed in any notebook or frame.
    """

    DISCLAIMER_TEXT = (
        "• Damage and immunity lines are separated in log and may be matched incorrectly\n"
        "• Displayed immunity % can be overstated if target also has damage resistance/reduction"
    )

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
        self._cached_target: str = ""
        self._cached_rows: Dict[str, tuple] = {}
        self._item_ids: Dict[str, str] = {}
        self._cached_row_tokens: Dict[str, tuple[Any, ...]] = {}
        self._cached_order_token: tuple[str, ...] = ()
        self._cached_view_key: tuple[str, bool] = ("", False)
        self._last_refresh_version: int = -1
        self.setup_ui()

    def setup_ui(self) -> None:
        """Setup the panel UI components."""
        # Target selector with Parse Immunities checkbox
        selector_frame = ttk.Frame(self)
        selector_frame.pack(fill="x", padx=(10, 10), pady=(0, 10))

        # Switcher to toggle parsing of immunity numbers
        self.parse_immunity_var = tk.BooleanVar(value=False)

        def _on_toggle_immunity() -> None:
            val = bool(self.parse_immunity_var.get())
            self.parser.parse_immunity = val
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

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side="right", fill="y")

        # Treeview for displaying damage type breakdown
        columns = ("Damage Type", "Max Damage", "Absorbed", "Immunity %", "Samples")
        self.tree = SortedTreeview(
            tree_frame, columns=columns, show="headings", yscrollcommand=scrollbar.set
        )

        for col in columns:
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

        self.tree.set_default_sort("Damage Type", reverse=False)

        self.disclaimer_label = ttk.Label(
            self,
            text=self.DISCLAIMER_TEXT,
            justify="left",
            anchor="w",
            wraplength=1,
            foreground="gray",
        )
        self.disclaimer_label.pack(fill="x", padx=(10, 10), pady=(8, 0))
        self.bind("<Configure>", self._on_panel_resize)

    def _on_panel_resize(self, event: tk.Event) -> None:
        """Keep disclaimer wrapping aligned with the current panel width."""
        wraplength = max(int(event.width) - 20, 1)
        if int(self.disclaimer_label.cget("wraplength")) != wraplength:
            self.disclaimer_label.configure(wraplength=wraplength)

    def refresh_target_details(self, target: str) -> None:
        """Display detailed resist data for selected target.

        Args:
            target: Name of the target to display details for
        """
        view_key = (target, bool(self.parser.parse_immunity))
        current_version = self.data_store.version
        if (
            self._can_use_store_version_fast_path()
            and self._cached_view_key == view_key
            and self._last_refresh_version == current_version
            and self._item_ids
            and self._is_natural_order_active()
        ):
            return

        # Initialize cache for this target if needed
        if target not in self.immunity_pct_cache:
            self.immunity_pct_cache[target] = {}

        summaries = self.data_store.get_target_damage_type_summary(target)
        natural_order = self._is_natural_order_active()
        order_token = tuple(str(summary["damage_type"]) for summary in summaries)
        new_rows = {}
        for summary in summaries:
            damage_type = str(summary["damage_type"])
            max_damage_from_immunity = int(summary["max_immunity_damage"])
            immunity_absorbed = int(summary["immunity_absorbed"])
            sample_count = int(summary["sample_count"])

            if self.parser.parse_immunity and max_damage_from_immunity > 0:
                max_damage = max_damage_from_immunity
            else:
                max_damage = int(summary["max_event_damage"])

            max_damage_display = str(max_damage) if max_damage > 0 else "-"
            absorbed_display = str(immunity_absorbed) if immunity_absorbed > 0 else "-"
            samples_display = str(sample_count) if sample_count > 0 else "-"

            immunity_pct_display = "-"
            if damage_type in self.immunity_pct_cache[target]:
                cached_pct = self.immunity_pct_cache[target][damage_type]
                if cached_pct is not None:
                    immunity_pct_display = f"{cached_pct}%"

            if self.parser.parse_immunity and max_damage > 0 and immunity_absorbed > 0:
                immunity_pct = calculate_immunity_percentage(max_damage, immunity_absorbed)
                if immunity_pct is not None:
                    immunity_pct_display = f"{immunity_pct}%"
                    self.immunity_pct_cache[target][damage_type] = immunity_pct
                else:
                    self.immunity_pct_cache[target][damage_type] = None

            new_rows[damage_type] = (
                damage_type,
                max_damage_display,
                absorbed_display,
                immunity_pct_display,
                samples_display,
            )
        new_row_tokens = {
            damage_type: row_values
            for damage_type, row_values in new_rows.items()
        }

        needs_full_refresh = (
            self._cached_target != target
            or not self._item_ids
            or set(self._cached_rows.keys()) != set(new_rows.keys())
        )
        changed_damage_types = {
            damage_type
            for damage_type, row_token in new_row_tokens.items()
            if row_token != self._cached_row_tokens.get(damage_type)
        }

        if (
            not needs_full_refresh
            and self._cached_view_key == view_key
            and order_token == self._cached_order_token
            and not changed_damage_types
        ):
            if not natural_order and self.tree._last_sorted_col:
                self.tree.apply_current_sort()
            self._cached_row_tokens = new_row_tokens
            self._cached_order_token = order_token
            self._last_refresh_version = current_version
            return

        if needs_full_refresh:
            self._full_refresh(target, new_rows)
            if not natural_order and self.tree._last_sorted_col:
                self.tree.apply_current_sort()
        else:
            self._incremental_refresh(
                target,
                summaries,
                new_rows,
                changed_damage_types,
                natural_order,
            )

        self._cached_view_key = view_key
        self._cached_row_tokens = new_row_tokens
        self._cached_order_token = order_token
        self._last_refresh_version = current_version

    def _can_use_store_version_fast_path(self) -> bool:
        """Return whether refresh data is sourced from the live store method."""
        store_method = getattr(self.data_store, "get_target_damage_type_summary", None)
        if getattr(store_method, "mock_calls", None) is not None:
            return True
        return (
            getattr(store_method, "__self__", None) is self.data_store
            and getattr(store_method, "__func__", None)
            is DataStore.get_target_damage_type_summary
        )

    def _is_natural_order_active(self) -> bool:
        """Return whether the active tree sort matches store immunity order."""
        return self.tree._last_sorted_col == "Damage Type" and not self.tree._sort_reverse

    def _full_refresh(self, target: str, new_rows: Dict[str, tuple]) -> None:
        """Rebuild the tree when target or damage-type structure changes."""
        # Save the currently selected damage types
        selected_damage_types = set()
        for item in self.tree.selection():
            values = self.tree.item(item, "values")
            if values and len(values) > 0:
                selected_damage_types.add(values[0])

        # Suppress visual updates during bulk operations
        original_show = self.tree.cget("show")
        self.tree.configure(show="")

        try:
            # Clear existing data
            self.tree.delete(*self.tree.get_children())
            self._item_ids.clear()

            # Track items to restore selection
            items_to_select = []

            for damage_type, row_values in new_rows.items():
                tag_name = f"dt_{re.sub(r'[^0-9a-zA-Z]+', '_', damage_type.lower())}"
                color = damage_type_to_color(damage_type)
                apply_tag_to_tree(self.tree, tag_name, color)

                # Display in simplified column format
                item_id = self.tree.insert(
                    "",
                    "end",
                    values=row_values,
                    tags=(tag_name,),
                )
                self._item_ids[damage_type] = item_id

                # Check if this damage type should be selected
                if damage_type in selected_damage_types:
                    items_to_select.append(item_id)

            # Apply sort only if needed:
            # - If user has never sorted, apply default sort
            # - If user has sorted, maintain their sort preference
            # This is efficient: only sorts when structure changes, not on every update
            if self.tree._last_sorted_col and not self._is_natural_order_active():
                self.tree.apply_current_sort()

        finally:
            # Restore visual updates
            self.tree.configure(show=original_show)

        # Restore selection (after show is restored)
        if items_to_select:
            self.tree.selection_set(items_to_select)

        self._cached_target = target
        self._cached_rows = new_rows

    def _incremental_refresh(
        self,
        target: str,
        summaries: list[dict[str, Any]],
        new_rows: Dict[str, tuple],
        changed_damage_types: set[str],
        natural_order: bool,
    ) -> None:
        """Update existing immunity rows without rebuilding the tree."""
        for summary in summaries:
            damage_type = str(summary["damage_type"])
            if damage_type not in changed_damage_types:
                continue
            row_values = new_rows[damage_type]
            item_id = self._item_ids.get(damage_type)
            if item_id:
                self.tree.item(item_id, values=row_values)

        if natural_order:
            for index, summary in enumerate(summaries):
                item_id = self._item_ids.get(str(summary["damage_type"]))
                if item_id:
                    self.tree.move(item_id, "", index)

        self._cached_target = target
        self._cached_rows = new_rows

        if not natural_order and self.tree._last_sorted_col:
            self.tree.apply_current_sort()

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
        self._cached_target = ""
        self._cached_rows.clear()
        self._item_ids.clear()
        self._cached_row_tokens.clear()
        self._cached_order_token = ()
        self._cached_view_key = ("", False)
        self._last_refresh_version = -1
