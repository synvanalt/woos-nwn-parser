"""Unit tests for batched queue processing optimizations.

Tests the new batched event processing that reduces UI callback overhead.
"""

import pytest
import queue
from datetime import datetime
from unittest.mock import Mock, call

from app.services.queue_processor import QueueProcessor
from app.storage import DataStore
from app.parser import LogParser


class TestBatchedEventProcessing:
    """Test suite for batched event processing."""

    def test_process_queue_batches_dps_updates(self) -> None:
        """Test that DPS updates are batched (1 callback for N events)."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        # Add multiple damage events with attacker set
        for i in range(10):
            data_queue.put({
                'type': 'damage_dealt',
                'attacker': 'Woo',  # Must have attacker for DPS tracking
                'target': 'Goblin',
                'total_damage': 50,  # Must have damage > 0
                'timestamp': now,
                'damage_types': {'Physical': 50}
            })

        on_dps_updated = Mock()
        on_log_message = Mock()

        # Process queue
        processor.process_queue(
            data_queue,
            on_log_message,
            on_dps_updated,
            Mock(),
            Mock(),
            Mock()
        )

        # Should only call on_dps_updated ONCE, not 10 times
        assert on_dps_updated.call_count == 1

    def test_process_queue_deduplicates_target_updates(self) -> None:
        """Test that target updates are deduplicated."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        # Add multiple attacks to same target
        for i in range(10):
            data_queue.put({
                'type': 'attack_hit',
                'attacker': 'Woo',
                'target': 'Goblin',
                'roll': 15,
                'bonus': 10,
                'total': 25
            })

        on_target_selected = Mock()
        on_log_message = Mock()

        # Process queue
        processor.process_queue(
            data_queue,
            on_log_message,
            Mock(),
            on_target_selected,
            Mock()
        )

        # Should only call on_target_selected ONCE for "Goblin", not 10 times
        assert on_target_selected.call_count == 1
        on_target_selected.assert_called_with('Goblin')

    def test_process_queue_handles_multiple_targets(self) -> None:
        """Test that batching handles multiple different targets correctly."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        # Add attacks to 3 different targets
        for target in ['Goblin', 'Orc', 'Dragon']:
            for i in range(5):
                data_queue.put({
                    'type': 'attack_hit',
                    'attacker': 'Woo',
                    'target': target,
                    'roll': 15,
                    'bonus': 10,
                    'total': 25
                })

        on_target_selected = Mock()
        on_log_message = Mock()

        # Process queue
        processor.process_queue(
            data_queue,
            on_log_message,
            Mock(),
            on_target_selected,
            Mock()
        )

        # Should call on_target_selected exactly 3 times (once per unique target)
        assert on_target_selected.call_count == 3
        # Check all targets were called
        called_targets = {call_args[0][0] for call_args in on_target_selected.call_args_list}
        assert called_targets == {'Goblin', 'Orc', 'Dragon'}

    def test_process_queue_batches_immunity_updates(self) -> None:
        """Test that immunity updates are batched."""
        store = DataStore()
        parser = LogParser(parse_immunity=True)
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        # Queue immunity event
        data_queue.put({
            'type': 'immunity',
            'target': 'Goblin',
            'damage_type': 'Fire',
            'immunity_points': 10,
            'timestamp': now
        })

        # Queue matching damage event
        data_queue.put({
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': now,
            'damage_types': {'Fire': 50}
        })

        on_immunity_changed = Mock()
        on_log_message = Mock()

        # Process queue
        processor.process_queue(
            data_queue,
            on_log_message,
            Mock(),
            Mock(),
            on_immunity_changed
        )

        # Should call on_immunity_changed once
        assert on_immunity_changed.call_count == 1
        on_immunity_changed.assert_called_with('Goblin')

    def test_process_queue_batches_damage_dealt_callbacks(self) -> None:
        """Test that damage_dealt callbacks are batched and deduplicated."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        # Add multiple damage events to same target
        for i in range(5):
            data_queue.put({
                'type': 'damage_dealt',
                'attacker': 'Woo',
                'target': 'Goblin',
                'total_damage': 50,
                'timestamp': now,
                'damage_types': {'Physical': 50}
            })

        on_damage_dealt = Mock()
        on_log_message = Mock()

        # Process queue
        processor.process_queue(
            data_queue,
            on_log_message,
            Mock(),
            Mock(),
            Mock(),
            on_damage_dealt
        )

        # Should only call on_damage_dealt ONCE for "Goblin"
        assert on_damage_dealt.call_count == 1
        on_damage_dealt.assert_called_with('Goblin')

    def test_batched_processing_maintains_data_integrity(self) -> None:
        """Test that batched processing doesn't lose or corrupt data."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        # Add mixed events
        data_queue.put({
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': now,
            'damage_types': {'Physical': 50}
        })

        data_queue.put({
            'type': 'attack_hit',
            'attacker': 'Woo',
            'target': 'Orc',
            'roll': 15,
            'bonus': 10,
            'total': 25
        })

        # Process queue
        processor.process_queue(
            data_queue,
            Mock(),
            Mock(),
            Mock(),
            Mock()
        )

        # Verify data was stored correctly
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

        # Process empty queue - should not raise
        processor.process_queue(
            data_queue,
            Mock(),
            Mock(),
            Mock(),
            Mock()
        )

        # No errors, no data stored
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

        # Add many events with valid attacker and damage
        for i in range(num_events):
            data_queue.put({
                'type': 'damage_dealt',
                'attacker': 'Woo',  # Must have attacker
                'target': 'Goblin',
                'total_damage': 50,  # Must have damage > 0
                'timestamp': now,
                'damage_types': {'Physical': 50}
            })

        on_dps_updated = Mock()
        on_target_selected = Mock()
        on_damage_dealt = Mock()

        # Process queue
        processor.process_queue(
            data_queue,
            Mock(),
            on_dps_updated,
            on_target_selected,
            Mock(),
            on_damage_dealt
        )

        # With batching: O(1) callbacks instead of O(n)
        assert on_dps_updated.call_count == 1  # Not 100 - one DPS update
        # Note: damage events don't trigger on_target_selected (they use damage_target instead)
        # so we don't check on_target_selected here
        assert on_damage_dealt.call_count == 1  # Not 100 - deduplicated to 1 target

    def test_batching_with_heavy_combat_scenario(self) -> None:
        """Test batching performance with realistic heavy combat."""
        store = DataStore()
        parser = LogParser()
        processor = QueueProcessor(store, parser)

        data_queue = queue.Queue()
        now = datetime.now()

        # Simulate heavy combat: 200 events with 5 targets
        targets = ['Goblin', 'Orc', 'Dragon', 'Troll', 'Demon']

        for i in range(200):
            target = targets[i % len(targets)]

            # Mix of attacks and damage
            if i % 2 == 0:
                data_queue.put({
                    'type': 'attack_hit',
                    'attacker': 'Woo',
                    'target': target,
                    'roll': 15,
                    'bonus': 10,
                    'total': 25
                })
            else:
                data_queue.put({
                    'type': 'damage_dealt',
                    'attacker': 'Woo',
                    'target': target,
                    'total_damage': 50,
                    'timestamp': now,
                    'damage_types': {'Physical': 50}
                })

        on_dps_updated = Mock()
        on_target_selected = Mock()
        on_damage_dealt = Mock()

        # Process queue
        processor.process_queue(
            data_queue,
            Mock(),
            on_dps_updated,
            on_target_selected,
            Mock(),
            on_damage_dealt
        )

        # Batching should result in:
        # - 1 DPS update (not 100)
        # - 5 target updates (one per unique target, not 200)
        # - 5 damage dealt (one per unique target, not 100)
        assert on_dps_updated.call_count == 1
        assert on_target_selected.call_count == 5
        assert on_damage_dealt.call_count == 5

        # Verify all data was stored correctly
        assert len(store.attacks) == 100
        assert len(store.events) == 100

