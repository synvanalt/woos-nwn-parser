"""Unit tests for DataStore.

Tests in-memory data storage, DPS tracking, attack tracking,
immunity tracking, and time tracking modes.
"""

import pytest
from datetime import datetime, timedelta
from threading import Thread
import time

from app.models import AttackMutation, DamageMutation, ImmunityMutation
from app.storage import DataStore
from tests.helpers.store_mutations import apply, attack, damage_row, dps_update, epic_dodge, immunity, save


class TestDataStoreInitialization:
    """Test suite for DataStore initialization."""

    def test_initialization(self, data_store: DataStore) -> None:
        """Test DataStore initializes with empty state."""
        assert len(data_store.events) == 0
        assert len(data_store.attacks) == 0
        assert len(data_store.dps_data) == 0
        assert len(data_store.immunity_data) == 0
        assert data_store.last_damage_timestamp is None

    def test_initialization_uses_named_default_history_limits(self) -> None:
        """Default raw-history retention should remain backward-compatible."""
        store = DataStore()

        assert store.max_events_history == DataStore.DEFAULT_MAX_EVENTS_HISTORY
        assert store.max_attacks_history == DataStore.DEFAULT_MAX_ATTACKS_HISTORY
        assert store.events.maxlen == DataStore.DEFAULT_MAX_EVENTS_HISTORY
        assert store.attacks.maxlen == DataStore.DEFAULT_MAX_ATTACKS_HISTORY

    def test_initialization_accepts_none_for_default_history_limits(self) -> None:
        """Explicit None should resolve to the same safe defaults."""
        store = DataStore(max_events_history=None, max_attacks_history=None)

        assert store.max_events_history == DataStore.DEFAULT_MAX_EVENTS_HISTORY
        assert store.max_attacks_history == DataStore.DEFAULT_MAX_ATTACKS_HISTORY

    def test_initialization_clamps_invalid_history_limits(self) -> None:
        """Configured raw-history limits should be normalized to at least one item."""
        store = DataStore(max_events_history=0, max_attacks_history=-5)

        assert store.max_events_history == 1
        assert store.max_attacks_history == 1
        assert store.events.maxlen == 1
        assert store.attacks.maxlen == 1


class TestApplyMutations:
    """Test suite for the public batch mutation API."""

    def test_apply_mutations_updates_damage_and_dps_in_one_batch(self, data_store: DataStore) -> None:
        ts = datetime.now()
        data_store.apply_mutations([
            DamageMutation(
                target="Goblin",
                total_damage=50,
                attacker="Woo",
                timestamp=ts,
                count_for_dps=True,
                damage_types={"Fire": 50},
            ),
            DamageMutation(
                target="Goblin",
                damage_type="Fire",
                total_damage=50,
                attacker="Woo",
                timestamp=ts,
            ),
        ])

        assert data_store.dps_data["Woo"]["total_damage"] == 50
        assert data_store.get_target_stats("Goblin") == (1, 50, 0)
        assert data_store.get_earliest_timestamp() == ts
        assert data_store.get_earliest_timestamp_for_target("Goblin") == ts

    def test_apply_mutations_updates_mixed_mutations_with_single_version_bump(self, data_store: DataStore) -> None:
        start_version = data_store.version
        data_store.apply_mutations([
            AttackMutation(attacker="Woo", target="Goblin", outcome="hit"),
            ImmunityMutation(target="Goblin", damage_type="Fire", immunity_points=5, damage_dealt=20),
        ])

        assert data_store.version == start_version + 1
        assert data_store.get_attack_stats("Woo", "Goblin") is not None
        assert data_store.get_immunity_for_target_and_type("Goblin", "Fire")["sample_count"] == 1



