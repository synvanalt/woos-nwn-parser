"""Sortable Treeview widget with column header click sorting.

This module provides a SortedTreeview class that extends ttk.Treeview
with the ability to sort data by clicking on column headers.
"""

import re
from typing import Optional
import tkinter as tk
from tkinter import ttk


class SortedTreeview(ttk.Treeview):
    """A Treeview that can be sorted by clicking column headers.

    Features:
    - Click column headers to sort ascending/descending
    - Visual indicators (↑/↓) show current sort direction
    - Automatic numeric vs string detection for optimal sorting
    - Preserves selection during sorting
    - High performance with O(n log n) sorting
    """

    def __init__(self, master, **kwargs):
        """Initialize the sortable treeview.

        Args:
            master: Parent widget
            **kwargs: Standard Treeview arguments including 'columns'
        """
        super().__init__(master, **kwargs)
        self.column_names = {col: col for col in kwargs.get("columns", [])}
        self._last_sorted_col: Optional[str] = None
        self._sort_reverse = False

        # Bind header clicks for all columns
        for col in self.column_names:
            self.heading(col, text=col, command=lambda c=col: self.sort_column(c))

    _RANGE_PATTERN = re.compile(
        r"^(?:[<>]=?|[≤≥])?\s*(-?\d+(?:\.\d+)?)\s*-\s*(?:[<>]=?|[≤≥])?\s*(-?\d+(?:\.\d+)?)$"
    )
    _SINGLE_PATTERN = re.compile(r"^(?:[<>]=?|[≤≥])?\s*(-?\d+(?:\.\d+)?)$")
    _NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")

    @classmethod
    def _parse_numeric_sort_value(cls, val: object) -> float:
        """Parse display value into a numeric key for stable numeric sorting."""
        text = "" if val is None else str(val).strip()
        if not text or text == "-":
            return float("-inf")

        cleaned = text.replace(",", "").replace("%", "").strip()
        while cleaned.startswith("~"):
            cleaned = cleaned[1:].strip()

        if not cleaned or cleaned == "-":
            return float("-inf")

        range_match = cls._RANGE_PATTERN.fullmatch(cleaned)
        if range_match:
            first = float(range_match.group(1))
            second = float(range_match.group(2))
            return max(first, second)

        single_match = cls._SINGLE_PATTERN.fullmatch(cleaned)
        if single_match:
            return float(single_match.group(1))

        # Last-resort numeric extraction for values like "⚠45"
        numbers = cls._NUMBER_PATTERN.findall(cleaned)
        if numbers:
            parsed = [float(num) for num in numbers]
            return max(parsed) if len(parsed) > 1 and "-" in cleaned else parsed[0]

        raise ValueError(f"Value is not numeric-sortable: {val!r}")

    def sort_column(self, col: str, reverse: Optional[bool] = None) -> None:
        """Sort the treeview by the specified column.

        Args:
            col: Column name to sort by
            reverse: If True, sort descending. If None, toggles direction.
        """
        # Determine sort direction
        if reverse is None:
            # Toggle if same column, otherwise ascending
            if self._last_sorted_col == col:
                reverse = not self._sort_reverse
            else:
                reverse = False

        # Save selection state by values (to restore after sorting)
        selected_values = []
        for item in self.selection():
            values = self.item(item, "values")
            if values:
                selected_values.append(tuple(values))

        # Extract data for sorting (only top-level items, ignore children)
        # Format: [(sort_value, item_id), ...]
        data = []
        for child in self.get_children(''):
            try:
                value = self.set(child, col)
                data.append((value, child))
            except tk.TclError:
                # Handle case where column doesn't exist
                continue

        # Sort with intelligent type detection
        if data:
            try:
                # Try numeric sort first
                # Remove common formatting: commas, %, and whitespace
                data.sort(key=lambda t: self._parse_numeric_sort_value(t[0]), reverse=reverse)
            except (ValueError, AttributeError):
                # Fallback to string sort
                data.sort(key=lambda t: str(t[0]).lower(), reverse=reverse)

        # Reorder items in the treeview
        for index, (val, child) in enumerate(data):
            self.move(child, '', index)

        # Restore selection
        if selected_values:
            items_to_select = []
            for child in self.get_children(''):
                values = self.item(child, "values")
                if values and tuple(values) in selected_values:
                    items_to_select.append(child)
            if items_to_select:
                self.selection_set(items_to_select)

        # Update heading indicators
        self._update_headings(col, reverse)
        self._last_sorted_col = col
        self._sort_reverse = reverse

    def _update_headings(self, sorted_col: str, reverse: bool) -> None:
        """Update column headings with sort direction indicators.

        Args:
            sorted_col: The column currently sorted
            reverse: True if sorted descending, False if ascending
        """
        for col, original_name in self.column_names.items():
            if col == sorted_col:
                arrow = " ↓" if reverse else " ↑"
                self.heading(col, text=original_name + arrow)
            else:
                # Reset other columns to have no arrows
                self.heading(col, text=original_name)

    def set_default_sort(self, col: str, reverse: bool = False) -> None:
        """Set the default sort column and direction with visual indicator.

        This sets an initial sort order and shows the sort arrow indicator.
        The sort will be applied when data is populated or apply_current_sort() is called.

        Args:
            col: Column name to sort by
            reverse: If True, sort descending
        """
        self._last_sorted_col = col
        self._sort_reverse = reverse
        # Show the visual indicator immediately
        self._update_headings(col, reverse)

    def apply_current_sort(self) -> None:
        """Reapply the current sort after data has been updated.

        Call this after inserting/updating items to maintain sort order.
        Only sorts if a column has been previously sorted by the user.
        Optimized to skip sorting if data is already in correct order.
        """
        if not self._last_sorted_col:
            return

        # Check if data is already in correct order (skip sorting if so)
        if self._is_already_sorted():
            return

        self.sort_column(self._last_sorted_col, self._sort_reverse)

    def _is_already_sorted(self) -> bool:
        """Check if the current data is already sorted correctly.

        Returns:
            True if data is already in the correct sort order
        """
        if not self._last_sorted_col:
            return True

        children = self.get_children('')
        if len(children) <= 1:
            return True  # 0 or 1 items are always sorted

        col = self._last_sorted_col
        reverse = self._sort_reverse

        # Extract values for sorting comparison
        values = []
        for child in children:
            try:
                value = self.set(child, col)
                values.append(value)
            except Exception:
                return False  # Can't determine, assume not sorted

        if not values:
            return True

        # Try to parse as numeric first
        try:
            parsed = [self._parse_numeric_sort_value(v) for v in values]

            # Check if already sorted
            if reverse:
                return all(parsed[i] >= parsed[i + 1] for i in range(len(parsed) - 1))
            else:
                return all(parsed[i] <= parsed[i + 1] for i in range(len(parsed) - 1))

        except (ValueError, AttributeError):
            # Fallback to string comparison
            str_values = [str(v).lower() for v in values]
            if reverse:
                return all(str_values[i] >= str_values[i + 1] for i in range(len(str_values) - 1))
            else:
                return all(str_values[i] <= str_values[i + 1] for i in range(len(str_values) - 1))

