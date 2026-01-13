"""Unit tests for DataStore.

Tests in-memory data storage, DPS tracking, attack tracking,
immunity tracking, and time tracking modes.
"""

import pytest
from datetime import datetime, timedelta
from threading import Thread
import time

from app.storage import DataStore
from app.parser import LogParser
from app.models import EnemyAC, EnemySaves


class TestDataStoreInitialization:
    """Test suite for DataStore initialization."""

    def test_initialization(self, data_store: DataStore) -> None:
        """Test DataStore initializes with empty state."""
        assert len(data_store.events) == 0
        assert len(data_store.attacks) == 0
        assert len(data_store.dps_data) == 0
        assert len(data_store.immunity_data) == 0
        assert data_store.last_damage_timestamp is None

    def test_initialization_with_db_path(self) -> None:
        """Test DataStore ignores db_path parameter for compatibility."""
        ds = DataStore(db_path="ignored.db")
        assert len(ds.events) == 0


class TestDamageEventInsertion:
    """Test suite for insert_damage_event method."""

    def test_insert_single_damage_event(self, data_store: DataStore) -> None:
        """Test inserting a single damage event."""
        data_store.insert_damage_event("Goblin", "Fire", 10, 40, "Woo")

        assert len(data_store.events) == 1
        event = data_store.events[0]
        assert event.target == "Goblin"
        assert event.damage_type == "Fire"
        assert event.immunity_absorbed == 10
        assert event.total_damage_dealt == 40
        assert event.attacker == "Woo"

    def test_insert_multiple_damage_events(self, data_store: DataStore) -> None:
        """Test inserting multiple damage events."""
        data_store.insert_damage_event("Goblin", "Fire", 10, 40, "Woo")
        data_store.insert_damage_event("Orc", "Cold", 5, 30, "Rogue")

        assert len(data_store.events) == 2

    def test_insert_damage_with_timestamp(self, data_store: DataStore) -> None:
        """Test inserting damage event with custom timestamp."""
        ts = datetime(2026, 1, 9, 14, 30, 0)
        data_store.insert_damage_event("Goblin", "Fire", 10, 40, "Woo", ts)

        event = data_store.events[0]
        assert event.timestamp == ts

    def test_insert_damage_without_timestamp(self, data_store: DataStore) -> None:
        """Test inserting damage event without timestamp uses current time."""
        data_store.insert_damage_event("Goblin", "Fire", 10, 40, "Woo")

        event = data_store.events[0]
        assert isinstance(event.timestamp, datetime)


class TestAttackEventInsertion:
    """Test suite for insert_attack_event method."""

    def test_insert_attack_hit(self, data_store: DataStore) -> None:
        """Test inserting an attack hit event."""
        data_store.insert_attack_event("Woo", "Goblin", "hit", 15, 5, 20)

        assert len(data_store.attacks) == 1
        attack = data_store.attacks[0]
        assert attack.attacker == "Woo"
        assert attack.target == "Goblin"
        assert attack.outcome == "hit"
        assert attack.roll == 15
        assert attack.bonus == 5
        assert attack.total == 20

    def test_insert_attack_miss(self, data_store: DataStore) -> None:
        """Test inserting an attack miss event."""
        data_store.insert_attack_event("Woo", "Goblin", "miss", 8, 5, 13)

        attack = data_store.attacks[0]
        assert attack.outcome == "miss"

    def test_insert_attack_critical(self, data_store: DataStore) -> None:
        """Test inserting a critical hit event."""
        data_store.insert_attack_event("Woo", "Goblin", "critical_hit", 18, 5, 23)

        attack = data_store.attacks[0]
        assert attack.outcome == "critical_hit"