class TestDamageEventInsertion:
    """Test suite for insert_damage_event method."""

    def test_insert_single_damage_event(self, data_store: DataStore) -> None:
        """Test inserting a single damage event."""
        apply(data_store, damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=10, total_damage=40, attacker="Woo"))

        assert len(data_store.events) == 1
        event = data_store.events[0]
        assert event.target == "Goblin"
        assert event.damage_type == "Fire"
        assert event.immunity_absorbed == 10
        assert event.total_damage_dealt == 40
        assert event.attacker == "Woo"

    def test_insert_multiple_damage_events(self, data_store: DataStore) -> None:
        """Test inserting multiple damage events."""
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=10, total_damage=40, attacker="Woo"),
            damage_row(target="Orc", damage_type="Cold", immunity_absorbed=5, total_damage=30, attacker="Rogue"),
        )

        assert len(data_store.events) == 2

    def test_insert_damage_with_timestamp(self, data_store: DataStore) -> None:
        """Test inserting damage event with custom timestamp."""
        ts = datetime(2026, 1, 9, 14, 30, 0)
        apply(data_store, damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=10, total_damage=40, attacker="Woo", timestamp=ts))

        event = data_store.events[0]
        assert event.timestamp == ts

    def test_insert_damage_without_timestamp(self, data_store: DataStore) -> None:
        """Test inserting damage event without timestamp uses current time."""
        apply(data_store, damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=10, total_damage=40, attacker="Woo"))

        event = data_store.events[0]
        assert isinstance(event.timestamp, datetime)


class TestAttackEventInsertion:
    """Test suite for insert_attack_event method."""

    def test_insert_attack_hit(self, data_store: DataStore) -> None:
        """Test inserting an attack hit event."""
        apply(data_store, attack(attacker="Woo", target="Goblin", outcome="hit", roll=15, bonus=5, total=20))

        assert len(data_store.attacks) == 1
        attack_event = data_store.attacks[0]
        assert attack_event.attacker == "Woo"
        assert attack_event.target == "Goblin"
        assert attack_event.outcome == "hit"
        assert attack_event.roll == 15
        assert attack_event.bonus == 5
        assert attack_event.total == 20

    def test_insert_attack_miss(self, data_store: DataStore) -> None:
        """Test inserting an attack miss event."""
        apply(data_store, attack(attacker="Woo", target="Goblin", outcome="miss", roll=8, bonus=5, total=13))

        attack_event = data_store.attacks[0]
        assert attack_event.outcome == "miss"

    def test_insert_attack_critical(self, data_store: DataStore) -> None:
        """Test inserting a critical hit event."""
        apply(data_store, attack(attacker="Woo", target="Goblin", outcome="critical_hit", roll=18, bonus=5, total=23))

        attack_event = data_store.attacks[0]
        assert attack_event.outcome == "critical_hit"


