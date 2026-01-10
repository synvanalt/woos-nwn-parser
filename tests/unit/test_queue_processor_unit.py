"""Unit tests for QueueProcessor.

Tests event processing, immunity queuing, damage buffering,
attack handling, and cleanup methods.
"""

import pytest
import queue
from datetime import datetime, timedelta
from unittest.mock import Mock, call

from app.services.queue_processor import QueueProcessor
from app.storage import DataStore
from app.parser import LogParser


class TestQueueProcessorInitialization:
    """Test suite for QueueProcessor initialization."""

    def test_initialization(self, data_store: DataStore, parser: LogParser) -> None:
        """Test QueueProcessor initializes correctly."""
        processor = QueueProcessor(data_store, parser)

        assert processor.data_store == data_store
        assert processor.parser == parser
        assert len(processor.damage_buffer) == 0
        assert len(processor.pending_immunity_queue) == 0
        assert len(processor.immunity_pct_cache) == 0
        assert processor.parsed_event_count == 0


class TestEventRouting:
    """Test suite for event routing to appropriate handlers."""

    def test_route_damage_dealt_event(self, queue_processor: QueueProcessor) -> None:
        """Test routing damage_dealt event to correct handler."""
        data_queue = queue.Queue()

        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Physical': 50}
        }

        data_queue.put(damage_event)

        on_log_message = Mock()
        on_dps_updated = Mock()
        on_target_selected = Mock()
        on_immunity_changed = Mock()

        queue_processor.process_queue(
            data_queue,
            on_log_message,
            on_dps_updated,
            on_target_selected,
            on_immunity_changed
        )

        # Verify DPS was updated
        on_dps_updated.assert_called()

        # Verify damage was buffered
        assert 'Goblin' in queue_processor.damage_buffer
        assert queue_processor.damage_buffer['Goblin']['damage_types'] == {'Physical': 50}

    def test_route_immunity_event(self, queue_processor: QueueProcessor) -> None:
        """Test routing immunity event to correct handler."""
        queue_processor.parser.parse_immunity = True
        data_queue = queue.Queue()

        immunity_event = {
            'type': 'immunity',
            'target': 'Goblin',
            'damage_type': 'Fire',
            'immunity_points': 10,
            'timestamp': datetime.now()
        }

        data_queue.put(immunity_event)

        on_log_message = Mock()
        on_dps_updated = Mock()
        on_target_selected = Mock()
        on_immunity_changed = Mock()

        queue_processor.process_queue(
            data_queue,
            on_log_message,
            on_dps_updated,
            on_target_selected,
            on_immunity_changed
        )

        # Immunity should be queued if no matching damage
        assert 'Goblin' in queue_processor.pending_immunity_queue

    def test_route_attack_hit_event(self, queue_processor: QueueProcessor) -> None:
        """Test routing attack_hit event to correct handler."""
        data_queue = queue.Queue()

        attack_event = {
            'type': 'attack_hit',
            'attacker': 'Woo',
            'target': 'Goblin',
            'roll': 15,
            'bonus': '5',
            'total': 20,
            'timestamp': datetime.now()
        }

        data_queue.put(attack_event)

        on_log_message = Mock()
        on_dps_updated = Mock()
        on_target_selected = Mock()
        on_immunity_changed = Mock()

        queue_processor.process_queue(
            data_queue,
            on_log_message,
            on_dps_updated,
            on_target_selected,
            on_immunity_changed
        )

        # Verify attack was stored
        assert len(queue_processor.data_store.attacks) == 1
        attack = queue_processor.data_store.attacks[0]
        assert attack.outcome == 'hit'

    def test_route_attack_miss_event(self, queue_processor: QueueProcessor) -> None:
        """Test routing attack_miss event to correct handler."""
        data_queue = queue.Queue()

        attack_event = {
            'type': 'attack_miss',
            'attacker': 'Woo',
            'target': 'Goblin',
            'roll': 8,
            'bonus': '5',
            'total': 13,
            'timestamp': datetime.now()
        }

        data_queue.put(attack_event)

        on_log_message = Mock()
        on_dps_updated = Mock()
        on_target_selected = Mock()
        on_immunity_changed = Mock()

        queue_processor.process_queue(
            data_queue,
            on_log_message,
            on_dps_updated,
            on_target_selected,
            on_immunity_changed
        )

        # Verify attack was stored
        assert len(queue_processor.data_store.attacks) == 1
        attack = queue_processor.data_store.attacks[0]
        assert attack.outcome == 'miss'

    def test_route_critical_hit_event(self, queue_processor: QueueProcessor) -> None:
        """Test routing critical_hit event to correct handler."""
        data_queue = queue.Queue()

        attack_event = {
            'type': 'attack_hit_critical',
            'attacker': 'Woo',
            'target': 'Goblin',
            'roll': 20,
            'bonus': '5',
            'total': 25,
            'timestamp': datetime.now()
        }

        data_queue.put(attack_event)

        on_log_message = Mock()
        on_dps_updated = Mock()
        on_target_selected = Mock()
        on_immunity_changed = Mock()

        queue_processor.process_queue(
            data_queue,
            on_log_message,
            on_dps_updated,
            on_target_selected,
            on_immunity_changed
        )

        # Verify attack was stored as critical_hit
        assert len(queue_processor.data_store.attacks) == 1
        attack = queue_processor.data_store.attacks[0]
        assert attack.outcome == 'critical_hit'

    def test_route_debug_message(self, queue_processor: QueueProcessor) -> None:
        """Test routing debug message."""
        data_queue = queue.Queue()

        debug_event = {
            'type': 'debug',
            'message': 'Test debug message'
        }

        data_queue.put(debug_event)

        on_log_message = Mock()
        on_dps_updated = Mock()
        on_target_selected = Mock()
        on_immunity_changed = Mock()

        queue_processor.process_queue(
            data_queue,
            on_log_message,
            on_dps_updated,
            on_target_selected,
            on_immunity_changed
        )

        # Verify message was logged
        on_log_message.assert_called_with('Test debug message', 'debug')


