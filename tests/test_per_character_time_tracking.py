"""Tests for per-character time tracking in By Character mode.

This test suite verifies that in "By Character" mode, each character's
DPS and time values are independent and only update when that specific
character deals damage, not when other characters deal damage.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from app.storage import DataStore
from app.services.dps_service import DPSCalculationService


class TestPerCharacterTimeTracking(unittest.TestCase):
    """Test suite for independent per-character time tracking in By Character mode."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = DataStore()
        self.service = DPSCalculationService(self.data_store)
        self.service.set_time_tracking_mode('by_character')

    def test_character_time_independent_when_other_character_attacks(self) -> None:
        """Test that Character A's time doesn't update when Character B deals damage.

        Scenario:
        1. Character A deals 100 damage at T=0
        2. Character A deals 100 damage at T=5
        3. Character B deals 200 damage at T=10
        4. Character B deals 200 damage at T=15

        Expected:
        - Character A: 200 damage over 5 seconds = 40 DPS
        - Character B: 400 damage over 5 seconds = 80 DPS

        Character A's time should NOT update to 15 seconds when Character B attacks.
        """
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        # Character A deals damage at T=0 and T=5
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=100,
            timestamp=base_time,
            damage_types={'Physical': 100}
        )
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=100,
            timestamp=base_time + timedelta(seconds=5),
            damage_types={'Physical': 100}
        )

        # Character B deals damage at T=10 and T=15
        self.data_store.update_dps_data(
            character='CharacterB',
            damage_amount=200,
            timestamp=base_time + timedelta(seconds=10),
            damage_types={'Fire': 200}
        )
        self.data_store.update_dps_data(
            character='CharacterB',
            damage_amount=200,
            timestamp=base_time + timedelta(seconds=15),
            damage_types={'Fire': 200}
        )

        # Get DPS data in By Character mode
        dps_data = self.data_store.get_dps_data(time_tracking_mode='by_character')

        # Find each character's data
        char_a_data = next(d for d in dps_data if d['character'] == 'CharacterA')
        char_b_data = next(d for d in dps_data if d['character'] == 'CharacterB')

        # Verify Character A's time is 5 seconds (not affected by Character B)
        self.assertEqual(char_a_data['time_seconds'].total_seconds(), 5.0,
                        "Character A's time should be 5 seconds (T=0 to T=5)")
        self.assertEqual(char_a_data['total_damage'], 200,
                        "Character A should have 200 total damage")
        self.assertAlmostEqual(char_a_data['dps'], 40.0, places=2,
                              msg="Character A's DPS should be 40.0 (200 damage / 5 seconds)")

        # Verify Character B's time is 5 seconds
        self.assertEqual(char_b_data['time_seconds'].total_seconds(), 5.0,
                        "Character B's time should be 5 seconds (T=10 to T=15)")
        self.assertEqual(char_b_data['total_damage'], 400,
                        "Character B should have 400 total damage")
        self.assertAlmostEqual(char_b_data['dps'], 80.0, places=2,
                              msg="Character B's DPS should be 80.0 (400 damage / 5 seconds)")

    def test_character_dps_stays_constant_after_stopping(self) -> None:
        """Test that a character's DPS remains constant after they stop attacking.

        Scenario:
        1. Character A deals damage at T=0, T=2, T=4 (stops)
        2. Character B deals damage at T=0, T=5, T=10, T=15 (continues)

        Expected:
        - Character A: DPS calculated from T=0 to T=4 (their own timeframe)
        - Character B: DPS calculated from T=0 to T=15 (their own timeframe)
        - Character A's values should NOT change when Character B attacks at T=10 and T=15
        """
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        # Both characters start at T=0
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=50,
            timestamp=base_time,
            damage_types={'Physical': 50}
        )
        self.data_store.update_dps_data(
            character='CharacterB',
            damage_amount=50,
            timestamp=base_time,
            damage_types={'Fire': 50}
        )

        # Character A attacks at T=2 and T=4, then stops
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=50,
            timestamp=base_time + timedelta(seconds=2),
            damage_types={'Physical': 50}
        )
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=50,
            timestamp=base_time + timedelta(seconds=4),
            damage_types={'Physical': 50}
        )

        # Get DPS after Character A stops
        dps_data_t4 = self.data_store.get_dps_data(time_tracking_mode='by_character')
        char_a_data_t4 = next(d for d in dps_data_t4 if d['character'] == 'CharacterA')

        # Character A should have 150 damage over 4 seconds = 37.5 DPS
        self.assertAlmostEqual(char_a_data_t4['dps'], 37.5, places=2)
        self.assertEqual(char_a_data_t4['time_seconds'].total_seconds(), 4.0)

        # Character B continues attacking at T=5, T=10, T=15
        self.data_store.update_dps_data(
            character='CharacterB',
            damage_amount=50,
            timestamp=base_time + timedelta(seconds=5),
            damage_types={'Fire': 50}
        )
        self.data_store.update_dps_data(
            character='CharacterB',
            damage_amount=50,
            timestamp=base_time + timedelta(seconds=10),
            damage_types={'Fire': 50}
        )
        self.data_store.update_dps_data(
            character='CharacterB',
            damage_amount=50,
            timestamp=base_time + timedelta(seconds=15),
            damage_types={'Fire': 50}
        )

        # Get DPS after Character B continues
        dps_data_t15 = self.data_store.get_dps_data(time_tracking_mode='by_character')
        char_a_data_t15 = next(d for d in dps_data_t15 if d['character'] == 'CharacterA')
        char_b_data_t15 = next(d for d in dps_data_t15 if d['character'] == 'CharacterB')

        # Character A's DPS should STILL be 37.5 (unchanged)
        self.assertAlmostEqual(char_a_data_t15['dps'], 37.5, places=2,
                              msg="Character A's DPS should remain 37.5")
        self.assertEqual(char_a_data_t15['time_seconds'].total_seconds(), 4.0,
                        "Character A's time should still be 4 seconds")
        self.assertEqual(char_a_data_t15['total_damage'], 150,
                        "Character A's damage should still be 150")

        # Character B should have 200 damage over 15 seconds = 13.33 DPS
        self.assertAlmostEqual(char_b_data_t15['dps'], 13.33, places=2,
                              msg="Character B's DPS should be 13.33 (200 damage / 15 seconds)")
        self.assertEqual(char_b_data_t15['time_seconds'].total_seconds(), 15.0,
                        "Character B's time should be 15 seconds")

    def test_damage_type_breakdown_per_character_independent(self) -> None:
        """Test that damage type breakdown also uses per-character time tracking.

        Scenario:
        1. Character A deals Physical damage at T=0 and T=5
        2. Character B deals Fire damage at T=10 and T=20

        Expected:
        - Character A's Physical DPS: based on 5 second timeframe
        - Character B's Fire DPS: based on 10 second timeframe
        """
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        # Character A deals Physical damage
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=100,
            timestamp=base_time,
            damage_types={'Physical': 100}
        )
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=100,
            timestamp=base_time + timedelta(seconds=5),
            damage_types={'Physical': 100}
        )

        # Character B deals Fire damage
        self.data_store.update_dps_data(
            character='CharacterB',
            damage_amount=300,
            timestamp=base_time + timedelta(seconds=10),
            damage_types={'Fire': 300}
        )
        self.data_store.update_dps_data(
            character='CharacterB',
            damage_amount=300,
            timestamp=base_time + timedelta(seconds=20),
            damage_types={'Fire': 300}
        )

        # Get breakdown for Character A
        breakdown_a = self.data_store.get_dps_breakdown_by_type(
            'CharacterA',
            time_tracking_mode='by_character'
        )

        # Character A: 200 Physical damage over 5 seconds = 40 DPS
        self.assertEqual(len(breakdown_a), 1)
        self.assertEqual(breakdown_a[0]['damage_type'], 'Physical')
        self.assertAlmostEqual(breakdown_a[0]['dps'], 40.0, places=2)

        # Get breakdown for Character B
        breakdown_b = self.data_store.get_dps_breakdown_by_type(
            'CharacterB',
            time_tracking_mode='by_character'
        )

        # Character B: 600 Fire damage over 10 seconds = 60 DPS
        self.assertEqual(len(breakdown_b), 1)
        self.assertEqual(breakdown_b[0]['damage_type'], 'Fire')
        self.assertAlmostEqual(breakdown_b[0]['dps'], 60.0, places=2)

    def test_single_character_only_updates_own_timestamp(self) -> None:
        """Test that a single character's timestamps update correctly.

        Scenario:
        1. Character A deals damage at T=0
        2. Character A deals damage at T=3
        3. Character A deals damage at T=7

        Expected:
        - First timestamp: T=0
        - Last timestamp: T=7
        - Time elapsed: 7 seconds
        """
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=100,
            timestamp=base_time,
            damage_types={'Physical': 100}
        )
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=100,
            timestamp=base_time + timedelta(seconds=3),
            damage_types={'Physical': 100}
        )
        self.data_store.update_dps_data(
            character='CharacterA',
            damage_amount=100,
            timestamp=base_time + timedelta(seconds=7),
            damage_types={'Physical': 100}
        )

        dps_data = self.data_store.get_dps_data(time_tracking_mode='by_character')

        self.assertEqual(len(dps_data), 1)
        char_data = dps_data[0]

        self.assertEqual(char_data['character'], 'CharacterA')
        self.assertEqual(char_data['total_damage'], 300)
        self.assertEqual(char_data['time_seconds'].total_seconds(), 7.0)
        self.assertAlmostEqual(char_data['dps'], 42.86, places=2)  # 300 / 7

    def test_three_characters_independent_timeframes(self) -> None:
        """Test that three characters with different attack patterns have independent times.

        Scenario:
        - Character A: attacks from T=0 to T=5
        - Character B: attacks from T=3 to T=10
        - Character C: attacks from T=8 to T=15

        Expected: Each character's DPS is calculated based on their own timeframe.
        """
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        # Character A: T=0 to T=5 (5 seconds)
        self.data_store.update_dps_data('CharacterA', 100, base_time, {'Physical': 100})
        self.data_store.update_dps_data('CharacterA', 100, base_time + timedelta(seconds=5), {'Physical': 100})

        # Character B: T=3 to T=10 (7 seconds)
        self.data_store.update_dps_data('CharacterB', 150, base_time + timedelta(seconds=3), {'Fire': 150})
        self.data_store.update_dps_data('CharacterB', 150, base_time + timedelta(seconds=10), {'Fire': 150})

        # Character C: T=8 to T=15 (7 seconds)
        self.data_store.update_dps_data('CharacterC', 200, base_time + timedelta(seconds=8), {'Cold': 200})
        self.data_store.update_dps_data('CharacterC', 200, base_time + timedelta(seconds=15), {'Cold': 200})

        dps_data = self.data_store.get_dps_data(time_tracking_mode='by_character')

        # Verify each character has independent time tracking
        char_a = next(d for d in dps_data if d['character'] == 'CharacterA')
        char_b = next(d for d in dps_data if d['character'] == 'CharacterB')
        char_c = next(d for d in dps_data if d['character'] == 'CharacterC')

        self.assertEqual(char_a['time_seconds'].total_seconds(), 5.0)
        self.assertAlmostEqual(char_a['dps'], 40.0, places=2)  # 200 / 5

        self.assertEqual(char_b['time_seconds'].total_seconds(), 7.0)
        self.assertAlmostEqual(char_b['dps'], 42.86, places=2)  # 300 / 7

        self.assertEqual(char_c['time_seconds'].total_seconds(), 7.0)
        self.assertAlmostEqual(char_c['dps'], 57.14, places=2)  # 400 / 7


if __name__ == '__main__':
    unittest.main()

