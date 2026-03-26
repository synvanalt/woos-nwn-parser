"""Shared helpers for treeview refresh behavior.

This module centralizes the repeated top-level row refresh flow used by
multiple panels while keeping widget-specific row rendering local.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from tkinter import ttk
from typing import Callable, Hashable


RowKey = str
RowValues = tuple[object, ...]
SelectionKeyGetter = Callable[[RowValues], str | None]
InsertRow = Callable[[RowKey], str]


@dataclass(slots=True)
class FlatTreeRefreshState:
    """Mutable refresh state for a flat top-level tree."""

    view_key: Hashable | None = None
    row_tokens: dict[RowKey, tuple[object, ...]] = field(default_factory=dict)
    order_token: tuple[RowKey, ...] = ()
    item_ids: dict[RowKey, str] = field(default_factory=dict)
    last_refresh_version: int = -1
    last_refresh_used_store_query: bool = False


class FlatTreeRefreshCoordinator:
    """Coordinate incremental vs full refreshes for flat tree rows."""

    def __init__(
        self,
        tree: ttk.Treeview,
        selection_key_getter: SelectionKeyGetter | None = None,
    ) -> None:
        self.tree = tree
        self._selection_key_getter = selection_key_getter or self._default_selection_key_getter

    def can_skip_refresh(
        self,
        state: FlatTreeRefreshState,
        *,
        current_version: int,
        uses_store_query: bool,
        item_ids_present: bool,
        natural_order_active: bool = True,
        require_natural_order: bool = False,
        view_key: Hashable | None = None,
    ) -> bool:
        """Return whether the refresh can short-circuit before querying rows."""
        if not (
            state.last_refresh_used_store_query
            and state.last_refresh_version == current_version
            and item_ids_present
        ):
            return False
        if view_key is not None and state.view_key != view_key:
            return False
        if require_natural_order and not natural_order_active:
            return False
        return True

    def capture_selection_keys(self) -> set[str]:
        """Capture selected row keys from the current tree selection."""
        selected_keys: set[str] = set()
        for item_id in self.tree.selection():
            values = self.tree.item(item_id, "values")
            if not values:
                continue
            selection_key = self._selection_key_getter(tuple(values))
            if selection_key is not None:
                selected_keys.add(selection_key)
        return selected_keys

    def full_refresh(
        self,
        *,
        ordered_keys: list[RowKey],
        insert_row: InsertRow,
        state: FlatTreeRefreshState,
        natural_order_active: bool,
    ) -> None:
        """Rebuild all top-level rows while preserving selection."""
        selected_keys = self.capture_selection_keys()
        original_show = self.tree.cget("show")
        self.tree.configure(show="")

        try:
            self.tree.delete(*self.tree.get_children())
            state.item_ids.clear()

            items_to_select: list[str] = []
            for row_key in ordered_keys:
                item_id = insert_row(row_key)
                state.item_ids[row_key] = item_id
                if row_key in selected_keys:
                    items_to_select.append(item_id)

            if self.tree._last_sorted_col and not natural_order_active:
                self.tree.apply_current_sort()
        finally:
            self.tree.configure(show=original_show)

        if items_to_select:
            self.tree.selection_set(items_to_select)

    def incremental_refresh(
        self,
        *,
        ordered_keys: list[RowKey],
        row_values_by_key: dict[RowKey, RowValues],
        changed_keys: set[RowKey],
        state: FlatTreeRefreshState,
        natural_order_active: bool,
    ) -> bool:
        """Update changed rows and optionally reapply order.

        Returns `True` when a stale item id forced the caller to fall back to a
        full rebuild.
        """
        known_items = set(self.tree.get_children())
        for row_key in ordered_keys:
            if row_key not in changed_keys:
                continue
            item_id = state.item_ids.get(row_key)
            if item_id not in known_items:
                return True
            if item_id:
                self.tree.item(item_id, values=row_values_by_key[row_key])

        if natural_order_active:
            for index, row_key in enumerate(ordered_keys):
                item_id = state.item_ids.get(row_key)
                if item_id not in known_items:
                    return True
                if item_id:
                    self.tree.move(item_id, "", index)

        if not natural_order_active and self.tree._last_sorted_col:
            self.tree.apply_current_sort()
        return False

    @staticmethod
    def _default_selection_key_getter(values: RowValues) -> str | None:
        """Return the first column as the selection identity by default."""
        if not values:
            return None
        return str(values[0])
