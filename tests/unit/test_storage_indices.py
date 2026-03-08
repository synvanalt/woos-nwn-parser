"""Unit tests for storage.py aggregate index optimizations."""

import pytest
from datetime import datetime, timedelta

from app.storage import DataStore


class TestAttackIndices:
    """Test suite for attack aggregate indexing optimizations."""

    def test_attacks_by_attacker_index(self) -> None:
        """Test that attacks are correctly aggregated by attacker."""
        store = DataStore()

        # Insert attacks
        store.insert_attack_event("Woo", "Goblin", "hit", 15, 10, 25)
        store.insert_attack_event("Woo", "Orc", "miss", 8, 10, 18)
        store.insert_attack_event("Ally", "Goblin", "hit", 12, 8, 20)

        # Verify aggregate index is populated
        assert "Woo" in store._attack_stats_by_attacker
        assert "Ally" in store._attack_stats_by_attacker
        assert store._attack_stats_by_attacker["Woo"] == {"hits": 1, "crits": 0, "misses": 1}
        assert store._attack_stats_by_attacker["Ally"] == {"hits": 1, "crits": 0, "misses": 0}

    def test_attacks_by_target_index(self) -> None:
        """Test that attacks are correctly aggregated by target."""
        store = DataStore()

        # Insert attacks
        store.insert_attack_event("Woo", "Goblin", "hit")
        store.insert_attack_event("Ally", "Goblin", "hit")
        store.insert_attack_event("Woo", "Orc", "miss")

        # Verify aggregate index is populated
        assert "Goblin" in store._attack_stats_by_target
        assert "Orc" in store._attack_stats_by_target
        assert store._attack_stats_by_target["Goblin"] == {"hits": 2, "crits": 0, "misses": 0}
        assert store._attack_stats_by_target["Orc"] == {"hits": 0, "crits": 0, "misses": 1}

    def test_attacks_by_attacker_target_index(self) -> None:
        """Test that attacks are correctly aggregated by (attacker, target)."""
        store = DataStore()

        # Insert attacks
        store.insert_attack_event("Woo", "Goblin", "hit")
        store.insert_attack_event("Woo", "Goblin", "hit")
        store.insert_attack_event("Woo", "Orc", "miss")
        store.insert_attack_event("Ally", "Goblin", "critical_hit")

        # Verify aggregate index is populated
        assert ("Woo", "Goblin") in store._attack_stats_by_attacker_target
        assert ("Woo", "Orc") in store._attack_stats_by_attacker_target
        assert ("Ally", "Goblin") in store._attack_stats_by_attacker_target
        assert store._attack_stats_by_attacker_target[("Woo", "Goblin")] == {
            "hits": 2, "crits": 0, "misses": 0
        }
        assert store._attack_stats_by_attacker_target[("Woo", "Orc")] == {
            "hits": 0, "crits": 0, "misses": 1
        }

    def test_get_attack_stats_uses_index(self) -> None:
        """Test that get_attack_stats benefits from indexing."""
        store = DataStore()

        # Insert many attacks
        for i in range(100):
            store.insert_attack_event("Woo", "Goblin", "hit" if i % 2 == 0 else "miss")

        # This should use the index for O(1) lookup
        stats = store.get_attack_stats("Woo", "Goblin")

        assert stats is not None
        assert stats['total_attacks'] == 100
        assert stats['hits'] == 50
        assert stats['misses'] == 50

    def test_indices_cleared_on_clear_all_data(self) -> None:
        """Test that indices are cleared when clearing all data."""
        store = DataStore()

        # Insert data
        store.insert_attack_event("Woo", "Goblin", "hit")
        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo")

        # Verify indices populated
        assert len(store._attack_stats_by_attacker) > 0
        assert len(store._attack_stats_by_target) > 0
        assert len(store._targets_cache) > 0

        # Clear all data
        store.clear_all_data()

        # Verify indices cleared
        assert len(store._attack_stats_by_attacker) == 0
        assert len(store._attack_stats_by_target) == 0
        assert len(store._attack_stats_by_attacker_target) == 0
        assert len(store._targets_cache) == 0
        assert len(store._damage_dealers_cache) == 0