class TestDamageBuffering:
    """Test suite for damage event buffering."""

    def test_damage_buffer_stores_damage_types(self, queue_processor: QueueProcessor) -> None:
        """Test that damage buffer stores damage type information."""
        data_queue = queue.Queue()

        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Dragon',
            'total_damage': 100,
            'timestamp': datetime.now(),
            'damage_types': {'Fire': 60, 'Physical': 40}
        }

        data_queue.put(damage_event)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Verify buffer contains damage types
        assert 'Dragon' in queue_processor.damage_buffer
        buffer_data = queue_processor.damage_buffer['Dragon']
        assert buffer_data['damage_types'] == {'Fire': 60, 'Physical': 40}
        assert 'attacker' in buffer_data
        assert 'timestamp' in buffer_data

    def test_damage_buffer_overwrites_previous_target(self, queue_processor: QueueProcessor) -> None:
        """Test that new damage overwrites previous buffer for same target."""
        data_queue = queue.Queue()

        damage_event1 = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Physical': 50}
        }

        damage_event2 = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 100,
            'timestamp': datetime.now(),
            'damage_types': {'Fire': 100}
        }

        data_queue.put(damage_event1)
        data_queue.put(damage_event2)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Buffer should have most recent damage
        assert queue_processor.damage_buffer['Goblin']['damage_types'] == {'Fire': 100}

    def test_damage_buffer_stores_multiple_targets(self, queue_processor: QueueProcessor) -> None:
        """Test that damage buffer can store multiple targets simultaneously."""
        data_queue = queue.Queue()

        damage_event1 = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Physical': 50}
        }

        damage_event2 = {
            'type': 'damage_dealt',
            'attacker': 'Rogue',
            'target': 'Orc',
            'total_damage': 40,
            'timestamp': datetime.now(),
            'damage_types': {'Cold': 40}
        }

        data_queue.put(damage_event1)
        data_queue.put(damage_event2)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Both targets should be in buffer
        assert 'Goblin' in queue_processor.damage_buffer
        assert 'Orc' in queue_processor.damage_buffer