class TestDPSTracking:
    """Test suite for DPS data tracking."""

    def test_update_dps_data_new_character(self, data_store: DataStore) -> None:
        """Test updating DPS data for a new character."""
        ts = datetime.now()
        apply(data_store, dps_update(attacker="Woo", total_damage=100, timestamp=ts, damage_types={"Fire": 60, "Physical": 40}))

        assert "Woo" in data_store.dps_data
        assert data_store.dps_data["Woo"]["total_damage"] == 100
        assert data_store.dps_data["Woo"]["first_timestamp"] == ts
        assert data_store.dps_data["Woo"]["damage_by_type"]["Fire"] == 60
        assert data_store.dps_data["Woo"]["damage_by_type"]["Physical"] == 40

    def test_update_dps_data_existing_character(self, data_store: DataStore) -> None:
        """Test updating DPS data for existing character accumulates damage."""
        ts1 = datetime.now()
        ts2 = ts1 + timedelta(seconds=5)

        apply(
            data_store,
            dps_update(attacker="Woo", total_damage=100, timestamp=ts1, damage_types={"Fire": 100}),
            dps_update(attacker="Woo", total_damage=50, timestamp=ts2, damage_types={"Fire": 50}),
        )

        assert data_store.dps_data["Woo"]["total_damage"] == 150
        assert data_store.dps_data["Woo"]["damage_by_type"]["Fire"] == 150

    def test_update_dps_data_updates_global_timestamp(self, data_store: DataStore) -> None:
        """Test that updating DPS data updates global last damage timestamp."""
        ts = datetime.now()
        apply(data_store, dps_update(attacker="Woo", total_damage=100, timestamp=ts))

        assert data_store.last_damage_timestamp == ts

    def test_get_earliest_timestamp(self, data_store: DataStore) -> None:
        """Test getting earliest timestamp across all characters."""
        ts1 = datetime(2026, 1, 9, 14, 30, 0)
        ts2 = datetime(2026, 1, 9, 14, 25, 0)  # Earlier
        ts3 = datetime(2026, 1, 9, 14, 35, 0)

        apply(
            data_store,
            dps_update(attacker="Woo", total_damage=100, timestamp=ts1),
            dps_update(attacker="Rogue", total_damage=50, timestamp=ts2),
            dps_update(attacker="Mage", total_damage=75, timestamp=ts3),
        )

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

        apply(data_store, dps_update(attacker="Woo", total_damage=100, timestamp=ts1))
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

        apply(
            data_store,
            dps_update(attacker="Woo", total_damage=100, timestamp=ts1, damage_types={"Fire": 100}),
            dps_update(attacker="Rogue", total_damage=50, timestamp=ts2, damage_types={"Cold": 50}),
        )

        dps_list = data_store.get_dps_data(
            time_tracking_mode="global",
            global_start_time=ts_start
        )

        assert len(dps_list) == 2
        # Both characters use same global time window

    def test_get_dps_data_sorted_by_dps(self, data_store: DataStore) -> None:
        """Test that DPS data is sorted by DPS descending."""
        ts = datetime.now()

        apply(
            data_store,
            dps_update(attacker="Woo", total_damage=100, timestamp=ts),
            dps_update(attacker="Rogue", total_damage=200, timestamp=ts),
            dps_update(attacker="Mage", total_damage=150, timestamp=ts),
        )
        data_store.last_damage_timestamp = ts + timedelta(seconds=10)

        dps_list = data_store.get_dps_data(time_tracking_mode="per_character")

        assert dps_list[0]["character"] == "Rogue"  # Highest DPS
        assert dps_list[1]["character"] == "Mage"
        assert dps_list[2]["character"] == "Woo"

    def test_get_dps_data_cache_invalidates_after_version_change(self, data_store: DataStore) -> None:
        """Cached DPS rows should refresh automatically after a store mutation."""
        ts = datetime.now()
        apply(data_store, dps_update(attacker="Woo", total_damage=100, timestamp=ts))
        data_store.last_damage_timestamp = ts + timedelta(seconds=10)

        first = data_store.get_dps_data(time_tracking_mode="per_character")
        assert first[0]["total_damage"] == 100

        apply(data_store, dps_update(attacker="Woo", total_damage=50, timestamp=ts + timedelta(seconds=5)))
        data_store.last_damage_timestamp = ts + timedelta(seconds=15)

        second = data_store.get_dps_data(time_tracking_mode="per_character")
        assert second[0]["total_damage"] == 150
        assert second[0]["dps"] == 10.0

    def test_get_dps_breakdown_by_type(self, data_store: DataStore) -> None:
        """Test getting DPS breakdown by damage type."""
        ts = datetime.now()
        damage_types = {"Fire": 60, "Physical": 40}

        apply(data_store, dps_update(attacker="Woo", total_damage=100, timestamp=ts, damage_types=damage_types))
        data_store.last_damage_timestamp = ts + timedelta(seconds=10)

        breakdown = data_store.get_dps_breakdown_by_type(
            "Woo", time_tracking_mode="per_character"
        )

        assert len(breakdown) == 2
        assert breakdown[0]["damage_type"] == "Fire"
        assert breakdown[0]["total_damage"] == 60
        assert breakdown[1]["damage_type"] == "Physical"

    def test_get_dps_breakdowns_by_type_bulk(self, data_store: DataStore) -> None:
        """Test bulk DPS breakdown retrieval for multiple characters."""
        ts = datetime.now()
        apply(
            data_store,
            dps_update(attacker="Woo", total_damage=100, timestamp=ts, damage_types={"Fire": 60, "Physical": 40}),
            dps_update(attacker="Rogue", total_damage=50, timestamp=ts, damage_types={"Cold": 50}),
        )
        data_store.last_damage_timestamp = ts + timedelta(seconds=10)

        breakdowns = data_store.get_dps_breakdowns_by_type(
            ["Woo", "Rogue"],
            time_tracking_mode="per_character",
        )

        assert set(breakdowns.keys()) == {"Woo", "Rogue"}
        assert breakdowns["Woo"][0]["damage_type"] == "Fire"
        assert breakdowns["Woo"][0]["total_damage"] == 60
        assert breakdowns["Rogue"] == [
            {"damage_type": "Cold", "total_damage": 50, "dps": 5.0}
        ]

    def test_get_dps_breakdowns_by_type_bulk_missing_character(self, data_store: DataStore) -> None:
        """Missing characters should return empty breakdown lists in bulk calls."""
        ts = datetime.now()
        apply(data_store, dps_update(attacker="Woo", total_damage=100, timestamp=ts, damage_types={"Fire": 100}))
        data_store.last_damage_timestamp = ts + timedelta(seconds=5)

        breakdowns = data_store.get_dps_breakdowns_by_type(
            ["Woo", "Mage"],
            time_tracking_mode="per_character",
        )

        assert "Woo" in breakdowns
        assert "Mage" in breakdowns
        assert breakdowns["Mage"] == []