class TestDPSTracking:
    """Test suite for DPS data tracking."""

    def test_update_dps_data_new_character(self, data_store: DataStore) -> None:
        """Test updating DPS data for a new character."""
        ts = datetime.now()
        data_store.update_dps_data("Woo", 100, ts, {"Fire": 60, "Physical": 40})

        assert "Woo" in data_store.dps_data
        assert data_store.dps_data["Woo"]["total_damage"] == 100
        assert data_store.dps_data["Woo"]["first_timestamp"] == ts
        assert data_store.dps_data["Woo"]["damage_by_type"]["Fire"] == 60
        assert data_store.dps_data["Woo"]["damage_by_type"]["Physical"] == 40

    def test_update_dps_data_existing_character(self, data_store: DataStore) -> None:
        """Test updating DPS data for existing character accumulates damage."""
        ts1 = datetime.now()
        ts2 = ts1 + timedelta(seconds=5)

        data_store.update_dps_data("Woo", 100, ts1, {"Fire": 100})
        data_store.update_dps_data("Woo", 50, ts2, {"Fire": 50})

        assert data_store.dps_data["Woo"]["total_damage"] == 150
        assert data_store.dps_data["Woo"]["damage_by_type"]["Fire"] == 150

    def test_update_dps_data_updates_global_timestamp(self, data_store: DataStore) -> None:
        """Test that updating DPS data updates global last damage timestamp."""
        ts = datetime.now()
        data_store.update_dps_data("Woo", 100, ts)

        assert data_store.last_damage_timestamp == ts

    def test_get_earliest_timestamp(self, data_store: DataStore) -> None:
        """Test getting earliest timestamp across all characters."""
        ts1 = datetime(2026, 1, 9, 14, 30, 0)
        ts2 = datetime(2026, 1, 9, 14, 25, 0)  # Earlier
        ts3 = datetime(2026, 1, 9, 14, 35, 0)

        data_store.update_dps_data("Woo", 100, ts1)
        data_store.update_dps_data("Rogue", 50, ts2)
        data_store.update_dps_data("Mage", 75, ts3)

        earliest = data_store.get_earliest_timestamp()
        assert earliest == ts2

    def test_get_earliest_timestamp_no_data(self, data_store: DataStore) -> None:
        """Test getting earliest timestamp with no data returns None."""
        assert data_store.get_earliest_timestamp() is None


class TestDPSCalculations:
    """Test suite for DPS calculation methods."""

    def test_get_dps_data_by_character_mode(self, data_store: DataStore) -> None:
        """Test getting DPS data in by_character mode."""
        ts1 = datetime.now()
        ts2 = ts1 + timedelta(seconds=10)

        data_store.update_dps_data("Woo", 100, ts1)
        data_store.last_damage_timestamp = ts2

        dps_list = data_store.get_dps_data(time_tracking_mode="per_character")

        assert len(dps_list) == 1
        assert dps_list[0]["character"] == "Woo"
        assert dps_list[0]["total_damage"] == 100
        assert dps_list[0]["dps"] == 10.0  # 100 damage / 10 seconds

    def test_get_dps_data_global_mode(self, data_store: DataStore) -> None:
        """Test getting DPS data in global mode."""
        ts_start = datetime.now()
        ts1 = ts_start + timedelta(seconds=5)
        ts2 = ts_start + timedelta(seconds=10)

        data_store.update_dps_data("Woo", 100, ts1)
        data_store.update_dps_data("Rogue", 50, ts2)

        dps_list = data_store.get_dps_data(
            time_tracking_mode="global",
            global_start_time=ts_start
        )

        assert len(dps_list) == 2
        # Both characters use same global time window

    def test_get_dps_data_sorted_by_dps(self, data_store: DataStore) -> None:
        """Test that DPS data is sorted by DPS descending."""
        ts = datetime.now()

        data_store.update_dps_data("Woo", 100, ts)
        data_store.update_dps_data("Rogue", 200, ts)
        data_store.update_dps_data("Mage", 150, ts)
        data_store.last_damage_timestamp = ts + timedelta(seconds=10)

        dps_list = data_store.get_dps_data(time_tracking_mode="per_character")

        assert dps_list[0]["character"] == "Rogue"  # Highest DPS
        assert dps_list[1]["character"] == "Mage"
        assert dps_list[2]["character"] == "Woo"

    def test_get_dps_breakdown_by_type(self, data_store: DataStore) -> None:
        """Test getting DPS breakdown by damage type."""
        ts = datetime.now()
        damage_types = {"Fire": 60, "Physical": 40}

        data_store.update_dps_data("Woo", 100, ts, damage_types)
        data_store.last_damage_timestamp = ts + timedelta(seconds=10)

        breakdown = data_store.get_dps_breakdown_by_type(
            "Woo", time_tracking_mode="per_character"
        )

        assert len(breakdown) == 2
        assert breakdown[0]["damage_type"] == "Fire"
        assert breakdown[0]["total_damage"] == 60
        assert breakdown[1]["damage_type"] == "Physical"


