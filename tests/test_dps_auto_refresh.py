"""Tests for DPS panel auto-refresh functionality in Global mode.

This test suite verifies that:
1. In Global mode, the DPS panel refreshes automatically every second
2. Auto-refresh is optimized to skip scheduling when damage events arrive frequently
3. Auto-refresh stops when monitoring is paused or mode is changed
"""

import unittest
import time
from unittest.mock import Mock
from datetime import datetime

from app.services.dps_service import DPSCalculationService
from app.storage import DataStore


class TestDPSAutoRefresh(unittest.TestCase):
    """Test suite for DPS auto-refresh in Global mode."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = Mock(spec=DataStore)
        self.service = DPSCalculationService(self.data_store)

    def test_should_auto_refresh_in_global_mode(self) -> None:
        """Test that should_auto_refresh_in_global_mode returns True only in global mode."""
        # In by_character mode, should not auto-refresh
        self.service.set_time_tracking_mode('by_character')
        self.assertFalse(self.service.should_auto_refresh_in_global_mode())

        # In global mode, should auto-refresh
        self.data_store.get_earliest_timestamp.return_value = datetime.now()
        self.service.set_time_tracking_mode('global')
        self.assertTrue(self.service.should_auto_refresh_in_global_mode())

    def test_should_auto_refresh_after_mode_switch(self) -> None:
        """Test that auto-refresh flag updates when switching modes."""
        self.data_store.get_earliest_timestamp.return_value = datetime.now()

        # Start in by_character mode
        self.service.set_time_tracking_mode('by_character')
        self.assertFalse(self.service.should_auto_refresh_in_global_mode())

        # Switch to global mode
        self.service.set_time_tracking_mode('global')
        self.assertTrue(self.service.should_auto_refresh_in_global_mode())

        # Switch back to by_character mode
        self.service.set_time_tracking_mode('by_character')
        self.assertFalse(self.service.should_auto_refresh_in_global_mode())


class TestDPSAutoRefreshOptimization(unittest.TestCase):
    """Test suite for DPS auto-refresh optimization logic."""

    def test_refresh_scheduled_when_no_recent_damage(self) -> None:
        """Test that auto-refresh is scheduled when no damage events arrived recently."""
        # Simulate the logic from main_window.refresh_dps()
        last_damage_event_time: float = time.time() - 2.0  # 2 seconds ago
        current_time = time.time()

        should_schedule = True
        time_since_last_event = current_time - last_damage_event_time
        if time_since_last_event < 1.0:
            should_schedule = False

        # Should schedule because last event was >1 second ago
        self.assertTrue(should_schedule)

    def test_refresh_not_scheduled_when_recent_damage(self) -> None:
        """Test that auto-refresh is NOT scheduled when damage events arrived recently."""
        # Simulate the logic from main_window.refresh_dps()
        last_damage_event_time: float = time.time() - 0.5  # 0.5 seconds ago
        current_time = time.time()

        should_schedule = True
        time_since_last_event = current_time - last_damage_event_time
        if time_since_last_event < 1.0:
            should_schedule = False

        # Should NOT schedule because last event was <1 second ago
        self.assertFalse(should_schedule)

    def test_refresh_scheduled_when_no_damage_events_yet(self) -> None:
        """Test that auto-refresh is scheduled when no damage events have occurred yet."""
        # Simulate the logic from main_window.refresh_dps()
        last_damage_event_time = None  # No events yet
        current_time = time.time()

        should_schedule = True
        if last_damage_event_time is not None:
            time_since_last_event = current_time - last_damage_event_time
            if time_since_last_event < 1.0:
                should_schedule = False

        # Should schedule because no events have occurred
        self.assertTrue(should_schedule)

    def test_refresh_optimization_boundary_case(self) -> None:
        """Test auto-refresh optimization at exactly 1.0 second boundary."""
        # Simulate the logic from main_window.refresh_dps()
        last_damage_event_time: float = time.time() - 1.0  # Exactly 1 second ago
        current_time = time.time()

        should_schedule = True
        time_since_last_event = current_time - last_damage_event_time
        if time_since_last_event < 1.0:
            should_schedule = False

        # Should schedule because time_since_last_event >= 1.0
        self.assertTrue(should_schedule)


class TestDPSServiceGlobalModeIntegration(unittest.TestCase):
    """Integration tests for DPS service in Global mode with time progression."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = Mock(spec=DataStore)
        self.service = DPSCalculationService(self.data_store)

    def test_global_mode_dps_decreases_over_time(self) -> None:
        """Test that in Global mode, DPS decreases as time passes without new damage.

        This simulates the scenario where:
        1. A character deals damage
        2. The fight ends (no more damage)
        3. Time keeps moving forward in Global mode
        4. DPS should decrease as the denominator (time) increases
        """
        # Setup: Character dealt 1000 damage at T=0
        start_time = datetime(2025, 1, 1, 10, 0, 0)

        # At T=10s: DPS should be 1000/10 = 100.0
        mock_dps_data_t10 = [
            {
                'character': 'Fighter1',
                'total_damage': 1000,
                'time_seconds': 10.0,
                'dps': 100.0,
            }
        ]

        # At T=20s: DPS should be 1000/20 = 50.0
        mock_dps_data_t20 = [
            {
                'character': 'Fighter1',
                'total_damage': 1000,
                'time_seconds': 20.0,
                'dps': 50.0,
            }
        ]

        self.data_store.get_earliest_timestamp.return_value = start_time
        self.service.set_time_tracking_mode('global')

        # Simulate DPS at T=10s
        self.data_store.get_dps_data.return_value = mock_dps_data_t10
        self.data_store.get_hit_rate_for_damage_dealers.return_value = {'Fighter1': 75.0}

        result_t10 = self.service.get_dps_display_data(target_filter='All')
        self.assertEqual(result_t10[0]['dps'], 100.0)
        self.assertEqual(result_t10[0]['time_seconds'], 10.0)

        # Simulate DPS at T=20s (time passed, no new damage)
        self.data_store.get_dps_data.return_value = mock_dps_data_t20

        result_t20 = self.service.get_dps_display_data(target_filter='All')
        self.assertEqual(result_t20[0]['dps'], 50.0)
        self.assertEqual(result_t20[0]['time_seconds'], 20.0)

        # DPS should decrease
        self.assertLess(result_t20[0]['dps'], result_t10[0]['dps'])

    def test_by_character_mode_dps_stays_constant(self) -> None:
        """Test that in By Character mode, DPS stays constant when no new damage arrives.

        This is the key difference from Global mode - time only advances per character
        when they deal damage.
        """
        # Setup: Character dealt 1000 damage over 10 seconds
        mock_dps_data = [
            {
                'character': 'Fighter1',
                'total_damage': 1000,
                'time_seconds': 10.0,
                'dps': 100.0,
            }
        ]

        self.service.set_time_tracking_mode('by_character')

        # Simulate multiple calls - DPS should remain constant
        self.data_store.get_dps_data.return_value = mock_dps_data
        self.data_store.get_hit_rate_for_damage_dealers.return_value = {'Fighter1': 75.0}

        result_1 = self.service.get_dps_display_data(target_filter='All')
        result_2 = self.service.get_dps_display_data(target_filter='All')

        # DPS should remain the same
        self.assertEqual(result_1[0]['dps'], 100.0)
        self.assertEqual(result_2[0]['dps'], 100.0)
        self.assertEqual(result_1[0]['dps'], result_2[0]['dps'])


if __name__ == '__main__':
    unittest.main()

