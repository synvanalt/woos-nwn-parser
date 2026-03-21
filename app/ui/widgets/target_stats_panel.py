"""Target stats panel widget for Woo's NWN Parser UI.

This module contains the TargetStatsPanel widget that displays target
statistics including AC, AB, and save values.
"""

from typing import Any, Optional
from tkinter import ttk

from ...storage import DataStore
from ...services.queries import TargetSummaryQueryService
from ..tooltips import TooltipManager
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
        target_summary_query_service: TargetSummaryQueryService,
        tooltip_manager: Optional[TooltipManager] = None,
    ) -> None:
        """Initialize the target stats panel.

        Args:
            parent: Parent notebook widget
            data_store: Reference to the data store
            target_summary_query_service: Read-side query service for target rows
        """
        super().__init__(parent, padding="10")
        self.data_store = data_store
        self.target_summary_query_service = target_summary_query_service
        self.tooltip_manager = tooltip_manager
        self._cached_rows: dict = {}
        self._item_ids: dict = {}
        self._cached_row_tokens: dict[str, tuple[Any, ...]] = {}
        self._cached_order_token: tuple[str, ...] = ()
        self._last_refresh_version: int = -1
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
        current_version = self.data_store.version
        if (
            self._can_use_store_version_fast_path()
            and self._last_refresh_version == current_version
            and self._item_ids
            and self._is_natural_order_active()
        ):
            return

        summary_data = self.target_summary_query_service.get_all_targets_summary()
        natural_order = self._is_natural_order_active()
        order_token = tuple(item["target"] for item in summary_data)
        new_rows = {
            item["target"]: self._build_row_values(item)
            for item in summary_data
        }
        new_row_tokens = {
            target: self._build_row_token(row_values)
            for target, row_values in new_rows.items()
        }

        current_targets = set(self._cached_row_tokens.keys())
        new_targets = set(new_rows.keys())

        needs_full_refresh = (
            not self._item_ids or
            current_targets != new_targets
        )

        changed_targets = {
            target
            for target, row_token in new_row_tokens.items()
            if row_token != self._cached_row_tokens.get(target)
        }

        if (
            not needs_full_refresh
            and order_token == self._cached_order_token
            and not changed_targets
        ):
            self._cached_row_tokens = new_row_tokens
            self._cached_order_token = order_token
            self._last_refresh_version = current_version
            return

        if needs_full_refresh:
            self._full_refresh(summary_data)
        else:
            self._incremental_refresh(summary_data, new_rows, changed_targets, natural_order)

        self._cached_row_tokens = new_row_tokens
        self._cached_order_token = order_token
        self._last_refresh_version = current_version

    def _can_use_store_version_fast_path(self) -> bool:
        """Return whether refresh data is sourced from the live store method."""
        service_method = getattr(self.target_summary_query_service, "get_all_targets_summary", None)
        return (
            getattr(service_method, "__self__", None) is self.target_summary_query_service
            and getattr(service_method, "__func__", None)
            is TargetSummaryQueryService.get_all_targets_summary
        )

    def _is_natural_order_active(self) -> bool:
        """Return whether the active tree sort matches store target order."""
        return self.tree._last_sorted_col == "Target" and not self.tree._sort_reverse

    def _build_row_values(self, item: dict[str, Any]) -> tuple[Any, ...]:
        """Build the rendered row values for one target summary."""
        return (
            item["target"],
            item["ab"],
            item["ac"],
            item["fortitude"],
            item["reflex"],
            item["will"],
            item["damage_taken"],
        )

    def _build_row_token(self, row_values: tuple[Any, ...]) -> tuple[Any, ...]:
        """Build a stable token for row change detection."""
        return row_values

    def clear_cache(self) -> None:
        """Clear cached row and tree state to force a full refresh next time."""
        self._cached_rows.clear()
        self._item_ids.clear()
        self._cached_row_tokens.clear()
        self._cached_order_token = ()
        self._last_refresh_version = -1

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
                row_values = self._build_row_values(item)
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
            if self.tree._last_sorted_col and not self._is_natural_order_active():
                self.tree.apply_current_sort()

        finally:
            # Restore visual updates
            self.tree.configure(show=original_show)

        # Restore selection (after show is restored)
        if items_to_select:
            self.tree.selection_set(items_to_select)

        self._cached_rows = {
            item["target"]: self._build_row_values(item)
            for item in summary_data
        }

    def _incremental_refresh(
        self,
        summary_data: list[dict],
        new_rows: dict,
        changed_targets: set[str],
        natural_order: bool,
    ) -> None:
        """Update existing rows without rebuilding the whole tree."""
        known_items = set(self.tree.get_children())
        for item in summary_data:
            target = item["target"]
            if target not in changed_targets:
                continue
            row_values = new_rows[target]
            item_id = self._item_ids.get(target)
            if item_id not in known_items:
                self._full_refresh(summary_data)
                return
            if item_id:
                self.tree.item(item_id, values=row_values)

        if natural_order:
            for index, item in enumerate(summary_data):
                item_id = self._item_ids.get(item["target"])
                if item_id not in known_items:
                    self._full_refresh(summary_data)
                    return
                if item_id:
                    self.tree.move(item_id, "", index)

        self._cached_rows = new_rows

        if not natural_order and self.tree._last_sorted_col:
            self.tree.apply_current_sort()
