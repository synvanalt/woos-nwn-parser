"""Unit tests for QueueProcessor service.

Tests event processing, queue handling, and immunity tracking logic.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from queue import Queue

from app.services.queue_processor import QueueProcessor
from app.storage import DataStore
from app.parser import LogParser


class TestQueueProcessor(unittest.TestCase):
    """Test suite for QueueProcessor service."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = Mock(spec=DataStore)
        self.parser = Mock(spec=LogParser)
        self.parser.parse_immunity = False

        self.processor = QueueProcessor(self.data_store, self.parser)
        self.queue = Queue()

    def test_initialization(self) -> None:
        """Test QueueProcessor initializes correctly."""
        self.assertIsNotNone(self.processor)
        self.assertEqual(self.processor.data_store, self.data_store)
        self.assertEqual(self.processor.parser, self.parser)
        self.assertEqual(len(self.processor.damage_buffer), 0)
        self.assertEqual(len(self.processor.pending_immunity_queue), 0)

    def test_process_empty_queue(self) -> None:
        """Test processing an empty queue does nothing."""
        callbacks = {
            'on_log_message': Mock(),
            'on_dps_updated': Mock(),
            'on_target_selected': Mock(),
            'on_immunity_changed': Mock(),
        }

        self.processor.process_queue(
            self.queue,
            **callbacks
        )

        # No callbacks should be called for empty queue
        callbacks['on_log_message'].assert_not_called()

    def test_damage_dealt_event_processing(self) -> None:
        """Test processing damage_dealt event."""
        callbacks = {
            'on_log_message': Mock(),
            'on_dps_updated': Mock(),
            'on_target_selected': Mock(),
            'on_immunity_changed': Mock(),
        }

        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Piercing': 50},
        }

        self.queue.put(damage_event)

        self.processor.process_queue(
            self.queue,
            **callbacks
        )

        # Verify DPS update callback was called
        callbacks['on_dps_updated'].assert_called()

        # Verify data store was updated
        self.data_store.update_dps_data.assert_called()
        self.data_store.insert_damage_event.assert_called()

    def test_immunity_event_without_damage(self) -> None:
        """Test queuing immunity event when no recent damage exists."""
        self.parser.parse_immunity = True

        callbacks = {
            'on_log_message': Mock(),
            'on_dps_updated': Mock(),
            'on_target_selected': Mock(),
            'on_immunity_changed': Mock(),
        }

        immunity_event = {
            'type': 'immunity',
            'target': 'TestTarget',
            'damage_type': 'Fire',
            'immunity_points': 20,
            'timestamp': datetime.now(),
        }

        self.queue.put(immunity_event)

        self.processor.process_queue(
            self.queue,
            **callbacks
        )

        # Immunity should be queued
        self.assertIn('TestTarget', self.processor.pending_immunity_queue)
        self.assertIn('Fire', self.processor.pending_immunity_queue['TestTarget'])

    def test_immunity_with_matching_damage(self) -> None:
        """Test processing immunity event with matching recent damage."""
        self.parser.parse_immunity = True

        callbacks = {
            'on_log_message': Mock(),
            'on_dps_updated': Mock(),
            'on_target_selected': Mock(),
            'on_immunity_changed': Mock(),
        }

        now = datetime.now()

        # First add damage event
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'total_damage': 50,
            'timestamp': now,
            'damage_types': {'Fire': 50},
        }

        self.queue.put(damage_event)
        self.processor.process_queue(self.queue, **callbacks)

        # Then add matching immunity event
        immunity_event = {
            'type': 'immunity',
            'target': 'TestTarget',
            'damage_type': 'Fire',
            'immunity_points': 20,
            'timestamp': now,
        }

        self.queue.put(immunity_event)
        self.processor.process_queue(self.queue, **callbacks)

        # Verify immunity was recorded
        self.data_store.record_immunity.assert_called()

    def test_attack_hit_event(self) -> None:
        """Test processing attack_hit event."""
        callbacks = {
            'on_log_message': Mock(),
            'on_dps_updated': Mock(),
            'on_target_selected': Mock(),
            'on_immunity_changed': Mock(),
        }

        attack_event = {
            'type': 'attack_hit',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'roll': 10,
            'bonus': 5,
            'total': 15,
        }

        self.queue.put(attack_event)
        self.processor.process_queue(self.queue, **callbacks)

        # Verify attack was recorded
        self.data_store.insert_attack_event.assert_called_with(
            'TestCharacter',
            'TestTarget',
            'hit',
            10,
            5,
            15
        )

    def test_cleanup_stale_immunities(self) -> None:
        """Test cleanup of stale immunity entries."""
        now = datetime.now()
        old_time = now - timedelta(seconds=10)

        # Add old immunity entry
        self.processor.pending_immunity_queue['OldTarget'] = {
            'Fire': [{'immunity': 10, 'timestamp': old_time}]
        }

        # Add recent immunity entry
        self.processor.pending_immunity_queue['NewTarget'] = {
            'Ice': [{'immunity': 15, 'timestamp': now}]
        }

        # Clean up entries older than 5 seconds
        self.processor.cleanup_stale_immunities(max_age_seconds=5.0)

        # Old target should be removed
        self.assertNotIn('OldTarget', self.processor.pending_immunity_queue)

        # New target should remain
        self.assertIn('NewTarget', self.processor.pending_immunity_queue)

    def test_critical_hit_event(self) -> None:
        """Test processing critical_hit event."""
        callbacks = {
            'on_log_message': Mock(),
            'on_dps_updated': Mock(),
            'on_target_selected': Mock(),
            'on_immunity_changed': Mock(),
        }

        crit_event = {
            'type': 'critical_hit',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'roll': 20,
            'bonus': 5,
            'total': 25,
        }

        self.queue.put(crit_event)
        self.processor.process_queue(self.queue, **callbacks)

        # Verify critical hit was recorded
        self.data_store.insert_attack_event.assert_called_with(
            'TestCharacter',
            'TestTarget',
            'critical_hit',
            20,
            5,
            25
        )

    def test_damage_buffer_state(self) -> None:
        """Test damage buffer maintains state correctly."""
        callbacks = {
            'on_log_message': Mock(),
            'on_dps_updated': Mock(),
            'on_target_selected': Mock(),
            'on_immunity_changed': Mock(),
        }

        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'total_damage': 100,
            'timestamp': datetime.now(),
            'damage_types': {'Piercing': 50, 'Fire': 50},
        }

        self.queue.put(damage_event)
        self.processor.process_queue(self.queue, **callbacks)

        # Verify damage buffer contains the damage data
        self.assertIn('TestTarget', self.processor.damage_buffer)
        self.assertEqual(
            self.processor.damage_buffer['TestTarget']['damage_types'],
            {'Piercing': 50, 'Fire': 50}
        )