class TestTargetFiltering:
    """Test suite for target-specific queries."""

    def test_get_all_targets(self, data_store: DataStore) -> None:
        """Test getting all unique targets."""
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
            damage_row(target="Orc", damage_type="Cold", total_damage=40, attacker="Rogue"),
            damage_row(target="Goblin", damage_type="Physical", total_damage=30, attacker="Woo"),
        )

        targets = data_store.get_all_targets()

        assert len(targets) == 2
        assert "Goblin" in targets
        assert "Orc" in targets

    def test_get_all_targets_sorts_case_insensitively(self, data_store: DataStore) -> None:
        """Target names should sort alphabetically without case sensitivity."""
        apply(
            data_store,
            damage_row(target="zombie", damage_type="Fire", total_damage=50, attacker="Woo"),
            damage_row(target="TYRMON risen", damage_type="Cold", total_damage=40, attacker="Rogue"),
            damage_row(target="Tyrmon scout", damage_type="Physical", total_damage=30, attacker="Woo"),
        )

        targets = data_store.get_all_targets()

        assert targets == ["TYRMON risen", "Tyrmon scout", "zombie"]

    def test_get_target_stats(self, data_store: DataStore) -> None:
        """Test getting stats for a specific target."""
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=10, total_damage=40, attacker="Woo"),
            damage_row(target="Goblin", damage_type="Physical", immunity_absorbed=5, total_damage=30, attacker="Woo"),
        )

        stats = data_store.get_target_stats("Goblin")

        assert stats is not None
        assert stats[0] == 2  # total_hits
        assert stats[1] == 70  # total_damage
        assert stats[2] == 15  # total_absorbed

    def test_get_target_stats_no_data(self, data_store: DataStore) -> None:
        """Test getting stats for target with no data."""
        stats = data_store.get_target_stats("NonExistent")
        assert stats is None

    def test_get_target_damage_type_summary_uses_indexed_values(self, data_store: DataStore) -> None:
        """Test combined target damage-type summaries from indexed store data."""
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=20, attacker="Woo"),
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
            damage_row(target="Goblin", damage_type="Cold", total_damage=15, attacker="Woo"),
            immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50),
        )

        summary = data_store.get_target_damage_type_summary("Goblin")

        assert len(summary) == 2
        fire = next(item for item in summary if item["damage_type"] == "Fire")
        cold = next(item for item in summary if item["damage_type"] == "Cold")

        assert fire["max_event_damage"] == 50
        assert fire["max_immunity_damage"] == 50
        assert fire["immunity_absorbed"] == 10
        assert fire["sample_count"] == 1

        assert cold["max_event_damage"] == 15
        assert cold["max_immunity_damage"] == 0
        assert cold["immunity_absorbed"] == 0
        assert cold["sample_count"] == 0

    def test_get_target_damage_type_summary_returns_defensive_copies(self, data_store: DataStore) -> None:
        """Mutating a returned summary row should not taint the cache."""
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=20, attacker="Woo"),
            immunity(target="Goblin", damage_type="Fire", immunity_points=5, damage_dealt=20),
        )

        first = data_store.get_target_damage_type_summary("Goblin")
        first[0]["max_event_damage"] = 999

        second = data_store.get_target_damage_type_summary("Goblin")
        assert second[0]["max_event_damage"] == 20

    def test_get_dps_data_for_target(self, data_store: DataStore) -> None:
        """Test getting DPS data filtered by target."""
        ts = datetime.now()

        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo", timestamp=ts),
            damage_row(target="Orc", damage_type="Cold", total_damage=40, attacker="Woo", timestamp=ts),
            damage_row(target="Goblin", damage_type="Physical", total_damage=30, attacker="Rogue", timestamp=ts),
        )

        dps_list = data_store.get_dps_data_for_target(
            "Goblin", time_tracking_mode="per_character"
        )

        # Should only include damage to Goblin
        total_goblin_damage = sum(d["total_damage"] for d in dps_list)
        assert total_goblin_damage == 80  # 50 + 30

    def test_get_dps_breakdown_by_type_for_target_uses_cached_summary(self, data_store: DataStore) -> None:
        """Test target-filtered breakdown uses aggregated attacker-target data."""
        ts = datetime.now()

        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo", timestamp=ts),
            damage_row(target="Goblin", damage_type="Physical", total_damage=30, attacker="Woo", timestamp=ts),
            damage_row(target="Orc", damage_type="Cold", total_damage=40, attacker="Woo", timestamp=ts),
        )

        breakdown = data_store.get_dps_breakdown_by_type_for_target(
            "Woo", "Goblin", time_tracking_mode="per_character"
        )

        assert breakdown == [
            {'damage_type': 'Fire', 'total_damage': 50, 'dps': 50.0},
            {'damage_type': 'Physical', 'total_damage': 30, 'dps': 30.0},
        ]

    def test_get_dps_breakdowns_by_type_bulk_for_target(self, data_store: DataStore) -> None:
        """Test bulk target-filtered breakdown retrieval from cached summaries."""
        ts = datetime.now()
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo", timestamp=ts),
            damage_row(target="Goblin", damage_type="Physical", total_damage=30, attacker="Woo", timestamp=ts),
            damage_row(target="Goblin", damage_type="Cold", total_damage=40, attacker="Rogue", timestamp=ts),
        )

        breakdowns = data_store.get_dps_breakdowns_by_type(
            ["Woo", "Rogue", "Mage"],
            target="Goblin",
            time_tracking_mode="per_character",
        )

        assert breakdowns["Woo"] == [
            {'damage_type': 'Fire', 'total_damage': 50, 'dps': 50.0},
            {'damage_type': 'Physical', 'total_damage': 30, 'dps': 30.0},
        ]
        assert breakdowns["Rogue"] == [
            {'damage_type': 'Cold', 'total_damage': 40, 'dps': 40.0}
        ]
        assert breakdowns["Mage"] == []