class TestImmunityQueuing:
    """Test suite for immunity event queuing and matching."""

    def test_immunity_queued_without_matching_damage(self, queue_processor: QueueProcessor) -> None:
        """Test immunity is queued when no matching damage exists."""
        queue_processor.parser.parse_immunity = True
        data_queue = queue.Queue()

        immunity_event = {
            'type': 'immunity',
            'target': 'Goblin',
            'damage_type': 'Fire',
            'immunity_points': 10,
            'timestamp': datetime.now()
        }

        data_queue.put(immunity_event)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Immunity should be queued
        assert 'Goblin' in queue_processor.pending_immunity_queue
        assert 'Fire' in queue_processor.pending_immunity_queue['Goblin']
        queued = queue_processor.pending_immunity_queue['Goblin']['Fire']
        assert len(queued) == 1
        assert queued[0]['immunity'] == 10

    def test_immunity_matched_with_recent_damage(self, queue_processor: QueueProcessor) -> None:
        """Test immunity is matched with recent damage."""
        queue_processor.parser.parse_immunity = True
        data_queue = queue.Queue()

        now = datetime.now()

        # First, damage event
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': now,
            'damage_types': {'Fire': 50}
        }

        # Then, immunity event
        immunity_event = {
            'type': 'immunity',
            'target': 'Goblin',
            'damage_type': 'Fire',
            'immunity_points': 10,
            'timestamp': now
        }

        data_queue.put(damage_event)
        data_queue.put(immunity_event)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Immunity should be recorded in data store
        immunity_info = queue_processor.data_store.get_immunity_for_target_and_type('Goblin', 'Fire')
        assert immunity_info['max_immunity'] == 10
        assert immunity_info['max_damage'] == 50

    def test_immunity_not_matched_with_wrong_damage_type(self, queue_processor: QueueProcessor) -> None:
        """Test immunity is queued when damage type doesn't match."""
        queue_processor.parser.parse_immunity = True
        data_queue = queue.Queue()

        now = datetime.now()

        # Damage with Physical
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': now,
            'damage_types': {'Physical': 50}
        }

        # Immunity for Fire (not in damage)
        immunity_event = {
            'type': 'immunity',
            'target': 'Goblin',
            'damage_type': 'Fire',
            'immunity_points': 10,
            'timestamp': now
        }

        data_queue.put(damage_event)
        data_queue.put(immunity_event)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Immunity should be queued, not matched
        assert 'Goblin' in queue_processor.pending_immunity_queue
        assert 'Fire' in queue_processor.pending_immunity_queue['Goblin']

    def test_queued_immunity_matched_with_later_damage(self, queue_processor: QueueProcessor) -> None:
        """Test queued immunity is matched when appropriate damage arrives."""
        queue_processor.parser.parse_immunity = True
        data_queue = queue.Queue()

        now = datetime.now()

        # First, immunity (no damage yet)
        immunity_event = {
            'type': 'immunity',
            'target': 'Goblin',
            'damage_type': 'Fire',
            'immunity_points': 10,
            'timestamp': now
        }

        # Then, matching damage
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': now,
            'damage_types': {'Fire': 50}
        }

        data_queue.put(immunity_event)
        data_queue.put(damage_event)

        on_immunity_changed = Mock()

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), on_immunity_changed
        )

        # Immunity should be processed
        immunity_info = queue_processor.data_store.get_immunity_for_target_and_type('Goblin', 'Fire')
        assert immunity_info['max_immunity'] == 10

        # Queue should be cleared
        if 'Goblin' in queue_processor.pending_immunity_queue:
            assert 'Fire' not in queue_processor.pending_immunity_queue['Goblin']

    def test_multiple_immunities_queued(self, queue_processor: QueueProcessor) -> None:
        """Test multiple immunity events can be queued."""
        queue_processor.parser.parse_immunity = True
        data_queue = queue.Queue()

        now = datetime.now()

        immunity1 = {
            'type': 'immunity',
            'target': 'Dragon',
            'damage_type': 'Fire',
            'immunity_points': 20,
            'timestamp': now
        }

        immunity2 = {
            'type': 'immunity',
            'target': 'Dragon',
            'damage_type': 'Cold',
            'immunity_points': 15,
            'timestamp': now
        }

        data_queue.put(immunity1)
        data_queue.put(immunity2)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Both immunities should be queued
        assert 'Dragon' in queue_processor.pending_immunity_queue
        assert 'Fire' in queue_processor.pending_immunity_queue['Dragon']
        assert 'Cold' in queue_processor.pending_immunity_queue['Dragon']


