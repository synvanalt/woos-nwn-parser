"""Unit tests for storage.py aggregate index optimizations."""

from datetime import datetime, timedelta

from app.storage import DataStore
from tests.helpers.store_mutations import apply, attack, damage_row, dps_update


class TestAttackIndices:
    """Test suite for attack aggregate indexing optimizations."""

    def test_attacks_by_attacker_index(self) -> None:
        store = DataStore()
        apply(
            store,
            attack(attacker="Woo", target="Goblin", outcome="hit", roll=15, bonus=10, total=25),
            attack(attacker="Woo", target="Orc", outcome="miss", roll=8, bonus=10, total=18),
            attack(attacker="Ally", target="Goblin", outcome="hit", roll=12, bonus=8, total=20),
        )

        assert "Woo" in store._attack_stats_by_attacker
        assert "Ally" in store._attack_stats_by_attacker
        assert store._attack_stats_by_attacker["Woo"] == {"hits": 1, "crits": 0, "misses": 1}
        assert store._attack_stats_by_attacker["Ally"] == {"hits": 1, "crits": 0, "misses": 0}

    def test_attacks_by_target_index(self) -> None:
        store = DataStore()
        apply(
            store,
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Ally", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Orc", outcome="miss"),
        )

        assert "Goblin" in store._attack_stats_by_target
        assert "Orc" in store._attack_stats_by_target
        assert store._attack_stats_by_target["Goblin"] == {"hits": 2, "crits": 0, "misses": 0}
        assert store._attack_stats_by_target["Orc"] == {"hits": 0, "crits": 0, "misses": 1}

    def test_attacks_by_attacker_target_index(self) -> None:
        store = DataStore()
        apply(
            store,
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Orc", outcome="miss"),
            attack(attacker="Ally", target="Goblin", outcome="critical_hit"),
        )

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
        store = DataStore()
        for i in range(100):
            apply(store, attack(attacker="Woo", target="Goblin", outcome="hit" if i % 2 == 0 else "miss"))

        stats = store.get_attack_stats("Woo", "Goblin")

        assert stats is not None
        assert stats["total_attacks"] == 100
        assert stats["hits"] == 50
        assert stats["misses"] == 50

    def test_indices_cleared_on_clear_all_data(self) -> None:
        store = DataStore()
        apply(
            store,
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo"),
        )

        assert len(store._attack_stats_by_attacker) > 0
        assert len(store._attack_stats_by_target) > 0
        assert len(store._targets_cache) > 0

        store.clear_all_data()

        assert len(store._attack_stats_by_attacker) == 0
        assert len(store._attack_stats_by_target) == 0
        assert len(store._attack_stats_by_attacker_target) == 0
        assert len(store._targets_cache) == 0
        assert len(store._damage_dealers_cache) == 0


class TestEventIndices:
    """Test suite for event aggregate indexing optimizations."""

    def test_events_by_target_index(self) -> None:
        store = DataStore()
        now = datetime.now()
        apply(
            store,
            damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo", timestamp=now),
            damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=5, total_damage=45, attacker="Woo", timestamp=now),
            damage_row(target="Orc", damage_type="Physical", total_damage=30, attacker="Ally", timestamp=now),
        )

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
        store = DataStore()
        now = datetime.now()
        apply(
            store,
            damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo", timestamp=now),
            damage_row(target="Goblin", damage_type="Fire", immunity_absorbed=5, total_damage=45, attacker="Woo", timestamp=now),
            damage_row(target="Goblin", damage_type="Cold", total_damage=30, attacker="Ally", timestamp=now),
        )

        assert ("Woo", "Goblin") in store._dps_by_attacker_target
        assert ("Ally", "Goblin") in store._dps_by_attacker_target
        assert store._dps_by_attacker_target[("Woo", "Goblin")]["total_damage"] == 95
        assert store._dps_by_attacker_target[("Ally", "Goblin")]["total_damage"] == 30

    def test_get_target_stats_uses_index(self) -> None:
        store = DataStore()
        now = datetime.now()
        for _ in range(100):
            apply(store, damage_row(target="Goblin", damage_type="Physical", total_damage=10, attacker="Woo", timestamp=now))

        stats = store.get_target_stats("Goblin")

        assert stats is not None
        total_hits, total_damage, _ = stats
        assert total_hits == 100
        assert total_damage == 1000

    def test_get_dps_data_for_target_uses_index(self) -> None:
        store = DataStore()
        now = datetime.now()
        apply(
            store,
            damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo", timestamp=now),
            dps_update(attacker="Woo", total_damage=50, timestamp=now, damage_types={"Physical": 50}),
            damage_row(target="Goblin", damage_type="Fire", total_damage=30, attacker="Ally", timestamp=now + timedelta(seconds=1)),
            dps_update(attacker="Ally", total_damage=30, timestamp=now + timedelta(seconds=1), damage_types={"Fire": 30}),
        )

        dps_list = store.get_dps_data_for_target("Goblin", "per_character")

        assert len(dps_list) == 2
        assert any(d["character"] == "Woo" for d in dps_list)
        assert any(d["character"] == "Ally" for d in dps_list)