class TestTargetFiltering:
    """Test suite for target-specific queries."""

    def test_get_all_targets(self, data_store: DataStore) -> None:
        """Test getting all unique targets."""
        data_store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
        data_store.insert_damage_event("Orc", "Cold", 0, 40, "Rogue")
        data_store.insert_damage_event("Goblin", "Physical", 0, 30, "Woo")

        targets = data_store.get_all_targets()

        assert len(targets) == 2
        assert "Goblin" in targets
        assert "Orc" in targets

    def test_get_target_stats(self, data_store: DataStore) -> None:
        """Test getting stats for a specific target."""
        data_store.insert_damage_event("Goblin", "Fire", 10, 40, "Woo")
        data_store.insert_damage_event("Goblin", "Physical", 5, 30, "Woo")

        stats = data_store.get_target_stats("Goblin")

        assert stats is not None
        assert stats[0] == 2  # total_hits
        assert stats[1] == 70  # total_damage
        assert stats[2] == 15  # total_absorbed

    def test_get_target_stats_no_data(self, data_store: DataStore) -> None:
        """Test getting stats for target with no data."""
        stats = data_store.get_target_stats("NonExistent")
        assert stats is None

    def test_get_dps_data_for_target(self, data_store: DataStore) -> None:
        """Test getting DPS data filtered by target."""
        ts = datetime.now()

        data_store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo", ts)
        data_store.insert_damage_event("Orc", "Cold", 0, 40, "Woo", ts)
        data_store.insert_damage_event("Goblin", "Physical", 0, 30, "Rogue", ts)

        dps_list = data_store.get_dps_data_for_target(
            "Goblin", time_tracking_mode="per_character"
        )

        # Should only include damage to Goblin
        total_goblin_damage = sum(d["total_damage"] for d in dps_list)
        assert total_goblin_damage == 80  # 50 + 30


class TestAttackStats:
    """Test suite for attack statistics methods."""

    def test_get_attack_stats(self, data_store: DataStore) -> None:
        """Test getting attack statistics for attacker vs target."""
        data_store.insert_attack_event("Woo", "Goblin", "hit")
        data_store.insert_attack_event("Woo", "Goblin", "hit")
        data_store.insert_attack_event("Woo", "Goblin", "critical_hit")
        data_store.insert_attack_event("Woo", "Goblin", "miss")

        stats = data_store.get_attack_stats("Woo", "Goblin")

        assert stats is not None
        assert stats["hits"] == 2
        assert stats["crits"] == 1
        assert stats["misses"] == 1
        assert stats["successful"] == 3  # hits + crits
        assert stats["hit_rate"] == 75.0  # 3/4

    def test_get_attack_stats_no_data(self, data_store: DataStore) -> None:
        """Test getting attack stats with no data."""
        stats = data_store.get_attack_stats("Woo", "NonExistent")
        assert stats is None

    def test_get_hit_rate_per_character(self, data_store: DataStore) -> None:
        """Test getting hit rate for each character."""
        data_store.insert_attack_event("Woo", "Goblin", "hit")
        data_store.insert_attack_event("Woo", "Goblin", "hit")
        data_store.insert_attack_event("Woo", "Goblin", "miss")

        data_store.insert_attack_event("Rogue", "Orc", "hit")
        data_store.insert_attack_event("Rogue", "Orc", "miss")
        data_store.insert_attack_event("Rogue", "Orc", "miss")

        hit_rates = data_store.get_hit_rate_per_character()

        assert hit_rates["Woo"] == pytest.approx(66.67, abs=0.1)
        assert hit_rates["Rogue"] == pytest.approx(33.33, abs=0.1)

    def test_get_hit_rate_for_damage_dealers(self, data_store: DataStore) -> None:
        """Test getting hit rate only for characters who dealt damage."""
        # Character with damage and attacks
        data_store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
        data_store.insert_attack_event("Woo", "Goblin", "hit")
        data_store.insert_attack_event("Woo", "Goblin", "miss")

        # Character with attacks but no damage
        data_store.insert_attack_event("Rogue", "Orc", "hit")
        data_store.insert_attack_event("Rogue", "Orc", "miss")

        hit_rates = data_store.get_hit_rate_for_damage_dealers()

        assert "Woo" in hit_rates
        assert "Rogue" not in hit_rates  # No damage dealt