class TestCleanupMethods:
    """Test suite for cleanup methods."""

    def test_cleanup_stale_immunities(self, queue_processor: QueueProcessor) -> None:
        """Test that old immunity entries are cleaned up."""
        # Add old immunity entries
        old_time = datetime.now() - timedelta(seconds=10)
        queue_processor.pending_immunity_queue['Goblin'] = {
            'Fire': [{'immunity': 10, 'timestamp': old_time}]
        }

        # Add recent immunity entries
        recent_time = datetime.now()
        queue_processor.pending_immunity_queue['Orc'] = {
            'Cold': [{'immunity': 5, 'timestamp': recent_time}]
        }

        # Cleanup with 5 second threshold
        queue_processor.cleanup_stale_immunities(max_age_seconds=5.0)

        # Old entry should be removed
        assert 'Goblin' not in queue_processor.pending_immunity_queue or \
               'Fire' not in queue_processor.pending_immunity_queue.get('Goblin', {})

        # Recent entry should remain
        assert 'Orc' in queue_processor.pending_immunity_queue
        assert 'Cold' in queue_processor.pending_immunity_queue['Orc']

    def test_cleanup_empty_targets_removed(self, queue_processor: QueueProcessor) -> None:
        """Test that targets with no damage types are removed."""
        old_time = datetime.now() - timedelta(seconds=10)
        queue_processor.pending_immunity_queue['Goblin'] = {
            'Fire': [{'immunity': 10, 'timestamp': old_time}]
        }

        queue_processor.cleanup_stale_immunities(max_age_seconds=5.0)

        # Target should be completely removed
        assert 'Goblin' not in queue_processor.pending_immunity_queue

    def test_cleanup_called_periodically(self, queue_processor: QueueProcessor) -> None:
        """Test that cleanup mechanism works correctly."""
        # Test that cleanup removes old entries
        data_queue = queue.Queue()

        # Add old immunity to test cleanup
        old_time = datetime.now() - timedelta(seconds=10)
        queue_processor.pending_immunity_queue['OldTarget'] = {
            'Fire': [{'immunity': 10, 'timestamp': old_time}]
        }

        # Directly call cleanup (this is what process_queue calls periodically)
        queue_processor.cleanup_stale_immunities(max_age_seconds=5.0)

        # Old immunity should be removed
        assert 'OldTarget' not in queue_processor.pending_immunity_queue

        # Verify counter increments on process_queue calls
        initial_count = queue_processor.parsed_event_count
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Target1',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Physical': 50}
        }
        data_queue.put(damage_event)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Counter should increment
        assert queue_processor.parsed_event_count == initial_count + 1

    def test_cleanup_with_mixed_timestamps(self, queue_processor: QueueProcessor) -> None:
        """Test cleanup with mix of old and recent entries for same target."""
        old_time = datetime.now() - timedelta(seconds=10)
        recent_time = datetime.now()

        queue_processor.pending_immunity_queue['Dragon'] = {
            'Fire': [
                {'immunity': 10, 'timestamp': old_time},
                {'immunity': 20, 'timestamp': recent_time}
            ]
        }

        queue_processor.cleanup_stale_immunities(max_age_seconds=5.0)

        # Old entry removed, recent kept
        assert 'Dragon' in queue_processor.pending_immunity_queue
        assert 'Fire' in queue_processor.pending_immunity_queue['Dragon']
        assert len(queue_processor.pending_immunity_queue['Dragon']['Fire']) == 1
        assert queue_processor.pending_immunity_queue['Dragon']['Fire'][0]['immunity'] == 20