class TestAttackStats:
    """Test suite for attack statistics methods."""

    def test_get_attack_stats(self, data_store: DataStore) -> None:
        """Test getting attack statistics for attacker vs target."""
        apply(
            data_store,
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="critical_hit"),
            attack(attacker="Woo", target="Goblin", outcome="miss"),
        )

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
        apply(
            data_store,
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="miss"),
            attack(attacker="Rogue", target="Orc", outcome="hit"),
            attack(attacker="Rogue", target="Orc", outcome="miss"),
            attack(attacker="Rogue", target="Orc", outcome="miss"),
        )

        hit_rates = data_store.get_hit_rate_per_character()

        assert hit_rates["Woo"] == pytest.approx(66.67, abs=0.1)
        assert hit_rates["Rogue"] == pytest.approx(33.33, abs=0.1)

    def test_get_hit_rate_for_damage_dealers(self, data_store: DataStore) -> None:
        """Test getting hit rate only for characters who dealt damage."""
        # Character with damage and attacks
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="miss"),
            attack(attacker="Rogue", target="Orc", outcome="hit"),
            attack(attacker="Rogue", target="Orc", outcome="miss"),
        )

        hit_rates = data_store.get_hit_rate_for_damage_dealers()

        assert "Woo" in hit_rates
        assert "Rogue" not in hit_rates  # No damage dealt

    def test_get_hit_rate_for_damage_dealers_cache_invalidates_after_attack(self, data_store: DataStore) -> None:
        """Cached hit rates should refresh automatically after attack mutations."""
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
            attack(attacker="Woo", target="Goblin", outcome="hit"),
        )

        first = data_store.get_hit_rate_for_damage_dealers()
        assert first["Woo"] == 100.0

        apply(data_store, attack(attacker="Woo", target="Goblin", outcome="miss"))

        second = data_store.get_hit_rate_for_damage_dealers()
        assert second["Woo"] == 50.0


