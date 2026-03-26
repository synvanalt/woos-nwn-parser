"""DPS display panel widget for Woo's NWN Parser UI.

This module contains the DPSPanel widget that displays DPS calculations
with time tracking modes and target filtering.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable, Optional

from ...storage import DataStore
from ...services.queries import DpsQueryService, DpsRow
from ..formatters import damage_type_to_color, apply_tag_to_tree, format_time
from ..tree_refresh import FlatTreeRefreshCoordinator, FlatTreeRefreshState
from ..tooltips import TooltipManager
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
        dps_query_service: DpsQueryService,
        tooltip_manager: Optional[TooltipManager] = None,
    ) -> None:
        """Initialize the DPS panel.

        Args:
            parent: Parent notebook widget
            data_store: Reference to the data store
            dps_query_service: Reference to the DPS query service
        """
        super().__init__(parent, padding="10")
        self.data_store = data_store
        self.dps_query_service = dps_query_service
        self.tooltip_manager = tooltip_manager
        # Cache for incremental updates
        self._cached_data: dict = {}  # character -> {dps, total_damage, hit_rate, time}
        self._cached_breakdown: dict = {}  # character -> [(damage_type, total_damage, dps), ...]
        self._item_ids: dict = {}  # character -> tree item id
        self._child_ids: dict = {}  # character -> {damage_type -> tree item id}
        self._cached_view_key = None
        self._cached_row_tokens: dict[str, tuple[Any, ...]] = {}
        self._cached_breakdown_tokens: dict[str, tuple[tuple[str, int], ...]] = {}
        self._cached_order_token: tuple[str, ...] = ()
        self._last_refresh_version: int = -1
        self._last_refresh_used_store_query: bool = False
        self._tree_refresh_state = FlatTreeRefreshState()
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
        self._tree_refresh = FlatTreeRefreshCoordinator(
            self.tree,
            selection_key_getter=lambda values: str(values[0]).strip() if values else None,
        )

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
        self.first_timestamp_label = ttk.Label(dps_controls_frame, text="First Timestamp:")
        self.first_timestamp_label.pack(side="left", padx=(5, 5))
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
        self.filter_target_label = ttk.Label(dps_controls_frame, text="Filter Target:")
        self.filter_target_label.pack(side="left", padx=(5, 5))
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
        self._register_tooltips()

    def _register_tooltips(self) -> None:
        """Register static tooltips for user-facing controls."""
        if self.tooltip_manager is None:
            return
        self.tooltip_manager.register_many(
            [self.first_timestamp_label, self.time_tracking_combo],
            "Choose how time is measured for DPS – 'Per Character' starts each attacker at their own first hit, 'Global' uses one shared session start time",
        )
        self.tooltip_manager.register_many(
            [self.filter_target_label, self.target_filter_combo],
            "Limit the DPS table to damage dealt to one target, or show all targets combined",
        )

    def refresh(self) -> None:
        """Refresh the DPS display with current data using incremental updates.

        Only updates rows that have changed, avoiding full tree rebuild.
        """
        selected_target = self.target_filter_var.get()
        view_key = (
            selected_target,
            self.dps_query_service.time_tracking_mode,
            self.dps_query_service.global_start_time,
        )
        current_version = self.data_store.version
        uses_store_query = self._can_use_store_version_fast_path()
        if self._tree_refresh.can_skip_refresh(
            self._tree_refresh_state,
            current_version=current_version,
            uses_store_query=uses_store_query,
            item_ids_present=bool(self._item_ids),
            view_key=view_key,
        ):
            return

        dps_list = self.dps_query_service.get_dps_display_data(target_filter=selected_target)
        natural_order = self._is_natural_order_active()
        order_token = tuple(item.character for item in dps_list)
        characters_in_view = set(order_token)

        current_characters = set(self._cached_row_tokens.keys())

        needs_full_refresh = (
            self._cached_view_key != view_key or  # Target filter / time mode changed
            current_characters != characters_in_view or  # Characters added/removed
            not self._item_ids  # First refresh
        )

        changed_characters: set[str] = set()
        breakdown_changed_characters: set[str] = set()
        new_row_tokens: dict[str, tuple[Any, ...]] = {}
        new_breakdown_tokens: dict[str, tuple[tuple[str, int], ...]] = {}

        for dps_info in dps_list:
            character = dps_info.character
            row_token = self._build_row_token(dps_info)
            breakdown_token = tuple(dps_info.breakdown_token)
            new_row_tokens[character] = row_token
            new_breakdown_tokens[character] = breakdown_token
            if row_token != self._cached_row_tokens.get(character):
                changed_characters.add(character)
            if breakdown_token != self._cached_breakdown_tokens.get(character):
                breakdown_changed_characters.add(character)

        if (
            not needs_full_refresh
            and order_token == self._cached_order_token
            and not changed_characters
            and not breakdown_changed_characters
        ):
            self._sync_refresh_state(
                view_key=view_key,
                row_tokens=new_row_tokens,
                breakdown_tokens=new_breakdown_tokens,
                order_token=order_token,
                current_version=current_version,
                uses_store_query=uses_store_query,
            )
            return

        new_data = {
            dps_info.character: self._build_row_cache_entry(dps_info)
            for dps_info in dps_list
        }

        if needs_full_refresh:
            new_breakdown = self._build_breakdown_cache(new_data.keys(), selected_target)
            # Full rebuild needed
            self._full_refresh(dps_list, new_data, new_breakdown)
            if not natural_order and self.tree._last_sorted_col:
                self.tree.apply_current_sort()
        else:
            new_breakdown = dict(self._cached_breakdown)
            breakdown_fetch_characters = changed_characters | breakdown_changed_characters
            new_data = dict(self._cached_data)

            for dps_info in dps_list:
                character = dps_info.character
                if character in changed_characters:
                    new_data[character] = self._build_row_cache_entry(dps_info)

            new_breakdown.update(
                self._build_breakdown_cache(breakdown_fetch_characters, selected_target)
            )
            # Incremental update - only update changed values
            rebuilt = self._incremental_refresh(
                dps_list=dps_list,
                new_data=new_data,
                new_breakdown=new_breakdown,
                changed_characters=changed_characters,
                natural_order=natural_order,
            )
            if rebuilt:
                self._full_refresh(dps_list, new_data, new_breakdown)
                if not natural_order and self.tree._last_sorted_col:
                    self.tree.apply_current_sort()

        self._sync_refresh_state(
            view_key=view_key,
            row_tokens=new_row_tokens,
            breakdown_tokens=new_breakdown_tokens,
            order_token=order_token,
            current_version=current_version,
            uses_store_query=uses_store_query,
        )

    def _can_use_store_version_fast_path(self) -> bool:
        """Return whether the service output is controlled by the store/version state."""
        service_method = getattr(self.dps_query_service, "get_dps_display_data", None)
        return (
            getattr(service_method, "__self__", None) is self.dps_query_service
            and getattr(service_method, "__func__", None)
            is DpsQueryService.get_dps_display_data
        )

    def _is_natural_order_active(self) -> bool:
        """Return whether the active tree sort matches the service's natural order."""
        return self.tree._last_sorted_col == "DPS" and self.tree._sort_reverse

    def _build_row_token(self, dps_info: DpsRow) -> tuple[Any, ...]:
        """Build a stable token for one top-level DPS row."""
        return (
            dps_info.dps,
            dps_info.total_damage,
            dps_info.hit_rate,
            dps_info.time_seconds,
        )

    def _build_row_cache_entry(self, dps_info: DpsRow) -> dict[str, Any]:
        """Build the cached row data for one character."""
        return {
            "dps": dps_info.dps,
            "total_damage": dps_info.total_damage,
            "hit_rate": dps_info.hit_rate,
            "time_seconds": dps_info.time_seconds,
            "breakdown_token": tuple(dps_info.breakdown_token),
        }

    def _build_breakdown_cache(self, characters: Iterable[str], selected_target: str) -> dict:
        """Build breakdown cache entries only for the requested characters."""
        requested_characters = list(characters)
        if not requested_characters:
            return {}

        breakdowns_by_character = self.dps_query_service.get_damage_type_breakdowns(
            requested_characters,
            selected_target,
        )
        breakdown_cache = {}
        for character in requested_characters:
            breakdown_cache[character] = [
                (d.damage_type, d.total_damage, d.dps)
                for d in breakdowns_by_character.get(character, [])
            ]
        return breakdown_cache

    def _full_refresh(self, dps_list: list[DpsRow], new_data: dict, new_breakdown: dict) -> None:
        """Perform a full tree rebuild when structure changes.

        Args:
            dps_list: List of DPS data dicts
            new_data: New data cache
            new_breakdown: New breakdown cache
        """
        # Save the expanded state of all nodes
        expanded_nodes = set()
        for item in self.tree.get_children():
            if self.tree.item(item, "open"):
                values = self.tree.item(item, "values")
                if values:
                    expanded_nodes.add(values[0])

        selected_keys = self._tree_refresh.capture_selection_keys()

        # Clear the tree and caches
        self._child_ids.clear()
        ordered_characters = [dps_info.character for dps_info in dps_list]
        dps_info_by_character = {
            dps_info.character: dps_info
            for dps_info in dps_list
        }

        def _insert_row(character: str) -> str:
            dps_info = dps_info_by_character[character]
            total_damage = dps_info.total_damage
            time_seconds = dps_info.time_seconds
            dps = dps_info.dps
            hit_rate = dps_info.hit_rate
            time_display = format_time(time_seconds)
            dps_display = f"{dps:.2f}"
            hit_rate_display = f"{hit_rate:.1f}%"

            parent_id = self.tree.insert(
                "",
                "end",
                text="",
                values=(character, dps_display, total_damage, hit_rate_display, time_display),
            )
            self._child_ids[character] = {}

            for damage_type, type_damage, type_dps in new_breakdown.get(character, []):
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

            if character in expanded_nodes:
                self.tree.item(parent_id, open=True)

            return parent_id

        self._tree_refresh.full_refresh(
            ordered_keys=ordered_characters,
            insert_row=_insert_row,
            state=self._tree_refresh_state,
            natural_order_active=True,
        )
        self._item_ids = self._tree_refresh_state.item_ids

        # Restore child-row selections after the top-level rebuild.
        child_items_to_select = []
        for damage_type in selected_keys:
            for child_ids in self._child_ids.values():
                child_id = child_ids.get(damage_type)
                if child_id:
                    child_items_to_select.append(child_id)
        if child_items_to_select:
            self.tree.selection_add(child_items_to_select)

        # Update caches
        self._cached_data = new_data
        self._cached_breakdown = new_breakdown

        # Update indicator images after refresh
        if hasattr(self.tree, "_update_indicators"):
            self.tree._update_indicators()

    def _incremental_refresh(
        self,
        dps_list: list[DpsRow],
        new_data: dict,
        new_breakdown: dict,
        changed_characters: set[str],
        natural_order: bool,
    ) -> bool:
        """Update only changed values without rebuilding the tree.

        Args:
            dps_list: Ordered DPS rows from the service
            new_data: New data for all characters
            new_breakdown: New breakdown data for all characters
            changed_characters: Characters with changed top-level row data
            natural_order: True if the current sort already matches service order
        """
        parent_rows = {}
        for dps_info in dps_list:
            character = dps_info.character
            row_data = new_data.get(character, self._cached_data.get(character, {}))
            parent_rows[character] = (
                character,
                f"{row_data.get('dps', dps_info.dps):.2f}",
                row_data.get("total_damage", dps_info.total_damage),
                f"{row_data.get('hit_rate', dps_info.hit_rate):.1f}%",
                format_time(row_data.get("time_seconds", dps_info.time_seconds)),
            )
        rebuilt = self._tree_refresh.incremental_refresh(
            ordered_keys=[dps_info.character for dps_info in dps_list],
            row_values_by_key=parent_rows,
            changed_keys=changed_characters,
            state=self._tree_refresh_state,
            natural_order_active=natural_order,
        )
        if rebuilt:
            return True

        for dps_info in dps_list:
            character = dps_info.character
            data = new_data.get(character, self._cached_data.get(character, {}))
            parent_id = self._item_ids.get(character)

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
        self._item_ids = self._tree_refresh_state.item_ids
        return False

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
        self._cached_view_key = None
        self._cached_row_tokens.clear()
        self._cached_breakdown_tokens.clear()
        self._cached_order_token = ()
        self._last_refresh_version = -1
        self._last_refresh_used_store_query = False
        self._tree_refresh_state = FlatTreeRefreshState()

    def reset_target_filter(self) -> None:
        """Reset the target filter selection to default 'All'."""
        self.target_filter_var.set("All")

    def _sync_refresh_state(
        self,
        *,
        view_key: tuple[object, ...],
        row_tokens: dict[str, tuple[Any, ...]],
        breakdown_tokens: dict[str, tuple[tuple[str, int], ...]],
        order_token: tuple[str, ...],
        current_version: int,
        uses_store_query: bool,
    ) -> None:
        """Keep legacy cache fields aligned with shared refresh state."""
        self._cached_view_key = view_key
        self._cached_row_tokens = row_tokens
        self._cached_breakdown_tokens = breakdown_tokens
        self._cached_order_token = order_token
        self._last_refresh_version = current_version
        self._last_refresh_used_store_query = uses_store_query
        self._tree_refresh_state.view_key = view_key
        self._tree_refresh_state.row_tokens = row_tokens
        self._tree_refresh_state.order_token = order_token
        self._tree_refresh_state.last_refresh_version = current_version
        self._tree_refresh_state.last_refresh_used_store_query = uses_store_query
        self._tree_refresh_state.item_ids = self._item_ids