class TestDPSTracking:
    """Test suite for DPS data updates."""

    def test_dps_updated_on_damage(self, queue_processor: QueueProcessor) -> None:
        """Test that DPS is updated when damage is dealt."""
        data_queue = queue.Queue()

        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 100,
            'timestamp': datetime.now(),
            'damage_types': {'Fire': 60, 'Physical': 40}
        }

        data_queue.put(damage_event)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Verify DPS data was updated
        assert 'Woo' in queue_processor.data_store.dps_data
        assert queue_processor.data_store.dps_data['Woo']['total_damage'] == 100

    def test_damage_events_inserted(self, queue_processor: QueueProcessor) -> None:
        """Test that damage events are inserted into data store."""
        data_queue = queue.Queue()

        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Physical': 30, 'Fire': 20}
        }

        data_queue.put(damage_event)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Verify damage events were inserted
        assert len(queue_processor.data_store.events) == 2  # Physical and Fire


class TestCallbacks:
    """Test suite for callback invocations."""

    def test_on_dps_updated_called(self, queue_processor: QueueProcessor) -> None:
        """Test that on_dps_updated callback is called."""
        data_queue = queue.Queue()

        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Physical': 50}
        }

        data_queue.put(damage_event)

        on_dps_updated = Mock()

        queue_processor.process_queue(
            data_queue,
            Mock(), on_dps_updated, Mock(), Mock()
        )

        # Callback should be called
        on_dps_updated.assert_called_once()

    def test_on_immunity_changed_called(self, queue_processor: QueueProcessor) -> None:
        """Test that on_immunity_changed callback is called when queued immunity is processed."""
        queue_processor.parser.parse_immunity = True
        data_queue = queue.Queue()

        now = datetime.now()

        # First, queue an immunity without matching damage
        immunity_event = {
            'type': 'immunity',
            'target': 'Goblin',
            'damage_type': 'Fire',
            'immunity_points': 10,
            'timestamp': now
        }

        data_queue.put(immunity_event)

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

        # Now send matching damage which should process the queued immunity
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': now,
            'damage_types': {'Fire': 50}
        }

        data_queue.put(damage_event)

        on_immunity_changed = Mock()

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), on_immunity_changed
        )

        # Callback should be called with target when queued immunity is processed
        on_immunity_changed.assert_called_with('Goblin')

    def test_on_damage_dealt_called(self, queue_processor: QueueProcessor) -> None:
        """Test that on_damage_dealt callback is called when provided."""
        data_queue = queue.Queue()

        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Woo',
            'target': 'Goblin',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Physical': 50}
        }

        data_queue.put(damage_event)

        on_damage_dealt = Mock()

        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock(),
            on_damage_dealt=on_damage_dealt
        )

        # Callback should be called with target
        on_damage_dealt.assert_called_with('Goblin')


class TestErrorHandling:
    """Test suite for error handling."""

    def test_immunity_skipped_when_disabled(self, queue_processor: QueueProcessor) -> None:
        """Test that immunity events are skipped when parsing is disabled."""
        queue_processor.parser.parse_immunity = False
        data_queue = queue.Queue()

        immunity_event = {
            'type': 'immunity',
            'target': 'Goblin',
            'damage_type': 'Fire',
            'immunity_points': 10,
            'timestamp': datetime.now()
        }

        data_queue.put(immunity_event)

        on_log_message = Mock()

        queue_processor.process_queue(
            data_queue,
            on_log_message, Mock(), Mock(), Mock()
        )

        # Should log that immunity is skipped
        assert on_log_message.called
        call_args = str(on_log_message.call_args_list)
        assert 'parsing disabled' in call_args.lower() or 'Skipping' in call_args

    def test_empty_queue_processed_safely(self, queue_processor: QueueProcessor) -> None:
        """Test that processing empty queue doesn't cause errors."""
        data_queue = queue.Queue()

        # Should not raise exception
        queue_processor.process_queue(
            data_queue,
            Mock(), Mock(), Mock(), Mock()
        )

    def test_invalid_event_type_handled(self, queue_processor: QueueProcessor) -> None:
        """Test that invalid event types are handled gracefully."""
        data_queue = queue.Queue()

        invalid_event = {
            'type': 'invalid_type',
            'message': 'Unknown event'
        }

        data_queue.put(invalid_event)

        on_log_message = Mock()

        # Should not raise exception
        queue_processor.process_queue(
            data_queue,
            on_log_message, Mock(), Mock(), Mock()
        )

        # Message should be logged
        on_log_message.assert_called_with('Unknown event', 'invalid_type')