class TestEventIndices:
    """Test suite for event aggregate indexing optimizations."""

    def test_events_by_target_index(self) -> None:
        """Test that damage events are correctly aggregated by target."""
        store = DataStore()
        now = datetime.now()

        # Insert events
        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo", now)
        store.insert_damage_event("Goblin", "Fire", 5, 45, "Woo", now)
        store.insert_damage_event("Orc", "Physical", 0, 30, "Ally", now)

        # Verify aggregate cache is populated
        assert store._target_stats_cache["Goblin"] == {
            "total_hits": 2,
            "total_damage": 95,
            "total_absorbed": 5,
        }
        assert store._target_stats_cache["Orc"] == {
            "total_hits": 1,
            "total_damage": 30,
            "total_absorbed": 0,
        }

    def test_events_by_attacker_target_index(self) -> None:
        """Test that damage events are correctly aggregated by (attacker, target)."""
        store = DataStore()
        now = datetime.now()

        # Insert events
        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo", now)
        store.insert_damage_event("Goblin", "Fire", 5, 45, "Woo", now)
        store.insert_damage_event("Goblin", "Cold", 0, 30, "Ally", now)

        # Verify attacker-target DPS summary is populated
        assert ("Woo", "Goblin") in store._dps_by_attacker_target
        assert ("Ally", "Goblin") in store._dps_by_attacker_target
        assert store._dps_by_attacker_target[("Woo", "Goblin")]["total_damage"] == 95
        assert store._dps_by_attacker_target[("Ally", "Goblin")]["total_damage"] == 30

    def test_get_target_stats_uses_index(self) -> None:
        """Test that get_target_stats benefits from indexing."""
        store = DataStore()
        now = datetime.now()

        # Insert many events
        for i in range(100):
            store.insert_damage_event("Goblin", "Physical", 0, 10, "Woo", now)

        # This should use the index for O(1) lookup
        stats = store.get_target_stats("Goblin")

        assert stats is not None
        total_hits, total_damage, total_absorbed = stats
        assert total_hits == 100
        assert total_damage == 1000

    def test_get_dps_data_for_target_uses_index(self) -> None:
        """Test that get_dps_data_for_target benefits from indexing."""
        store = DataStore()
        now = datetime.now()

        # Insert events
        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo", now)
        store.update_dps_data("Woo", 50, now, {"Physical": 50})

        # Insert more for second attacker
        store.insert_damage_event("Goblin", "Fire", 0, 30, "Ally", now + timedelta(seconds=1))
        store.update_dps_data("Ally", 30, now + timedelta(seconds=1), {"Fire": 30})

        # This should use the index
        dps_list = store.get_dps_data_for_target("Goblin", "per_character")

        assert len(dps_list) == 2
        assert any(d['character'] == 'Woo' for d in dps_list)
        assert any(d['character'] == 'Ally' for d in dps_list)


class TestCacheOptimizations:
    """Test suite for cache optimizations."""

    def test_targets_cache_populated_on_insert(self) -> None:
        """Test that targets cache is populated when inserting damage events."""
        store = DataStore()
        now = datetime.now()

        assert len(store._targets_cache) == 0

        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo", now)
        assert "Goblin" in store._targets_cache

        store.insert_damage_event("Orc", "Fire", 0, 30, "Woo", now)
        assert "Orc" in store._targets_cache
        assert len(store._targets_cache) == 2

    def test_damage_dealers_cache_populated_on_insert(self) -> None:
        """Test that damage dealers cache is populated correctly."""
        store = DataStore()
        now = datetime.now()

        assert len(store._damage_dealers_cache) == 0

        # Insert damage event with damage > 0
        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo", now)
        assert "Woo" in store._damage_dealers_cache

        # Insert event with 0 damage (shouldn't add to cache)
        store.insert_damage_event("Orc", "Fire", 0, 0, "Ally", now)
        assert "Ally" not in store._damage_dealers_cache

        # Insert event with damage (should add)
        store.insert_damage_event("Orc", "Cold", 0, 20, "Ally", now)
        assert "Ally" in store._damage_dealers_cache

    def test_get_all_targets_uses_cache(self) -> None:
        """Test that get_all_targets uses cached set."""
        store = DataStore()
        now = datetime.now()

        # Insert events
        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo", now)
        store.insert_damage_event("Orc", "Fire", 0, 30, "Woo", now)
        store.insert_damage_event("Dragon", "Cold", 0, 100, "Ally", now)

        # Get targets (should use cache)
        targets = store.get_all_targets()

        assert len(targets) == 3
        assert "Goblin" in targets
        assert "Orc" in targets
        assert "Dragon" in targets
        # Should be sorted
        assert targets == sorted(targets)

    def test_get_hit_rate_for_damage_dealers_uses_cache(self) -> None:
        """Test that get_hit_rate_for_damage_dealers uses damage dealers cache."""
        store = DataStore()
        now = datetime.now()

        # Insert damage events
        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo", now)
        store.insert_damage_event("Orc", "Fire", 0, 30, "Ally", now)

        # Insert attacks
        store.insert_attack_event("Woo", "Goblin", "hit")
        store.insert_attack_event("Woo", "Goblin", "miss")
        store.insert_attack_event("Ally", "Orc", "hit")

        # Get hit rates (should use damage dealers cache)
        hit_rates = store.get_hit_rate_for_damage_dealers()

        assert "Woo" in hit_rates
        assert "Ally" in hit_rates
        assert hit_rates["Woo"] == 50.0  # 1 hit, 1 miss
        assert hit_rates["Ally"] == 100.0  # 1 hit, 0 misses

    def test_attack_stats_cache_populated_on_insert(self) -> None:
        """Test that per-attacker aggregate attack stats are updated on insert."""
        store = DataStore()

        store.insert_attack_event("Woo", "Goblin", "hit")
        store.insert_attack_event("Woo", "Goblin", "critical_hit")
        store.insert_attack_event("Woo", "Goblin", "miss")

        assert store._attack_stats_by_attacker["Woo"]["hits"] == 1
        assert store._attack_stats_by_attacker["Woo"]["crits"] == 1
        assert store._attack_stats_by_attacker["Woo"]["misses"] == 1

    def test_attack_stats_by_attacker_target_cache_populated_on_insert(self) -> None:
        """Test that per-attacker target attack aggregates are updated on insert."""
        store = DataStore()

        store.insert_attack_event("Woo", "Goblin", "hit")
        store.insert_attack_event("Woo", "Goblin", "critical_hit")
        store.insert_attack_event("Woo", "Goblin", "miss")

        key = ("Woo", "Goblin")
        assert store._attack_stats_by_attacker_target[key]["hits"] == 1
        assert store._attack_stats_by_attacker_target[key]["crits"] == 1
        assert store._attack_stats_by_attacker_target[key]["misses"] == 1

    def test_target_filtered_dps_summary_cache_populated_on_insert(self) -> None:
        """Test that attacker-target DPS summary is updated on damage insert."""
        store = DataStore()
        now = datetime.now()

        store.insert_damage_event("Goblin", "Physical", 0, 50, "Woo", now)
        store.insert_damage_event("Goblin", "Fire", 0, 20, "Woo", now + timedelta(seconds=2))

        summary = store._dps_by_attacker_target[("Woo", "Goblin")]
        assert summary["total_damage"] == 70
        assert summary["first_timestamp"] == now
        assert summary["last_timestamp"] == now + timedelta(seconds=2)
        assert summary["damage_by_type"] == {"Physical": 50, "Fire": 20}

    def test_damage_dealers_by_target_cache_populated_on_insert(self) -> None:
        """Test that per-target damage dealer cache is updated only for positive damage."""
        store = DataStore()
        now = datetime.now()

        store.insert_damage_event("Goblin", "Physical", 0, 0, "Woo", now)
        assert "Goblin" not in store._damage_dealers_by_target

        store.insert_damage_event("Goblin", "Physical", 0, 25, "Woo", now)
        assert store._damage_dealers_by_target["Goblin"] == {"Woo"}