class TestImmunityTracking:
    """Test suite for immunity tracking methods."""

    def test_record_immunity(self, data_store: DataStore) -> None:
        """Test recording immunity data."""
        apply(data_store, immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50))

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")

        assert immunity_info["max_immunity"] == 10
        assert immunity_info["max_damage"] == 50
        assert immunity_info["sample_count"] == 1

    def test_record_immunity_updates_maximum(self, data_store: DataStore) -> None:
        """Test that recording immunity keeps maximum values."""
        apply(
            data_store,
            immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50),
            immunity(target="Goblin", damage_type="Fire", immunity_points=15, damage_dealt=70),
        )

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
        apply(data_store, immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50))

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")
        assert immunity_info["max_damage"] == 50
        assert immunity_info["max_immunity"] == 10

        # Second hit: 0 damage dealt, 50 absorbed (100% temporary immunity buff)
        # This should NOT update the record because damage_dealt is lower
        apply(data_store, immunity(target="Goblin", damage_type="Fire", immunity_points=50, damage_dealt=0))

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")
        assert immunity_info["max_damage"] == 50  # Still 50, not 0
        assert immunity_info["max_immunity"] == 10  # Still 10, not 50
        assert immunity_info["sample_count"] == 2  # Both samples counted

        # Third hit: 60 damage dealt, 12 absorbed (20% immunity)
        # This SHOULD update because damage_dealt is higher
        apply(data_store, immunity(target="Goblin", damage_type="Fire", immunity_points=12, damage_dealt=60))

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Fire")
        assert immunity_info["max_damage"] == 60  # Updated to 60
        assert immunity_info["max_immunity"] == 12  # Updated to 12 (from same hit)
        assert immunity_info["sample_count"] == 3

    def test_record_immunity_zero_damage_uses_highest_absorbed_tiebreak(self, data_store: DataStore) -> None:
        """Zero-damage matched samples should keep the highest absorbed value."""
        apply(
            data_store,
            immunity(target="Goblin", damage_type="Acid", immunity_points=50, damage_dealt=0),
            immunity(target="Goblin", damage_type="Acid", immunity_points=55, damage_dealt=0),
        )

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Acid")

        assert immunity_info["max_damage"] == 0
        assert immunity_info["max_immunity"] == 55
        assert immunity_info["sample_count"] == 2

    def test_record_immunity_prefers_higher_damage_before_absorbed_tiebreak(self, data_store: DataStore) -> None:
        """Higher damage remains the primary sort key for the stored pair."""
        apply(
            data_store,
            immunity(target="Goblin", damage_type="Acid", immunity_points=55, damage_dealt=0),
            immunity(target="Goblin", damage_type="Acid", immunity_points=3, damage_dealt=10),
            immunity(target="Goblin", damage_type="Acid", immunity_points=8, damage_dealt=10),
        )

        immunity_info = data_store.get_immunity_for_target_and_type("Goblin", "Acid")

        assert immunity_info["max_damage"] == 10
        assert immunity_info["max_immunity"] == 8
        assert immunity_info["sample_count"] == 3

    def test_get_target_resists(self, data_store: DataStore) -> None:
        """Test getting all resist data for a target."""
        apply(
            data_store,
            immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50),
            immunity(target="Goblin", damage_type="Cold", immunity_points=5, damage_dealt=40),
        )

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
        # Add some data
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
            damage_row(target="Orc", damage_type="Cold", total_damage=40, attacker="Rogue"),
        )

        # Add target stats directly to DataStore-owned structures
        data_store.record_target_attack_roll("Woo", "Goblin", "hit", 15, 5, 20)
        apply(data_store, save(target="Orc", save_key="fort", bonus=5))

        summary = data_store.get_all_targets_summary()

        assert len(summary) == 2
        targets = [s["target"] for s in summary]
        assert "Goblin" in targets
        assert "Orc" in targets

    def test_get_all_targets_summary_includes_damage_taken(self, data_store: DataStore) -> None:
        """Test that summary includes total damage taken by each target."""
        # Add multiple damage events against same target from different attackers
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
            damage_row(target="Goblin", damage_type="Cold", total_damage=30, attacker="Rogue"),
            damage_row(target="Goblin", damage_type="Physical", total_damage=20, attacker="Woo"),
            damage_row(target="Orc", damage_type="Fire", total_damage=100, attacker="Woo"),
        )

        summary = data_store.get_all_targets_summary()

        # Find Goblin and Orc in the summary
        goblin_summary = next(s for s in summary if s["target"] == "Goblin")
        orc_summary = next(s for s in summary if s["target"] == "Orc")

        # Goblin took 50 + 30 + 20 = 100 total damage
        assert goblin_summary["damage_taken"] == "100"
        # Orc took 100 total damage
        assert orc_summary["damage_taken"] == "100"

    def test_get_all_targets_summary_damage_taken_zero_when_no_damage(self, data_store: DataStore) -> None:
        """Test that damage_taken is 0 when target has no damage events."""
        # Insert an attack event but no damage event for target
        apply(data_store, attack(attacker="Woo", target="Goblin", outcome="miss"))

        # Manually add target via damage event with 0 damage to get it in the list
        apply(data_store, damage_row(target="Goblin", damage_type="Physical", total_damage=0, attacker="Woo"))

        summary = data_store.get_all_targets_summary()

        goblin_summary = next(s for s in summary if s["target"] == "Goblin")
        assert goblin_summary["damage_taken"] == "0"

    def test_get_all_targets_summary_uses_datastore_owned_ac_ab_save(self, data_store: DataStore) -> None:
        """Test summary values are sourced from DataStore target stat state."""
        apply(data_store, damage_row(target="Goblin", damage_type="Physical", total_damage=10, attacker="Woo"))
        data_store.record_target_attack_roll("Goblin", "Woo", "hit", 14, 8, 22)
        data_store.record_target_attack_roll("Woo", "Goblin", "miss", 10, 20, 30)
        data_store.record_target_attack_roll("Woo", "Goblin", "hit", 11, 20, 31)
        apply(
            data_store,
            epic_dodge(target="Goblin"),
            save(target="Goblin", save_key="fort", bonus=5),
        )

        summary = data_store.get_all_targets_summary()
        goblin_summary = next(s for s in summary if s["target"] == "Goblin")

        assert goblin_summary["ab"] == "8"
        assert goblin_summary["ac"] == "~31"
        assert goblin_summary["fortitude"] == "5"

    def test_get_all_targets_summary_returns_defensive_copies(self, data_store: DataStore) -> None:
        """Mutating a returned target summary should not taint later reads."""
        apply(data_store, damage_row(target="Goblin", damage_type="Physical", total_damage=10, attacker="Woo"))

        first = data_store.get_all_targets_summary()
        first[0]["damage_taken"] = "999"

        second = data_store.get_all_targets_summary()
        assert second[0]["damage_taken"] == "10"

    def test_concealment_miss_does_not_affect_ac_estimate(self, data_store: DataStore) -> None:
        """Test concealment misses are excluded from AC inference in DataStore."""
        apply(data_store, damage_row(target="Boss", damage_type="Physical", total_damage=1, attacker="Woo"))
        data_store.record_target_attack_roll("Woo", "Boss", "hit", 11, 20, 31)
        data_store.record_target_attack_roll(
            "Woo",
            "Boss",
            "miss",
            19,
            20,
            39,
            is_concealment=True,
        )

        summary = data_store.get_all_targets_summary()
        boss_summary = next(s for s in summary if s["target"] == "Boss")
        assert boss_summary["ac"] == "≤31"