class TestImmunityTracking:
    """Test suite for immunity tracking methods."""

    def test_record_immunity(self, data_store: DataStore) -> None:
        """Test recording immunity data."""
        data_store.record_immunity("Goblin", "Fire", 10, 50)

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")

        assert immunity_info["max_immunity"] == 10
        assert immunity_info["max_damage"] == 50
        assert immunity_info["sample_count"] == 1

    def test_record_immunity_updates_maximum(self, data_store: DataStore) -> None:
        """Test that recording immunity keeps maximum values."""
        data_store.record_immunity("Goblin", "Fire", 10, 50)
        data_store.record_immunity("Goblin", "Fire", 15, 70)  # Higher

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")

        assert immunity_info["max_immunity"] == 15
        assert immunity_info["max_damage"] == 70
        assert immunity_info["sample_count"] == 2

    def test_record_immunity_coupled_values(self, data_store: DataStore) -> None:
        """Test that max_immunity and max_damage are coupled from the same hit.

        When a hit with lower damage but higher immunity is recorded, it should NOT
        update the stored values. This ensures the immunity percentage calculation
        uses values from the same hit (e.g., preventing temporary 100% immunity buffs
        from skewing the calculation).
        """
        # First hit: 50 damage dealt, 10 absorbed (20% immunity)
        data_store.record_immunity("Goblin", "Fire", 10, 50)

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")
        assert immunity_info["max_damage"] == 50
        assert immunity_info["max_immunity"] == 10

        # Second hit: 0 damage dealt, 50 absorbed (100% temporary immunity buff)
        # This should NOT update the record because damage_dealt is lower
        data_store.record_immunity("Goblin", "Fire", 50, 0)

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")
        assert immunity_info["max_damage"] == 50  # Still 50, not 0
        assert immunity_info["max_immunity"] == 10  # Still 10, not 50
        assert immunity_info["sample_count"] == 2  # Both samples counted

        # Third hit: 60 damage dealt, 12 absorbed (20% immunity)
        # This SHOULD update because damage_dealt is higher
        data_store.record_immunity("Goblin", "Fire", 12, 60)

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")
        assert immunity_info["max_damage"] == 60  # Updated to 60
        assert immunity_info["max_immunity"] == 12  # Updated to 12 (from same hit)
        assert immunity_info["sample_count"] == 3

    def test_get_target_resists(self, data_store: DataStore) -> None:
        """Test getting all resist data for a target."""
        data_store.record_immunity("Goblin", "Fire", 10, 50)
        data_store.record_immunity("Goblin", "Cold", 5, 40)

        resists = data_store.get_target_resists("Goblin")

        assert len(resists) == 2
        # Each resist is now (damage_type, max_damage, immunity_absorbed, sample_count)
        damage_types = [r[0] for r in resists]
        assert "Fire" in damage_types
        assert "Cold" in damage_types

        # Verify the structure with max_damage in 2nd position
        for resist in resists:
            assert len(resist) == 4  # (damage_type, max_damage, immunity_absorbed, sample_count)
            damage_type, max_damage, immunity_absorbed, sample_count = resist
            if damage_type == "Fire":
                assert max_damage == 50
                assert immunity_absorbed == 10
                assert sample_count == 1
            elif damage_type == "Cold":
                assert max_damage == 40
                assert immunity_absorbed == 5
                assert sample_count == 1

    def test_get_immunity_for_target_and_type_no_data(self, data_store: DataStore) -> None:
        """Test getting immunity for non-existent target/type."""
        immunity_info = data_store.get_immunity_for_target_and_type("NonExistent", "Fire")

        assert immunity_info["max_immunity"] == 0
        assert immunity_info["max_damage"] == 0
        assert immunity_info["sample_count"] == 0