class TestIndexPerformance:
    """Test suite for performance characteristics of indices."""

    def test_index_lookup_faster_than_iteration(self) -> None:
        """Test that indexed lookups are faster (implicit through usage)."""
        store = DataStore()
        now = datetime.now()

        # Insert large number of attacks for multiple targets
        # Pattern: i=0: Attacker_0/Target_0, i=10: Attacker_0/Target_0, etc.
        # So Attacker_0 + Target_0 appears at i = 0,10,20,...,990 = 100 times
        for i in range(1000):
            target = f"Target_{i % 10}"
            attacker = f"Attacker_{i % 5}"
            store.insert_attack_event(attacker, target, "hit" if i % 2 == 0 else "miss")

        # Query should be fast (uses index)
        stats = store.get_attack_stats("Attacker_0", "Target_0")

        assert stats is not None
        assert stats['total_attacks'] == 100  # Occurs at i = 0, 10, 20, ..., 990

    def test_indices_scale_with_data(self) -> None:
        """Test that aggregate indices correctly scale with amount of data."""
        store = DataStore()
        now = datetime.now()

        num_targets = 50
        num_attackers = 10

        # Insert large dataset
        for i in range(1000):
            target = f"Target_{i % num_targets}"
            attacker = f"Attacker_{i % num_attackers}"
            store.insert_attack_event(attacker, target, "hit")
            store.insert_damage_event(target, "Physical", 0, 10, attacker, now)

        # Verify all aggregate indices populated correctly
        assert len(store._attack_stats_by_target) == num_targets
        assert len(store._attack_stats_by_attacker) == num_attackers
        assert len(store._targets_cache) == num_targets
        assert len(store._damage_dealers_cache) == num_attackers

        # Verify query still works efficiently
        targets = store.get_all_targets()
        assert len(targets) == num_targets

    def test_raw_histories_trim_while_lifetime_aggregates_remain(self) -> None:
        """Raw event/attack buffers should trim without affecting lifetime totals."""
        store = DataStore(max_events_history=2, max_attacks_history=2)
        now = datetime.now()

        for i in range(5):
            store.insert_attack_event("Woo", "Goblin", "hit")
            store.insert_damage_event("Goblin", "Physical", 0, 10, "Woo", now + timedelta(seconds=i))

        assert len(store.attacks) == 2
        assert len(store.events) == 2

        atk = store.get_attack_stats("Woo", "Goblin")
        assert atk is not None
        assert atk["total_attacks"] == 5
        assert atk["hits"] == 5

        target_stats = store.get_target_stats("Goblin")
        assert target_stats == (5, 50, 0)

