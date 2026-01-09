"""DPS calculation service with time tracking support.

This module handles all DPS calculations and time tracking mode management.
Supports both 'by_character' and 'global' time tracking modes.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any

from ..storage import DataStore


class DPSCalculationService:
    """Calculate DPS with support for different time tracking modes.

    Time Tracking Modes:
    - 'by_character': DPS calculated per-character from their first attack
    - 'global': DPS for all characters calculated from a single start time

    This service is pure Python with no UI dependencies and is fully testable.
    """

    def __init__(self, data_store: DataStore) -> None:
        """Initialize the DPS calculation service.

        Args:
            data_store: Reference to the data store
        """
        self.data_store = data_store
        self.time_tracking_mode = "by_character"
        self.global_start_time: Optional[datetime] = None

    def set_time_tracking_mode(self, mode: str) -> None:
        """Set time tracking mode.

        When switching to global mode, automatically initializes global_start_time
        if not already set.

        Args:
            mode: 'by_character' or 'global'

        Raises:
            ValueError: If mode is not valid
        """
        if mode not in ('by_character', 'global'):
            raise ValueError(f"Invalid mode: {mode}")

        self.time_tracking_mode = mode

        # Initialize global start time if switching to global mode
        if mode == 'global' and self.global_start_time is None:
            earliest = self.data_store.get_earliest_timestamp()
            if earliest:
                self.global_start_time = earliest

    def set_global_start_time(self, timestamp: Optional[datetime]) -> None:
        """Set global start time for global mode calculations.

        Args:
            timestamp: Start time, or None to reset
        """
        self.global_start_time = timestamp

    def get_dps_display_data(
        self, target_filter: str = "All"
    ) -> List[Dict[str, Any]]:
        """Get DPS data formatted for UI display.

        This method calculates DPS for all characters or a specific target,
        applying the current time tracking mode and including hit rate data.

        Args:
            target_filter: 'All' to show all targets, or specific target name

        Returns:
            List of dicts with keys:
            - character: Character name
            - dps: DPS value (float)
            - total_damage: Total damage dealt
            - time_seconds: Time spent dealing damage
            - hit_rate: Hit rate percentage (0-100)
        """
        if target_filter == "All":
            dps_list = self.data_store.get_dps_data(
                time_tracking_mode=self.time_tracking_mode,
                global_start_time=self.global_start_time,
            )
            hit_rates = self.data_store.get_hit_rate_for_damage_dealers()
        else:
            dps_list = self.data_store.get_dps_data_for_target(
                target=target_filter,
                time_tracking_mode=self.time_tracking_mode,
                global_start_time=self.global_start_time,
            )
            hit_rates = self.data_store.get_hit_rate_for_damage_dealers(
                target=target_filter
            )

        # Add hit rate to each entry
        for entry in dps_list:
            entry['hit_rate'] = hit_rates.get(entry['character'], 0.0)

        return dps_list

    def get_damage_type_breakdown(
        self, character: str, target_filter: str = "All"
    ) -> List[Dict[str, Any]]:
        """Get damage type breakdown for a character.

        Args:
            character: Character name
            target_filter: 'All' to show all targets, or specific target name

        Returns:
            List of dicts with keys:
            - damage_type: Type of damage
            - total_damage: Total damage of this type
            - dps: DPS of this damage type
        """
        if target_filter == "All":
            return self.data_store.get_dps_breakdown_by_type(
                character,
                time_tracking_mode=self.time_tracking_mode,
                global_start_time=self.global_start_time,
            )
        else:
            return self.data_store.get_dps_breakdown_by_type_for_target(
                character,
                target=target_filter,
                time_tracking_mode=self.time_tracking_mode,
                global_start_time=self.global_start_time,
            )

    def should_auto_refresh_in_global_mode(self) -> bool:
        """Check if auto-refresh should be active in global mode.

        Returns:
            True if in global mode and auto-refresh should be scheduled
        """
        return self.time_tracking_mode == "global"

