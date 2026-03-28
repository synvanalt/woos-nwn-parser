"""Target immunity panel widget for Woo's NWN Parser UI.

This module contains the ImmunityPanel widget that renders prepared
immunity display rows for each target and damage type.
"""

import re
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, Optional

from ...storage import DataStore
from ...services.queries import ImmunityDisplayRow, ImmunityQueryService
from ...parser import ParserSession
from ..formatters import damage_type_to_color, apply_tag_to_tree
from ..tree_refresh import FlatTreeRefreshCoordinator, FlatTreeRefreshState
from ..tooltips import TooltipManager
from .sorted_treeview import SortedTreeview


class ImmunityPanel(ttk.Frame):
    """Target immunity display panel.

    Manages:
    - Target selection via combobox
    - Parse Immunities toggle checkbox
    - Treeview showing damage type immunity data
    - Presentation and incremental refresh of prepared immunity display rows

    This is a reusable widget that can be placed in any notebook or frame.
    """

    # DISCLAIMER_TEXT = (
    #     "• Displayed immunity % can be overstated if target also has damage resistance/reduction\n"
    #     "• Damage and immunity absorbed lines are separated in logs and may be matched incorrectly"
    # )

    DISCLAIMER_TEXT = (
        "*Displayed immunity % may be overstated if target also has damage resistance or damage reduction"
    )

    def __init__(
        self,
        parent: ttk.Notebook,
        data_store: DataStore,
        parser: ParserSession,
        immunity_query_service: ImmunityQueryService,
        tooltip_manager: Optional[TooltipManager] = None,
        on_parse_immunity_changed: Optional[Callable[[bool], None]] = None,
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
        self.immunity_query_service = immunity_query_service
        self.tooltip_manager = tooltip_manager
        self.on_parse_immunity_changed = on_parse_immunity_changed
        self._tree_refresh_state = FlatTreeRefreshState(view_key=("", False))
        self.setup_ui()

    def setup_ui(self) -> None:
        """Setup the panel UI components."""
        # Target selector with Parse Immunities checkbox
        selector_frame = ttk.Frame(self)
        selector_frame.pack(fill="x", padx=(10, 10), pady=(0, 10))

        # Switcher to toggle parsing of immunity numbers
        self.parse_immunity_var = tk.BooleanVar(value=bool(self.parser.parse_immunity))

        def _on_toggle_immunity() -> None:
            val = bool(self.parse_immunity_var.get())
            self.parser.parse_immunity = val
            if self.on_parse_immunity_changed is not None:
                self.on_parse_immunity_changed(val)
            self.refresh_display()

        self.parse_immunity_toggle = ttk.Checkbutton(
            selector_frame,
            text="Parse Immunities",
            variable=self.parse_immunity_var,
            command=_on_toggle_immunity,
            style="Switch.TCheckbutton",
        )
        self.parse_immunity_toggle.pack(side="left", padx=0, pady=0)

        def _on_target_selected(event: tk.Event) -> None:
            """Handle target selection change."""
            selected = self.target_combo.get()
            if selected:
                self.refresh_target_details(selected)

        self.target_combo = ttk.Combobox(selector_frame, state="readonly", width=30)
        self.target_combo.pack(side="right", padx=5, fill="x", expand=False)
        self.target_combo.bind("<<ComboboxSelected>>", _on_target_selected)
        self.select_target_label = ttk.Label(selector_frame, text="Select Target:")
        self.select_target_label.pack(side="right", padx=5)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side="right", fill="y")

        # Treeview for displaying damage type breakdown
        columns = ("Damage Type", "Max Damage", "Absorbed", "Immunity %*", "Matched Samples")
        self.tree = SortedTreeview(
            tree_frame, columns=columns, show="headings", yscrollcommand=scrollbar.set
        )

        for col in columns:
            if col == "Damage Type":
                self.tree.column(col, width=140)
            elif col == "Max Damage":
                self.tree.column(col, width=110)
            elif col == "Absorbed":
                self.tree.column(col, width=110)
            elif col == "Immunity %*":
                self.tree.column(col, width=110)
            elif col == "Matched Samples":
                self.tree.column(col, width=110)

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
        self._tree_refresh = FlatTreeRefreshCoordinator(self.tree)
        self._register_tooltips()

    def _register_tooltips(self) -> None:
        """Register static tooltips for user-facing controls."""
        if self.tooltip_manager is None:
            return
        self.tooltip_manager.register(
            self.parse_immunity_toggle,
            "Parse damage immunity log lines to estimate immunity percentages per damage type",
        )
        self.tooltip_manager.register_many(
            [self.select_target_label, self.target_combo],
            "Choose which target to inspect for immunity and absorbed-damage details",
        )

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
        uses_store_query = self.immunity_query_service.supports_store_version_fast_path
        natural_order = self._is_natural_order_active()
        if self._tree_refresh.can_skip_refresh(
            self._tree_refresh_state,
            current_version=current_version,
            item_ids_present=bool(self._tree_refresh_state.item_ids),
            natural_order_active=natural_order,
            require_natural_order=True,
            view_key=view_key,
        ):
            return

        rows = self.immunity_query_service.get_target_immunity_display_rows(
            target,
            bool(self.parser.parse_immunity),
        )
        order_token = tuple(row.damage_type for row in rows)
        new_rows = {
            row.damage_type: (
                row.damage_type,
                row.max_damage_display,
                row.absorbed_display,
                row.immunity_pct_display,
                row.samples_display,
            )
            for row in rows
        }
        new_row_tokens = dict(new_rows)
        current_target = ""
        if isinstance(self._tree_refresh_state.view_key, tuple) and self._tree_refresh_state.view_key:
            current_target = str(self._tree_refresh_state.view_key[0])

        needs_full_refresh = (
            current_target != target
            or not self._tree_refresh_state.item_ids
            or set(self._tree_refresh_state.row_tokens.keys()) != set(new_rows.keys())
        )
        changed_damage_types = {
            damage_type
            for damage_type, row_token in new_row_tokens.items()
            if row_token != self._tree_refresh_state.row_tokens.get(damage_type)
        }

        if (
            not needs_full_refresh
            and self._tree_refresh_state.view_key == view_key
            and order_token == self._tree_refresh_state.order_token
            and not changed_damage_types
        ):
            if (
                current_version != self._tree_refresh_state.last_refresh_version
                and not natural_order
                and self.tree._last_sorted_col
            ):
                self.tree.apply_current_sort()
            self._tree_refresh_state.view_key = view_key
            self._tree_refresh_state.row_tokens = new_row_tokens
            self._tree_refresh_state.order_token = order_token
            self._tree_refresh_state.last_refresh_version = current_version
            self._tree_refresh_state.last_refresh_used_store_query = uses_store_query
            return

        if needs_full_refresh:
            self._full_refresh(target, new_rows, natural_order)
        else:
            rebuilt = self._incremental_refresh(
                rows,
                new_rows,
                changed_damage_types,
                natural_order,
            )
            if rebuilt:
                self._full_refresh(target, new_rows, natural_order)

        self._tree_refresh_state.view_key = view_key
        self._tree_refresh_state.row_tokens = new_row_tokens
        self._tree_refresh_state.order_token = order_token
        self._tree_refresh_state.last_refresh_version = current_version
        self._tree_refresh_state.last_refresh_used_store_query = uses_store_query

    def _is_natural_order_active(self) -> bool:
        """Return whether the active tree sort matches store immunity order."""
        return self.tree._last_sorted_col == "Damage Type" and not self.tree._sort_reverse

    def _full_refresh(self, target: str, new_rows: Dict[str, tuple], natural_order: bool) -> None:
        """Rebuild the tree when target or damage-type structure changes."""
        ordered_damage_types = list(new_rows.keys())

        def _insert_row(damage_type: str) -> str:
            tag_name = f"dt_{re.sub(r'[^0-9a-zA-Z]+', '_', damage_type.lower())}"
            color = damage_type_to_color(damage_type)
            apply_tag_to_tree(self.tree, tag_name, color)
            return self.tree.insert(
                "",
                "end",
                values=new_rows[damage_type],
                tags=(tag_name,),
            )

        self._tree_refresh.full_refresh(
            ordered_keys=ordered_damage_types,
            insert_row=_insert_row,
            state=self._tree_refresh_state,
            natural_order_active=natural_order,
        )

    def _incremental_refresh(
        self,
        rows: list[ImmunityDisplayRow],
        new_rows: Dict[str, tuple],
        changed_damage_types: set[str],
        natural_order: bool,
    ) -> bool:
        """Update existing immunity rows without rebuilding the tree."""
        rebuilt = self._tree_refresh.incremental_refresh(
            ordered_keys=[row.damage_type for row in rows],
            row_values_by_key=new_rows,
            changed_keys=changed_damage_types,
            state=self._tree_refresh_state,
            natural_order_active=natural_order,
        )
        return rebuilt

    def update_target_list(self, targets: list) -> None:
        """Update the target selector combobox.

        Args:
            targets: List of target names
        """
        if tuple(self.target_combo.cget("values")) != tuple(targets):
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
        """Reset panel refresh state and clear query-side immunity row caches."""
        self.immunity_query_service.clear_caches()
        self._tree_refresh_state = FlatTreeRefreshState(view_key=("", False))
