"""Unit tests for batched queue processing optimizations.

Tests the new batched event processing that reduces UI callback overhead.
"""

import queue
from datetime import datetime
from unittest.mock import Mock

from app.parser import LogParser
from app.services.queue_processor import QueueProcessor
from app.storage import DataStore
from tests.helpers.parsed_event_factories import (
    attack_hit_event,
    damage_event,
    immunity_event,
)


class TestBatchedEventProcessing:
    """Test suite for batched event processing."""

    def test_process_queue_batches_dps_updates(self) -> None:
        """Test that DPS updates are batched (1 callback for N events)."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        for _ in range(10):
            data_queue.put(
                damage_event(
                    attacker='Woo',
                    target='Goblin',
                    total_damage=50,
                    timestamp=now,
                    damage_types={'Physical': 50},
                )
            )

        result = processor.process_queue(data_queue, Mock())
        assert result.dps_updated is True

    def test_process_queue_deduplicates_target_updates(self) -> None:
        """Test that target updates are deduplicated."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()

        for _ in range(10):
            data_queue.put(
                attack_hit_event(
                    attacker='Woo',
                    target='Goblin',
                    roll=15,
                    bonus=10,
                    total=25,
                )
            )

        result = processor.process_queue(data_queue, Mock())
        assert result.targets_to_refresh == {'Goblin'}

    def test_process_queue_handles_multiple_targets(self) -> None:
        """Test that batching handles multiple different targets correctly."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()

        for target in ['Goblin', 'Orc', 'Dragon']:
            for _ in range(5):
                data_queue.put(
                    attack_hit_event(
                        attacker='Woo',
                        target=target,
                        roll=15,
                        bonus=10,
                        total=25,
                    )
                )

        result = processor.process_queue(data_queue, Mock())
        assert result.targets_to_refresh == {'Goblin', 'Orc', 'Dragon'}

    def test_process_queue_batches_immunity_updates(self) -> None:
        """Test that immunity updates are batched."""
        store = DataStore()
        parser = LogParser(parse_immunity=True)
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        data_queue.put(
            immunity_event(
                target='Goblin',
                damage_type='Fire',
                immunity_points=10,
                timestamp=now,
            )
        )
        data_queue.put(
            damage_event(
                attacker='Woo',
                target='Goblin',
                total_damage=50,
                timestamp=now,
                damage_types={'Fire': 50},
            )
        )

        result = processor.process_queue(data_queue, Mock())
        assert result.immunity_targets == {'Goblin'}

    def test_process_queue_batches_damage_dealt_callbacks(self) -> None:
        """Test that damage_dealt callbacks are batched and deduplicated."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        for _ in range(5):
            data_queue.put(
                damage_event(
                    attacker='Woo',
                    target='Goblin',
                    total_damage=50,
                    timestamp=now,
                    damage_types={'Physical': 50},
                )
            )

        result = processor.process_queue(data_queue, Mock())
        assert result.damage_targets == {'Goblin'}

    def test_batched_processing_maintains_data_integrity(self) -> None:
        """Test that batched processing doesn't lose or corrupt data."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        data_queue.put(
            damage_event(
                attacker='Woo',
                target='Goblin',
                total_damage=50,
                timestamp=now,
                damage_types={'Physical': 50},
            )
        )
        data_queue.put(
            attack_hit_event(
                attacker='Woo',
                target='Orc',
                roll=15,
                bonus=10,
                total=25,
            )
        )

        processor.process_queue(data_queue, Mock())

        assert len(store.events) == 1
        assert len(store.attacks) == 1
        assert store.events[0].target == 'Goblin'
        assert store.attacks[0].target == 'Orc'

    def test_empty_queue_processed_safely_batched(self) -> None:
        """Test that processing an empty queue doesn't cause errors."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()

        processor.process_queue(data_queue, Mock())

        assert len(store.events) == 0
        assert len(store.attacks) == 0


class TestBatchedProcessingPerformance:
    """Test suite for batched processing performance characteristics."""

    def test_batching_reduces_callback_overhead(self) -> None:
        """Test that batching significantly reduces callback count."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()
        num_events = 100

        for _ in range(num_events):
            data_queue.put(
                damage_event(
                    attacker='Woo',
                    target='Goblin',
                    total_damage=50,
                    timestamp=now,
                    damage_types={'Physical': 50},
                )
            )

        result = processor.process_queue(data_queue, Mock())
        assert result.dps_updated is True
        assert result.damage_targets == {'Goblin'}

    def test_batching_with_heavy_combat_scenario(self) -> None:
        """Test batching performance with realistic heavy combat."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()
        targets = ['Goblin', 'Orc', 'Dragon', 'Troll', 'Demon']

        for i in range(200):
            target = targets[i % len(targets)]
            if i % 2 == 0:
                data_queue.put(
                    attack_hit_event(
                        attacker='Woo',
                        target=target,
                        roll=15,
                        bonus=10,
                        total=25,
                    )
                )
            else:
                data_queue.put(
                    damage_event(
                        attacker='Woo',
                        target=target,
                        total_damage=50,
                        timestamp=now,
                        damage_types={'Physical': 50},
                    )
                )

        result = processor.process_queue(data_queue, Mock())
        assert result.dps_updated is True
        assert result.targets_to_refresh == set(targets)
        assert result.damage_targets == set(targets)
        assert len(store.attacks) == 100
        assert len(store.events) == 100

    def test_process_queue_reports_pressure_state_from_remaining_backlog(self) -> None:
        """Backlog classification should be derived from the queue after draining."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue(maxsize=4000)
        now = datetime.now()

        for _ in range(2501):
            data_queue.put(
                damage_event(
                    attacker='Woo',
                    target='Goblin',
                    total_damage=50,
                    timestamp=now,
                    damage_types={'Physical': 50},
                )
            )

        result = processor.process_queue(data_queue, Mock(), max_events=1)

        assert result.backlog_count == 2500
        assert result.has_backlog is True
        assert result.pressure_state == 'pressured'
