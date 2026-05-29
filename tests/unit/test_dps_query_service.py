"""Unit tests for DpsQueryService.

Tests DPS calculations, time tracking modes, and data aggregation.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from app.services.queries import DpsBreakdownRow, DpsQueryService, DpsRow
from app.storage import DataStore
from tests.helpers.store_mutations import apply, attack, damage_dealt, damage_row, dps_update


class TestDpsQueryService(unittest.TestCase):
    """Test suite for DpsQueryService."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = DataStore()
        self.service = DpsQueryService(self.data_store)

    def tearDown(self) -> None:
        self.data_store.close()

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
        now = datetime.now()
        apply(self.data_store, dps_update(attacker="Woo", total_damage=10, timestamp=now))

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
        now = datetime.now()
        apply(
            self.data_store,
            dps_update(attacker="Rogue1", total_damage=1000, timestamp=now),
            dps_update(attacker="Mage1", total_damage=2000, timestamp=now + timedelta(seconds=100)),
            damage_row(target="Dragon", damage_type="Physical", total_damage=1000, attacker="Rogue1", timestamp=now),
            damage_row(target="Dragon", damage_type="Fire", total_damage=2000, attacker="Mage1", timestamp=now + timedelta(seconds=100)),
            attack(attacker="Rogue1", target="Dragon", outcome="hit"),
            attack(attacker="Rogue1", target="Dragon", outcome="miss"),
            attack(attacker="Rogue1", target="Dragon", outcome="hit"),
            attack(attacker="Rogue1", target="Dragon", outcome="critical_hit"),
            attack(attacker="Mage1", target="Dragon", outcome="hit"),
            attack(attacker="Mage1", target="Dragon", outcome="hit"),
            attack(attacker="Mage1", target="Dragon", outcome="hit"),
            attack(attacker="Mage1", target="Dragon", outcome="miss"),
        )

        result = self.service.get_dps_display_data(target_filter='All')

        # Verify results include hit rate
        self.assertEqual(len(result), 2)
        by_character = {row.character: row for row in result}
        self.assertEqual(by_character['Rogue1'].hit_rate, 75.0)
        self.assertEqual(by_character['Mage1'].hit_rate, 75.0)

    def test_get_dps_display_data_specific_target(self) -> None:
        """Test getting DPS data for a specific target."""
        now = datetime.now()
        apply(
            self.data_store,
            damage_row(target="Dragon", damage_type="Physical", total_damage=500, attacker="Rogue1", timestamp=now),
            damage_row(target="Goblin", damage_type="Cold", total_damage=300, attacker="Rogue1", timestamp=now + timedelta(seconds=100)),
            attack(attacker="Rogue1", target="Dragon", outcome="hit"),
            attack(attacker="Rogue1", target="Dragon", outcome="miss"),
        )

        result = self.service.get_dps_display_data(target_filter='Dragon')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].character, "Rogue1")
        self.assertEqual(result[0].total_damage, 500)
        self.assertEqual(result[0].hit_rate, 50.0)

    def test_get_damage_type_breakdown_all_targets(self) -> None:
        """Test getting damage type breakdown for all targets."""
        now = datetime.now()
        apply(
            self.data_store,
            dps_update(attacker="Mage1", total_damage=800, timestamp=now, damage_types={"Fire": 500, "Cold": 300}),
        )
        self.data_store.last_damage_timestamp = now + timedelta(seconds=100)

        result = self.service.get_damage_type_breakdown('Mage1', target_filter='All')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].damage_type, 'Fire')
        self.assertEqual(result[1].damage_type, 'Cold')

    def test_get_damage_type_breakdown_specific_target(self) -> None:
        """Test getting damage type breakdown for specific target."""
        now = datetime.now()
        apply(
            self.data_store,
            damage_row(target="Dragon", damage_type="Fire", total_damage=500, attacker="Mage1", timestamp=now),
            damage_row(target="Goblin", damage_type="Cold", total_damage=300, attacker="Mage1", timestamp=now + timedelta(seconds=100)),
        )

        result = self.service.get_damage_type_breakdown('Mage1', target_filter='Dragon')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].damage_type, 'Fire')

    def test_get_damage_type_breakdowns_bulk_all_targets(self) -> None:
        """Test bulk damage type breakdown routing for all targets."""
        now = datetime.now()
        apply(
            self.data_store,
            dps_update(attacker="Mage1", total_damage=500, timestamp=now, damage_types={"Fire": 500}),
            dps_update(attacker="Rogue1", total_damage=300, timestamp=now, damage_types={"Physical": 300}),
        )
        self.data_store.last_damage_timestamp = now + timedelta(seconds=100)

        result = self.service.get_damage_type_breakdowns(['Mage1', 'Rogue1'], target_filter='All')

        self.assertIn('Mage1', result)
        self.assertIn('Rogue1', result)
        self.assertEqual(result["Mage1"][0].damage_type, "Fire")
        self.assertEqual(result["Rogue1"][0].damage_type, "Physical")


    def test_global_mode_with_earliest_timestamp(self) -> None:
        """Test global mode initialization with earliest timestamp."""
        earliest = datetime.now() - timedelta(hours=1)
        apply(self.data_store, dps_update(attacker="Woo", total_damage=10, timestamp=earliest))

        self.service.set_time_tracking_mode('global')

        self.assertEqual(self.service.global_start_time, earliest)

    def test_mode_switch_preserves_data(self) -> None:
        """Test switching time tracking modes preserves data."""
        now = datetime.now()
        apply(
            self.data_store,
            dps_update(attacker="Rogue1", total_damage=1000, timestamp=now, damage_types={"Physical": 1000}),
        )
        self.data_store.last_damage_timestamp = now + timedelta(seconds=100)

        # Get data in per_character mode
        result1 = self.service.get_dps_display_data(target_filter='All')

        # Switch to global mode
        self.service.set_time_tracking_mode('global')

        # Get data in global mode
        result2 = self.service.get_dps_display_data(target_filter='All')

        # Both should return the same character
        self.assertEqual(result1[0].character, result2[0].character)

    def test_get_dps_data_uses_atomic_projection_snapshot(self) -> None:
        """DPS rows should come from one store projection snapshot."""
        now = datetime.now()
        apply(
            self.data_store,
            dps_update(attacker="Woo", total_damage=100, timestamp=now, damage_types={"Fire": 100}),
        )
        self.data_store.get_last_damage_timestamp = Mock(side_effect=AssertionError("stale read"))
        self.data_store.get_dps_summaries = Mock(side_effect=AssertionError("stale read"))
        self.data_store.get_target_dps_summaries = Mock(side_effect=AssertionError("stale read"))

        result = self.service.get_dps_data()

        self.assertEqual(result[0].character, "Woo")

    def test_get_damage_type_breakdowns_uses_atomic_projection_snapshot(self) -> None:
        """Breakdown rows should come from one store projection snapshot."""
        now = datetime.now()
        apply(
            self.data_store,
            dps_update(attacker="Woo", total_damage=100, timestamp=now, damage_types={"Fire": 100}),
        )
        self.data_store.last_damage_timestamp = now + timedelta(seconds=10)
        self.data_store.get_last_damage_timestamp = Mock(side_effect=AssertionError("stale read"))
        self.data_store.get_dps_summaries = Mock(side_effect=AssertionError("stale read"))
        self.data_store.get_target_dps_summaries = Mock(side_effect=AssertionError("stale read"))

        result = self.service.get_damage_type_breakdowns(["Woo"])

        self.assertEqual(result["Woo"][0].damage_type, "Fire")

    def test_combine_associates_off_keeps_separate_rows(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead", target="Dragon", timestamp=now, damage_types={"Physical": 100}),
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now, damage_types={"Fire": 50}),
        )

        result = self.service.get_dps_display_data()

        self.assertEqual({row.character for row in result}, {"Lead", "Lead | Summon"})

    def test_combine_associates_aggregates_damage_breakdowns_and_hit_rate(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead", target="Dragon", timestamp=now, damage_types={"Physical": 100}),
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now + timedelta(seconds=4), damage_types={"Fire": 50}),
            attack(attacker="Lead", target="Dragon", outcome="hit"),
            attack(attacker="Lead", target="Dragon", outcome="miss"),
            attack(attacker="Lead | Summon", target="Dragon", outcome="critical_hit"),
        )
        self.service.set_combine_associates(True)

        result = self.service.get_dps_display_data()
        breakdown = self.service.get_damage_type_breakdown("Lead")

        self.assertEqual([row.character for row in result], ["Lead"])
        self.assertEqual(result[0].total_damage, 150)
        self.assertEqual(result[0].hit_rate, pytest.approx(200 / 3))
        self.assertEqual({row.damage_type: row.total_damage for row in breakdown}, {"Physical": 100, "Fire": 50})

    def test_combine_associates_multiple_associates(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead", target="Dragon", timestamp=now, damage_types={"Physical": 100}),
            damage_dealt(attacker="Lead | Wolf", target="Dragon", timestamp=now, damage_types={"Fire": 50}),
            damage_dealt(attacker="Lead | Bear", target="Dragon", timestamp=now, damage_types={"Cold": 25}),
        )
        self.service.set_combine_associates(True)

        result = self.service.get_dps_display_data()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].character, "Lead")
        self.assertEqual(result[0].total_damage, 175)

    def test_pipe_name_without_known_lead_is_not_associated(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now, damage_types={"Fire": 50}),
        )
        self.service.set_combine_associates(True)

        result = self.service.get_dps_display_data()

        self.assertEqual([row.character for row in result], ["Lead | Summon"])

    def test_associate_discovery_works_before_lead_seen(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now, damage_types={"Fire": 50}),
            damage_dealt(attacker="Lead", target="Dragon", timestamp=now + timedelta(seconds=1), damage_types={"Physical": 100}),
        )
        self.service.set_combine_associates(True)

        result = self.service.get_dps_display_data()

        self.assertEqual([row.character for row in result], ["Lead"])
        self.assertEqual(result[0].total_damage, 150)

    def test_combine_associates_target_filter_uses_selected_target_only(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead", target="Dragon", timestamp=now, damage_types={"Physical": 100}),
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now, damage_types={"Fire": 50}),
            damage_dealt(attacker="Lead | Summon", target="Goblin", timestamp=now, damage_types={"Cold": 75}),
            attack(attacker="Lead", target="Dragon", outcome="hit"),
            attack(attacker="Lead | Summon", target="Dragon", outcome="miss"),
            attack(attacker="Lead | Summon", target="Goblin", outcome="critical_hit"),
        )
        self.service.set_combine_associates(True)

        result = self.service.get_dps_display_data(target_filter="Dragon")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].character, "Lead")
        self.assertEqual(result[0].total_damage, 150)
        self.assertEqual(result[0].hit_rate, 50.0)

    def test_combine_associates_target_filter_shows_lead_when_only_associate_damaged_target(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead", target="Goblin", timestamp=now, damage_types={"Physical": 100}),
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now, damage_types={"Fire": 50}),
        )
        self.service.set_combine_associates(True)

        result = self.service.get_dps_display_data(target_filter="Dragon")

        self.assertEqual([row.character for row in result], ["Lead"])
        self.assertEqual(result[0].total_damage, 50)

    def test_combine_associates_per_character_timing_uses_group_earliest_and_latest(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead", target="Dragon", timestamp=now + timedelta(seconds=10), damage_types={"Physical": 100}),
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now, damage_types={"Fire": 50}),
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now + timedelta(seconds=20), damage_types={"Fire": 50}),
        )
        self.service.set_combine_associates(True)

        result = self.service.get_dps_display_data(target_filter="Dragon")

        self.assertEqual(result[0].time_seconds, timedelta(seconds=20))
        self.assertEqual(result[0].dps, 10.0)

    def test_combine_associates_global_mode_uses_global_window(self) -> None:
        now = datetime.now()
        apply(
            self.data_store,
            damage_dealt(attacker="Lead", target="Dragon", timestamp=now, damage_types={"Physical": 100}),
            damage_dealt(attacker="Lead | Summon", target="Dragon", timestamp=now + timedelta(seconds=10), damage_types={"Fire": 50}),
        )
        self.service.set_time_tracking_mode("global")
        self.service.set_global_start_time(now - timedelta(seconds=10))
        self.service.set_combine_associates(True)

        result = self.service.get_dps_display_data()

        self.assertEqual(result[0].time_seconds, timedelta(seconds=20))
        self.assertEqual(result[0].dps, 7.5)


class TestDpsQueryServiceIntegration(unittest.TestCase):
    """Integration tests with real DataStore."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = DataStore()
        self.service = DpsQueryService(self.data_store)

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

