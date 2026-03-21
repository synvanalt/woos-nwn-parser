"""Unit tests for QueueProcessor service.

Tests event processing, queue handling, and immunity tracking logic.
"""

import unittest
from unittest.mock import Mock
from datetime import datetime, timedelta
from queue import Queue

from app.services.queries import DpsQueryService
from app.services.queue_processor import QueueProcessor
from app.storage import DataStore
from app.parser import ParserSession
from tests.helpers.parsed_event_factories import (
    attack_hit_event,
    critical_hit_event,
    damage_event,
    immunity_event,
)


def _matcher(processor: QueueProcessor):
    return processor.ingestion_engine._matcher


def _damage_buffer(processor: QueueProcessor) -> dict:
    matcher = _matcher(processor)
    return {} if matcher is None else matcher.latest_damage_by_target


def _pending_immunity_queue(processor: QueueProcessor) -> dict:
    matcher = _matcher(processor)
    return {} if matcher is None else matcher.pending_immunity_queue


class TestQueueProcessor(unittest.TestCase):
    """Test suite for QueueProcessor service."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.data_store = Mock(spec=DataStore)
        self.parser = Mock(spec=ParserSession)
        self.parser.parse_immunity = False

        self.processor = QueueProcessor(self.data_store, self.parser)
        self.queue = Queue()

    def test_initialization(self) -> None:
        """Test QueueProcessor initializes correctly."""
        self.assertIsNotNone(self.processor)
        self.assertEqual(self.processor.data_store, self.data_store)
        self.assertEqual(self.processor.parser, self.parser)
        self.assertEqual(len(_damage_buffer(self.processor)), 0)
        self.assertEqual(len(_pending_immunity_queue(self.processor)), 0)

    def test_process_empty_queue(self) -> None:
        """Test processing an empty queue does nothing."""
        on_log_message = Mock()
        result = self.processor.process_queue(self.queue, on_log_message)

        on_log_message.assert_not_called()
        self.assertEqual(result.events_processed, 0)

    def test_damage_dealt_event_processing(self) -> None:
        """Test processing damage_dealt event."""
        self.queue.put(
            damage_event(
                attacker='TestCharacter',
                target='TestTarget',
                total_damage=50,
                timestamp=datetime.now(),
                damage_types={'Piercing': 50},
            )
        )

        result = self.processor.process_queue(self.queue, Mock())
        self.assertTrue(result.dps_updated)

        self.data_store.apply_mutations.assert_called_once()

    def test_immunity_event_without_damage(self) -> None:
        """Test queuing immunity event when no recent damage exists."""
        self.parser.parse_immunity = True

        self.queue.put(
            immunity_event(
                target='TestTarget',
                damage_type='Fire',
                immunity_points=20,
                timestamp=datetime.now(),
            )
        )

        self.processor.process_queue(self.queue, Mock())

        pending_queue = _pending_immunity_queue(self.processor)
        self.assertIn('TestTarget', pending_queue)
        self.assertIn('Fire', pending_queue['TestTarget'])

    def test_immunity_with_matching_damage(self) -> None:
        """Test processing immunity event with matching recent damage."""
        self.parser.parse_immunity = True

        now = datetime.now()

        self.queue.put(
            damage_event(
                attacker='TestCharacter',
                target='TestTarget',
                total_damage=50,
                timestamp=now,
                damage_types={'Fire': 50},
            )
        )
        self.processor.process_queue(self.queue, Mock())

        self.queue.put(
            immunity_event(
                target='TestTarget',
                damage_type='Fire',
                immunity_points=20,
                timestamp=now,
            )
        )
        self.processor.process_queue(self.queue, Mock())

        self.data_store.apply_mutations.assert_called()

    def test_attack_hit_event(self) -> None:
        """Test processing attack_hit event."""
        self.queue.put(
            attack_hit_event(
                attacker='TestCharacter',
                target='TestTarget',
                roll=10,
                bonus=5,
                total=15,
            )
        )
        self.processor.process_queue(self.queue, Mock())

        self.data_store.apply_mutations.assert_called_once()

    def test_cleanup_stale_immunities(self) -> None:
        """Test cleanup of stale immunity entries."""
        now = datetime.now()
        old_time = now - timedelta(seconds=10)

        matcher = _matcher(self.processor)
        assert matcher is not None
        matcher.queue_immunity(
            target='OldTarget',
            damage_type='Fire',
            immunity_points=10,
            timestamp=old_time,
            line_number=1,
        )
        matcher.queue_immunity(
            target='NewTarget',
            damage_type='Ice',
            immunity_points=15,
            timestamp=now,
            line_number=2,
        )

        self.processor.cleanup_stale_immunities(max_age_seconds=5.0)

        pending_queue = _pending_immunity_queue(self.processor)
        self.assertNotIn('OldTarget', pending_queue)
        self.assertIn('NewTarget', pending_queue)

    def test_critical_hit_event(self) -> None:
        """Test processing critical_hit event."""
        self.queue.put(
            critical_hit_event(
                attacker='TestCharacter',
                target='TestTarget',
                roll=20,
                bonus=5,
                total=25,
            )
        )
        self.processor.process_queue(self.queue, Mock())

        self.data_store.apply_mutations.assert_called_once()

    def test_damage_buffer_state(self) -> None:
        """Test damage buffer maintains state correctly."""
        self.parser.parse_immunity = True
        self.queue.put(
            damage_event(
                attacker='TestCharacter',
                target='TestTarget',
                total_damage=100,
                timestamp=datetime.now(),
                damage_types={'Piercing': 50, 'Fire': 50},
            )
        )
        self.processor.process_queue(self.queue, Mock())

        damage_buffer = _damage_buffer(self.processor)
        self.assertIn('TestTarget', damage_buffer)
        self.assertEqual(
            damage_buffer['TestTarget']['damage_types'],
            {'Piercing': 50, 'Fire': 50},
        )


class TestQueueProcessorIntegration(unittest.TestCase):
    """Integration tests for QueueProcessor with real DataStore."""

    def setUp(self) -> None:
        """Set up test fixtures with real DataStore."""
        self.data_store = DataStore()
        self.parser = Mock(spec=ParserSession)
        self.parser.parse_immunity = True

        self.processor = QueueProcessor(self.data_store, self.parser)
        self.queue = Queue()

    def tearDown(self) -> None:
        """Clean up test database."""
        self.data_store.close()

    def test_full_damage_and_immunity_flow(self) -> None:
        """Test complete flow of damage event followed by immunity event."""
        now = datetime.now()

        self.queue.put(
            damage_event(
                attacker='Rogue',
                target='Dragon',
                total_damage=100,
                timestamp=now,
                damage_types={'Fire': 100},
            )
        )
        self.processor.process_queue(self.queue, Mock())

        self.queue.put(
            immunity_event(
                target='Dragon',
                damage_type='Fire',
                immunity_points=30,
                timestamp=now,
            )
        )
        self.processor.process_queue(self.queue, Mock())

        dps_data = DpsQueryService(self.data_store).get_dps_data()
        self.assertTrue(any(d['character'] == 'Rogue' for d in dps_data))


if __name__ == '__main__':
    unittest.main()