class TestQueueProcessorIntegration(unittest.TestCase):
    """Integration tests for QueueProcessor with real DataStore."""

    def setUp(self) -> None:
        """Set up test fixtures with real DataStore."""
        self.data_store = DataStore(db_path=':memory:')  # In-memory DB for testing
        self.parser = Mock(spec=LogParser)
        self.parser.parse_immunity = True

        self.processor = QueueProcessor(self.data_store, self.parser)
        self.queue = Queue()

    def tearDown(self) -> None:
        """Clean up test database."""
        self.data_store.close()

    def test_full_damage_and_immunity_flow(self) -> None:
        """Test complete flow of damage event followed by immunity event."""
        callbacks = {
            'on_log_message': Mock(),
            'on_dps_updated': Mock(),
            'on_target_selected': Mock(),
            'on_immunity_changed': Mock(),
        }

        now = datetime.now()

        # Process damage event
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'Rogue',
            'target': 'Dragon',
            'total_damage': 100,
            'timestamp': now,
            'damage_types': {'Fire': 100},
        }

        self.queue.put(damage_event)
        self.processor.process_queue(self.queue, **callbacks)

        # Process immunity event
        immunity_event = {
            'type': 'immunity',
            'target': 'Dragon',
            'damage_type': 'Fire',
            'immunity_points': 30,
            'timestamp': now,
        }

        self.queue.put(immunity_event)
        self.processor.process_queue(self.queue, **callbacks)

        # Verify data was recorded
        dps_data = self.data_store.get_dps_data()
        self.assertTrue(any(d['character'] == 'Rogue' for d in dps_data))


if __name__ == '__main__':
    unittest.main()