class TestCacheOptimizations:
    """Test suite for cache optimizations."""

    def test_targets_cache_populated_on_insert(self) -> None:
        store = DataStore()
        now = datetime.now()

        assert len(store._targets_cache) == 0
        apply(store, damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo", timestamp=now))
        assert "Goblin" in store._targets_cache

        apply(store, damage_row(target="Orc", damage_type="Fire", total_damage=30, attacker="Woo", timestamp=now))
        assert "Orc" in store._targets_cache
        assert len(store._targets_cache) == 2

    def test_damage_dealers_cache_populated_on_insert(self) -> None:
        store = DataStore()
        now = datetime.now()

        assert len(store._damage_dealers_cache) == 0
        apply(store, damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo", timestamp=now))
        assert "Woo" in store._damage_dealers_cache

        apply(store, damage_row(target="Orc", damage_type="Fire", total_damage=0, attacker="Ally", timestamp=now))
        assert "Ally" not in store._damage_dealers_cache

        apply(store, damage_row(target="Orc", damage_type="Cold", total_damage=20, attacker="Ally", timestamp=now))
        assert "Ally" in store._damage_dealers_cache

    def test_get_all_targets_uses_cache(self) -> None:
        store = DataStore()
        now = datetime.now()
        apply(
            store,
            damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo", timestamp=now),
            damage_row(target="Orc", damage_type="Fire", total_damage=30, attacker="Woo", timestamp=now),
            damage_row(target="Dragon", damage_type="Cold", total_damage=100, attacker="Ally", timestamp=now),
        )

        targets = store.get_all_targets()

        assert len(targets) == 3
        assert "Goblin" in targets
        assert "Orc" in targets
        assert "Dragon" in targets
        assert targets == sorted(targets)

    def test_get_hit_rate_for_damage_dealers_uses_cache(self) -> None:
        store = DataStore()
        now = datetime.now()
        apply(
            store,
            damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo", timestamp=now),
            damage_row(target="Orc", damage_type="Fire", total_damage=30, attacker="Ally", timestamp=now),
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="miss"),
            attack(attacker="Ally", target="Orc", outcome="hit"),
        )

        hit_rates = store.get_hit_rate_for_damage_dealers()

        assert "Woo" in hit_rates
        assert "Ally" in hit_rates
        assert hit_rates["Woo"] == 50.0
        assert hit_rates["Ally"] == 100.0

    def test_attack_stats_cache_populated_on_insert(self) -> None:
        store = DataStore()
        apply(
            store,
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="critical_hit"),
            attack(attacker="Woo", target="Goblin", outcome="miss"),
        )

        assert store._attack_stats_by_attacker["Woo"]["hits"] == 1
        assert store._attack_stats_by_attacker["Woo"]["crits"] == 1
        assert store._attack_stats_by_attacker["Woo"]["misses"] == 1

    def test_attack_stats_by_attacker_target_cache_populated_on_insert(self) -> None:
        store = DataStore()
        apply(
            store,
            attack(attacker="Woo", target="Goblin", outcome="hit"),
            attack(attacker="Woo", target="Goblin", outcome="critical_hit"),
            attack(attacker="Woo", target="Goblin", outcome="miss"),
        )

        key = ("Woo", "Goblin")
        assert store._attack_stats_by_attacker_target[key]["hits"] == 1
        assert store._attack_stats_by_attacker_target[key]["crits"] == 1
        assert store._attack_stats_by_attacker_target[key]["misses"] == 1

    def test_target_filtered_dps_summary_cache_populated_on_insert(self) -> None:
        store = DataStore()
        now = datetime.now()
        apply(
            store,
            damage_row(target="Goblin", damage_type="Physical", total_damage=50, attacker="Woo", timestamp=now),
            damage_row(target="Goblin", damage_type="Fire", total_damage=20, attacker="Woo", timestamp=now + timedelta(seconds=2)),
        )

        summary = store._dps_by_attacker_target[("Woo", "Goblin")]
        assert summary["total_damage"] == 70
        assert summary["first_timestamp"] == now
        assert summary["last_timestamp"] == now + timedelta(seconds=2)
        assert summary["damage_by_type"] == {"Physical": 50, "Fire": 20}

    def test_damage_dealers_by_target_cache_populated_on_insert(self) -> None:
        store = DataStore()
        now = datetime.now()
        apply(store, damage_row(target="Goblin", damage_type="Physical", total_damage=0, attacker="Woo", timestamp=now))
        assert "Goblin" not in store._damage_dealers_by_target

        apply(store, damage_row(target="Goblin", damage_type="Physical", total_damage=25, attacker="Woo", timestamp=now))
        assert store._damage_dealers_by_target["Goblin"] == {"Woo"}


