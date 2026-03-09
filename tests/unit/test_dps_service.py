"""Unit tests for DPSCalculationService.

Tests DPS calculations, time tracking modes, and data aggregation.
"""

import unittest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta

from app.services.dps_service import DPSCalculationService
from app.storage import DataStore
from tests.helpers.store_mutations import apply, dps_update


class TestDPSCalculationService(unittest.TestCase):
    """Test suite for DPSCalculationService."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = Mock(spec=DataStore)
        self.service = DPSCalculationService(self.data_store)

    def test_initialization(self) -> None:
        """Test service initializes with correct defaults."""
        self.assertEqual(self.service.time_tracking_mode, 'per_character')
        self.assertIsNone(self.service.global_start_time)
        self.assertEqual(self.service.data_store, self.data_store)

    def test_set_time_tracking_mode_per_character(self) -> None:
        """Test setting time tracking mode to per_character."""
        self.service.set_time_tracking_mode('per_character')
        self.assertEqual(self.service.time_tracking_mode, 'per_character')

    def test_set_time_tracking_mode_global(self) -> None:
        """Test setting time tracking mode to global."""
        self.data_store.get_earliest_timestamp.return_value = datetime.now()

        self.service.set_time_tracking_mode('global')
        self.assertEqual(self.service.time_tracking_mode, 'global')

    def test_set_time_tracking_mode_invalid(self) -> None:
        """Test setting invalid time tracking mode raises error."""
        with self.assertRaises(ValueError):
            self.service.set_time_tracking_mode('invalid_mode')

    def test_set_global_start_time(self) -> None:
        """Test setting global start time."""
        now = datetime.now()
        self.service.set_global_start_time(now)
        self.assertEqual(self.service.global_start_time, now)

    def test_set_global_start_time_none(self) -> None:
        """Test resetting global start time to None."""
        now = datetime.now()
        self.service.set_global_start_time(now)
        self.service.set_global_start_time(None)
        self.assertIsNone(self.service.global_start_time)

    def test_get_dps_display_data_all_targets(self) -> None:
        """Test getting DPS data for all targets."""
        mock_dps_data = [
            {
                'character': 'Rogue1',
                'total_damage': 1000,
                'time_seconds': 100,
                'dps': 10.0,
            },
            {
                'character': 'Mage1',
                'total_damage': 2000,
                'time_seconds': 100,
                'dps': 20.0,
            },
        ]

        self.data_store.get_dps_data.return_value = mock_dps_data
        self.data_store.get_hit_rate_for_damage_dealers.return_value = {
            'Rogue1': 75.0,
            'Mage1': 95.0,
        }

        result = self.service.get_dps_display_data(target_filter='All')

        # Verify results include hit rate
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['hit_rate'], 75.0)
        self.assertEqual(result[1]['hit_rate'], 95.0)

    def test_get_dps_display_data_specific_target(self) -> None:
        """Test getting DPS data for a specific target."""
        mock_dps_data = [
            {
                'character': 'Rogue1',
                'total_damage': 500,
                'time_seconds': 100,
                'dps': 5.0,
            },
        ]

        self.data_store.get_dps_data_for_target.return_value = mock_dps_data
        self.data_store.get_hit_rate_for_damage_dealers.return_value = {'Rogue1': 75.0}

        result = self.service.get_dps_display_data(target_filter='Dragon')

        # Verify get_dps_data_for_target was called with correct target
        self.data_store.get_dps_data_for_target.assert_called_with(
            target='Dragon',
            time_tracking_mode='per_character',
            global_start_time=None
        )

    def test_get_damage_type_breakdown_all_targets(self) -> None:
        """Test getting damage type breakdown for all targets."""
        self.data_store.get_dps_breakdowns_by_type.return_value = {
            'Mage1': [
                {'damage_type': 'Fire', 'total_damage': 500, 'dps': 5.0},
                {'damage_type': 'Cold', 'total_damage': 300, 'dps': 3.0},
            ]
        }

        result = self.service.get_damage_type_breakdown('Mage1', target_filter='All')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['damage_type'], 'Fire')
        self.assertEqual(result[1]['damage_type'], 'Cold')
        self.data_store.get_dps_breakdowns_by_type.assert_called_with(
            ['Mage1'],
            target=None,
            time_tracking_mode='per_character',
            global_start_time=None
        )

    def test_get_damage_type_breakdown_specific_target(self) -> None:
        """Test getting damage type breakdown for specific target."""
        self.data_store.get_dps_breakdowns_by_type.return_value = {
            'Mage1': [{'damage_type': 'Fire', 'total_damage': 500, 'dps': 5.0}]
        }

        result = self.service.get_damage_type_breakdown('Mage1', target_filter='Dragon')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['damage_type'], 'Fire')
        self.data_store.get_dps_breakdowns_by_type.assert_called_with(
            ['Mage1'],
            target='Dragon',
            time_tracking_mode='per_character',
            global_start_time=None
        )

    def test_get_damage_type_breakdowns_bulk_all_targets(self) -> None:
        """Test bulk damage type breakdown routing for all targets."""
        self.data_store.get_dps_breakdowns_by_type.return_value = {
            'Mage1': [{'damage_type': 'Fire', 'total_damage': 500, 'dps': 5.0}],
            'Rogue1': [{'damage_type': 'Physical', 'total_damage': 300, 'dps': 3.0}],
        }

        result = self.service.get_damage_type_breakdowns(['Mage1', 'Rogue1'], target_filter='All')

        self.assertIn('Mage1', result)
        self.assertIn('Rogue1', result)
        self.data_store.get_dps_breakdowns_by_type.assert_called_with(
            ['Mage1', 'Rogue1'],
            target=None,
            time_tracking_mode='per_character',
            global_start_time=None
        )


    def test_global_mode_with_earliest_timestamp(self) -> None:
        """Test global mode initialization with earliest timestamp."""
        earliest = datetime.now() - timedelta(hours=1)
        self.data_store.get_earliest_timestamp.return_value = earliest

        self.service.set_time_tracking_mode('global')

        self.assertEqual(self.service.global_start_time, earliest)

    def test_mode_switch_preserves_data(self) -> None:
        """Test switching time tracking modes preserves data."""
        mock_dps_data = [
            {'character': 'Rogue1', 'total_damage': 1000, 'time_seconds': 100, 'dps': 10.0},
        ]

        self.data_store.get_dps_data.return_value = mock_dps_data
        self.data_store.get_hit_rate_for_damage_dealers.return_value = {}

        # Get data in per_character mode
        result1 = self.service.get_dps_display_data(target_filter='All')

        # Switch to global mode
        self.data_store.get_earliest_timestamp.return_value = datetime.now()
        self.service.set_time_tracking_mode('global')

        # Get data in global mode
        result2 = self.service.get_dps_display_data(target_filter='All')

        # Both should return the same character
        self.assertEqual(result1[0]['character'], result2[0]['character'])


class TestDPSCalculationServiceIntegration(unittest.TestCase):
    """Integration tests with real DataStore."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = DataStore()
        self.service = DPSCalculationService(self.data_store)

    def tearDown(self) -> None:
        """Clean up."""
        self.data_store.close()

    def test_mode_switching_with_real_data(self) -> None:
        """Test mode switching works correctly with real data."""
        now = datetime.now()

        # Insert some test data
        apply(
            self.data_store,
            dps_update(attacker='Rogue1', total_damage=100, timestamp=now, damage_types={'Piercing': 100}),
            dps_update(attacker='Mage1', total_damage=150, timestamp=now + timedelta(seconds=10), damage_types={'Fire': 150}),
        )

        # Test per_character mode
        self.service.set_time_tracking_mode('per_character')
        self.assertEqual(self.service.time_tracking_mode, 'per_character')

        # Test global mode
        self.service.set_time_tracking_mode('global')
        self.assertEqual(self.service.time_tracking_mode, 'global')
        self.assertIsNotNone(self.service.global_start_time)


if __name__ == '__main__':
    unittest.main()

