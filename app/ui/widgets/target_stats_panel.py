"""Target stats panel widget for Woo's NWN Parser UI."""

from typing import Any, Optional
from tkinter import ttk

from ...storage import DataStore
from ...services.queries import TargetSummaryQueryService, TargetSummaryRow
from ..tree_refresh import FlatTreeRefreshCoordinator, FlatTreeRefreshState
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
        self._tree_refresh_state = FlatTreeRefreshState()
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
        self._tree_refresh = FlatTreeRefreshCoordinator(self.tree)

    def refresh(self) -> None:
        """Refresh the target stats display with current data."""
        current_version = self.data_store.version
        uses_store_query = self._can_use_store_version_fast_path()
        natural_order = self._is_natural_order_active()
        if self._tree_refresh.can_skip_refresh(
            self._tree_refresh_state,
            current_version=current_version,
            item_ids_present=bool(self._tree_refresh_state.item_ids),
            natural_order_active=natural_order,
            require_natural_order=True,
        ):
            return

        summary_data = self.target_summary_query_service.get_all_targets_summary()
        order_token = tuple(item.target for item in summary_data)
        new_rows = {
            item.target: self._build_row_values(item)
            for item in summary_data
        }
        new_row_tokens = {
            target: self._build_row_token(row_values)
            for target, row_values in new_rows.items()
        }

        current_targets = set(self._tree_refresh_state.row_tokens.keys())
        new_targets = set(new_rows.keys())

        needs_full_refresh = (
            not self._tree_refresh_state.item_ids or
            current_targets != new_targets
        )

        changed_targets = {
            target
            for target, row_token in new_row_tokens.items()
            if row_token != self._tree_refresh_state.row_tokens.get(target)
        }

        if (
            not needs_full_refresh
            and order_token == self._tree_refresh_state.order_token
            and not changed_targets
        ):
            self._tree_refresh_state.row_tokens = new_row_tokens
            self._tree_refresh_state.order_token = order_token
            self._tree_refresh_state.last_refresh_version = current_version
            self._tree_refresh_state.last_refresh_used_store_query = uses_store_query
            return

        if needs_full_refresh:
            self._full_refresh(summary_data, natural_order)
        else:
            rebuilt = self._incremental_refresh(
                summary_data,
                new_rows,
                changed_targets,
                natural_order,
            )
            if rebuilt:
                self._full_refresh(summary_data, natural_order)

        self._tree_refresh_state.row_tokens = new_row_tokens
        self._tree_refresh_state.order_token = order_token
        self._tree_refresh_state.last_refresh_version = current_version
        self._tree_refresh_state.last_refresh_used_store_query = uses_store_query

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

    def _build_row_values(self, item: TargetSummaryRow) -> tuple[Any, ...]:
        """Build the rendered row values for one target summary."""
        return (
            item.target,
            item.ab,
            item.ac,
            item.fortitude,
            item.reflex,
            item.will,
            item.damage_taken,
        )

    def _build_row_token(self, row_values: tuple[Any, ...]) -> tuple[Any, ...]:
        """Build a stable token for row change detection."""
        return row_values

    def clear_cache(self) -> None:
        """Clear cached row and tree state to force a full refresh next time."""
        self._tree_refresh_state = FlatTreeRefreshState()

    def _full_refresh(self, summary_data: list[TargetSummaryRow], natural_order: bool) -> None:
        """Rebuild the tree when targets are added, removed, or reordered."""
        ordered_targets = [item.target for item in summary_data]
        row_values_by_target = {
            item.target: self._build_row_values(item)
            for item in summary_data
        }
        self._tree_refresh.full_refresh(
            ordered_keys=ordered_targets,
            insert_row=lambda target: self.tree.insert("", "end", values=row_values_by_target[target]),
            state=self._tree_refresh_state,
            natural_order_active=natural_order,
        )

    def _incremental_refresh(
        self,
        summary_data: list[TargetSummaryRow],
        new_rows: dict,
        changed_targets: set[str],
        natural_order: bool,
    ) -> bool:
        """Update existing rows without rebuilding the whole tree."""
        rebuilt = self._tree_refresh.incremental_refresh(
            ordered_keys=[item.target for item in summary_data],
            row_values_by_key=new_rows,
            changed_keys=changed_targets,
            state=self._tree_refresh_state,
            natural_order_active=natural_order,
        )
        return rebuilt