class TestIndexPerformance:
    """Test suite for performance characteristics of indices."""

    def test_index_lookup_faster_than_iteration(self) -> None:
        store = DataStore()
        for i in range(1000):
            target = f"Target_{i % 10}"
            attacker_name = f"Attacker_{i % 5}"
            apply(store, attack(attacker=attacker_name, target=target, outcome="hit" if i % 2 == 0 else "miss"))

        stats = store.get_attack_stats("Attacker_0", "Target_0")

        assert stats is not None
        assert stats["total_attacks"] == 100

    def test_indices_scale_with_data(self) -> None:
        store = DataStore()
        now = datetime.now()

        num_targets = 50
        num_attackers = 10

        for i in range(1000):
            target = f"Target_{i % num_targets}"
            attacker_name = f"Attacker_{i % num_attackers}"
            apply(
                store,
                attack(attacker=attacker_name, target=target, outcome="hit"),
                damage_row(target=target, damage_type="Physical", total_damage=10, attacker=attacker_name, timestamp=now),
            )

        assert len(store._attack_stats_by_target) == num_targets
        assert len(store._attack_stats_by_attacker) == num_attackers
        assert len(store._targets_cache) == num_targets
        assert len(store._damage_dealers_cache) == num_attackers

        targets = store.get_all_targets()
        assert len(targets) == num_targets

    def test_raw_histories_trim_while_lifetime_aggregates_remain(self) -> None:
        store = DataStore(max_events_history=2, max_attacks_history=2)
        now = datetime.now()

        for i in range(5):
            apply(
                store,
                attack(attacker="Woo", target="Goblin", outcome="hit"),
                damage_row(target="Goblin", damage_type="Physical", total_damage=10, attacker="Woo", timestamp=now + timedelta(seconds=i)),
            )

        assert len(store.attacks) == 2
        assert len(store.events) == 2

        atk = store.get_attack_stats("Woo", "Goblin")
        assert atk is not None
        assert atk["total_attacks"] == 5
        assert atk["hits"] == 5

        target_stats = store.get_target_stats("Goblin")
        assert target_stats == (5, 50, 0)

    def test_raw_histories_evict_oldest_and_preserve_read_semantics(self) -> None:
        store = DataStore(max_events_history=2, max_attacks_history=2)
        now = datetime.now()
        apply(
            store,
            damage_row(target="T1", damage_type="Physical", total_damage=10, attacker="Woo", timestamp=now),
            damage_row(target="T2", damage_type="Physical", total_damage=10, attacker="Woo", timestamp=now + timedelta(seconds=1)),
            damage_row(target="T3", damage_type="Physical", total_damage=10, attacker="Woo", timestamp=now + timedelta(seconds=2)),
            attack(attacker="Woo", target="A1", outcome="hit"),
            attack(attacker="Woo", target="A2", outcome="miss"),
            attack(attacker="Woo", target="A3", outcome="critical_hit"),
        )

        assert len(store.events) == 2
        assert len(store.attacks) == 2
        assert store.events[0].target == "T2"
        assert [event.target for event in store.events] == ["T2", "T3"]
        assert store.attacks[0].target == "A2"
        assert [attack_event.target for attack_event in store.attacks] == ["A2", "A3"]
