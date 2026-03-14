"""Unit tests for QueueProcessor service.

Tests event processing, queue handling, and immunity tracking logic.
"""

import unittest
from unittest.mock import Mock
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
        on_log_message = Mock()
        result = self.processor.process_queue(self.queue, on_log_message)

        # No callbacks should be called for empty queue
        on_log_message.assert_not_called()
        self.assertEqual(result.events_processed, 0)

    def test_damage_dealt_event_processing(self) -> None:
        """Test processing damage_dealt event."""
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'total_damage': 50,
            'timestamp': datetime.now(),
            'damage_types': {'Piercing': 50},
        }

        self.queue.put(damage_event)

        result = self.processor.process_queue(self.queue, Mock())
        self.assertTrue(result.dps_updated)

        self.data_store.apply_mutations.assert_called_once()

    def test_immunity_event_without_damage(self) -> None:
        """Test queuing immunity event when no recent damage exists."""
        self.parser.parse_immunity = True

        immunity_event = {
            'type': 'immunity',
            'target': 'TestTarget',
            'damage_type': 'Fire',
            'immunity_points': 20,
            'timestamp': datetime.now(),
        }

        self.queue.put(immunity_event)

        self.processor.process_queue(self.queue, Mock())

        # Immunity should be queued
        self.assertIn('TestTarget', self.processor.pending_immunity_queue)
        self.assertIn('Fire', self.processor.pending_immunity_queue['TestTarget'])

    def test_immunity_with_matching_damage(self) -> None:
        """Test processing immunity event with matching recent damage."""
        self.parser.parse_immunity = True

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
        self.processor.process_queue(self.queue, Mock())

        # Then add matching immunity event
        immunity_event = {
            'type': 'immunity',
            'target': 'TestTarget',
            'damage_type': 'Fire',
            'immunity_points': 20,
            'timestamp': now,
        }

        self.queue.put(immunity_event)
        self.processor.process_queue(self.queue, Mock())

        self.data_store.apply_mutations.assert_called()

    def test_attack_hit_event(self) -> None:
        """Test processing attack_hit event."""
        attack_event = {
            'type': 'attack_hit',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'roll': 10,
            'bonus': 5,
            'total': 15,
        }

        self.queue.put(attack_event)
        self.processor.process_queue(self.queue, Mock())

        self.data_store.apply_mutations.assert_called_once()

    def test_cleanup_stale_immunities(self) -> None:
        """Test cleanup of stale immunity entries."""
        now = datetime.now()
        old_time = now - timedelta(seconds=10)

        self.processor.immunity_matcher.queue_immunity(
            target='OldTarget',
            damage_type='Fire',
            immunity_points=10,
            timestamp=old_time,
            line_number=1,
        )
        self.processor.immunity_matcher.queue_immunity(
            target='NewTarget',
            damage_type='Ice',
            immunity_points=15,
            timestamp=now,
            line_number=2,
        )

        # Clean up entries older than 5 seconds
        self.processor.cleanup_stale_immunities(max_age_seconds=5.0)

        # Old target should be removed
        self.assertNotIn('OldTarget', self.processor.pending_immunity_queue)

        # New target should remain
        self.assertIn('NewTarget', self.processor.pending_immunity_queue)

    def test_critical_hit_event(self) -> None:
        """Test processing critical_hit event."""
        crit_event = {
            'type': 'critical_hit',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'roll': 20,
            'bonus': 5,
            'total': 25,
        }

        self.queue.put(crit_event)
        self.processor.process_queue(self.queue, Mock())

        self.data_store.apply_mutations.assert_called_once()

    def test_damage_buffer_state(self) -> None:
        """Test damage buffer maintains state correctly."""
        damage_event = {
            'type': 'damage_dealt',
            'attacker': 'TestCharacter',
            'target': 'TestTarget',
            'total_damage': 100,
            'timestamp': datetime.now(),
            'damage_types': {'Piercing': 50, 'Fire': 50},
        }

        self.queue.put(damage_event)
        self.processor.process_queue(self.queue, Mock())

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
        self.data_store = DataStore()
        self.parser = Mock(spec=LogParser)
        self.parser.parse_immunity = True

        self.processor = QueueProcessor(self.data_store, self.parser)
        self.queue = Queue()

    def tearDown(self) -> None:
        """Clean up test database."""
        self.data_store.close()

    def test_full_damage_and_immunity_flow(self) -> None:
        """Test complete flow of damage event followed by immunity event."""
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
        self.processor.process_queue(self.queue, Mock())

        # Process immunity event
        immunity_event = {
            'type': 'immunity',
            'target': 'Dragon',
            'damage_type': 'Fire',
            'immunity_points': 30,
            'timestamp': now,
        }

        self.queue.put(immunity_event)
        self.processor.process_queue(self.queue, Mock())

        # Verify data was recorded
        dps_data = self.data_store.get_dps_data()
        self.assertTrue(any(d['character'] == 'Rogue' for d in dps_data))


if __name__ == '__main__':
    unittest.main()