class TestThreadSafety:
    """Test suite for thread safety."""

    def test_concurrent_damage_insertion(self, data_store: DataStore) -> None:
        """Test thread-safe damage event insertion."""
        def insert_events():
            for i in range(100):
                apply(data_store, damage_row(target=f"Target{i}", damage_type="Fire", total_damage=50, attacker="Woo"))

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
                apply(data_store, dps_update(attacker="Woo", total_damage=10, timestamp=ts))

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
        now = datetime.now()
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            dps_update(attacker="Woo", total_damage=100, timestamp=now),
            immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50),
        )

        # Clear
        data_store.clear_all_data()

        # Verify all cleared
        assert len(data_store.events) == 0
        assert len(data_store.attacks) == 0
        assert len(data_store.dps_data) == 0
        assert len(data_store.immunity_data) == 0
        assert data_store.get_target_damage_type_summary("Goblin") == []
        assert data_store.last_damage_timestamp is None

    def test_clear_all_data_increments_version(self, data_store: DataStore) -> None:
        """Clearing the store should invalidate version-keyed read caches."""
        apply(data_store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))
        start_version = data_store.version

        data_store.clear_all_data()

        assert data_store.version == start_version + 1

    def test_clear_all_data_invalidates_target_summary_cache(self, data_store: DataStore) -> None:
        """Target summary reads should not return stale rows after a reset."""
        apply(data_store, damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"))

        summary_before_clear = data_store.get_all_targets_summary()
        assert [row["target"] for row in summary_before_clear] == ["Goblin"]

        data_store.clear_all_data()

        assert data_store.get_all_targets_summary() == []


class TestUtilityMethods:
    """Test suite for utility methods."""

    def test_get_all_damage_types(self, data_store: DataStore) -> None:
        """Test getting all unique damage types."""
        apply(
            data_store,
            damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
            damage_row(target="Orc", damage_type="Cold", total_damage=40, attacker="Rogue"),
            damage_row(target="Dragon", damage_type="Fire", total_damage=100, attacker="Mage"),
        )

        damage_types = data_store.get_all_damage_types()

        assert len(damage_types) == 2
        assert "Fire" in damage_types
        assert "Cold" in damage_types

    def test_close_method(self, data_store: DataStore) -> None:
        """Test close method (no-op for in-memory store)."""
        data_store.close()
        # Should not raise exception
        assert True