class TestTargetSummary:
    """Test suite for get_all_targets_summary method."""

    def test_get_all_targets_summary(self, data_store: DataStore) -> None:
        """Test getting summary for all targets."""
        parser = LogParser()

        # Add some data
        data_store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
        data_store.insert_damage_event("Orc", "Cold", 0, 40, "Rogue")

        # Add parser data
        parser.target_ac["Goblin"] = EnemyAC(name="Goblin")
        parser.target_ac["Goblin"].record_hit(20)

        parser.target_saves["Orc"] = EnemySaves(name="Orc")
        parser.target_saves["Orc"].update_save('fort', 5)

        summary = data_store.get_all_targets_summary(parser)

        assert len(summary) == 2
        targets = [s["target"] for s in summary]
        assert "Goblin" in targets
        assert "Orc" in targets


class TestThreadSafety:
    """Test suite for thread safety."""

    def test_concurrent_damage_insertion(self, data_store: DataStore) -> None:
        """Test thread-safe damage event insertion."""
        def insert_events():
            for i in range(100):
                data_store.insert_damage_event(f"Target{i}", "Fire", 0, 50, "Woo")

        threads = [Thread(target=insert_events) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(data_store.events) == 500

    def test_concurrent_dps_updates(self, data_store: DataStore) -> None:
        """Test thread-safe DPS updates."""
        def update_dps():
            ts = datetime.now()
            for i in range(50):
                data_store.update_dps_data("Woo", 10, ts)

        threads = [Thread(target=update_dps) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert data_store.dps_data["Woo"]["total_damage"] == 2500


class TestClearData:
    """Test suite for clear_all_data method."""

    def test_clear_all_data(self, data_store: DataStore) -> None:
        """Test clearing all data from store."""
        # Add various data
        data_store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
        data_store.insert_attack_event("Woo", "Goblin", "hit")
        data_store.update_dps_data("Woo", 100, datetime.now())
        data_store.record_immunity("Goblin", "Fire", 10, 50)

        # Clear
        data_store.clear_all_data()

        # Verify all cleared
        assert len(data_store.events) == 0
        assert len(data_store.attacks) == 0
        assert len(data_store.dps_data) == 0
        assert len(data_store.immunity_data) == 0
        assert data_store.last_damage_timestamp is None


class TestUtilityMethods:
    """Test suite for utility methods."""

    def test_get_all_damage_types(self, data_store: DataStore) -> None:
        """Test getting all unique damage types."""
        data_store.insert_damage_event("Goblin", "Fire", 0, 50, "Woo")
        data_store.insert_damage_event("Orc", "Cold", 0, 40, "Rogue")
        data_store.insert_damage_event("Dragon", "Fire", 0, 100, "Mage")

        damage_types = data_store.get_all_damage_types()

        assert len(damage_types) == 2
        assert "Fire" in damage_types
        assert "Cold" in damage_types

    def test_close_method(self, data_store: DataStore) -> None:
        """Test close method (no-op for in-memory store)."""
        data_store.close()
        # Should not raise exception
        assert True

