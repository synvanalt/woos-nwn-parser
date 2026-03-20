"""Additional resilience tests for QueueProcessor."""

import queue
from datetime import datetime, timedelta
from unittest.mock import Mock

from app.services.queue_processor import QueueProcessor
from tests.helpers.parsed_event_factories import damage_event, save_event


def _build_processor_with_mocks() -> tuple[QueueProcessor, Mock, Mock]:
    data_store = Mock()
    parser = Mock()
    parser.parse_immunity = True
    processor = QueueProcessor(data_store, parser)
    return processor, data_store, parser


def test_save_event_logs_only_when_debug_enabled() -> None:
    processor, _, _ = _build_processor_with_mocks()
    event = save_event(target='Goblin', save_type='fort', bonus=5)

    q = queue.Queue()
    q.put(event)
    on_log_message = Mock()

    processor.process_queue(q, on_log_message, debug_enabled=False)
    on_log_message.assert_not_called()

    q.put(event)
    processor.process_queue(q, on_log_message, debug_enabled=True)
    on_log_message.assert_called_once()
    assert 'SAVE' in on_log_message.call_args.args[0]


def test_unknown_event_without_message_logs_generated_fallback_message() -> None:
    processor, _, _ = _build_processor_with_mocks()
    q = queue.Queue()
    q.put({"type": "mystery_event", "x": 1})

    on_log_message = Mock()
    processor.process_queue(q, on_log_message)

    on_log_message.assert_called_once()
    msg, msg_type = on_log_message.call_args.args
    assert msg_type == 'error'
    assert msg.startswith('Unhandled parsed event:')


def test_damage_dealt_logs_dps_tracking_error_when_store_raises() -> None:
    processor, data_store, _ = _build_processor_with_mocks()
    data_store.apply_mutations.side_effect = RuntimeError('boom')

    q = queue.Queue()
    q.put(
        damage_event(
            attacker='Woo',
            target='Goblin',
            total_damage=20,
            damage_types={'Fire': 20},
            timestamp=datetime.now(),
        )
    )

    on_log_message = Mock()
    processor.process_queue(q, on_log_message)

    assert any('Data store batch error' in c.args[0] and c.args[1] == 'error' for c in on_log_message.call_args_list)


def test_damage_dealt_logs_insert_error_when_damage_event_insert_fails() -> None:
    processor, data_store, _ = _build_processor_with_mocks()
    data_store.apply_mutations.side_effect = RuntimeError('insert-failed')

    q = queue.Queue()
    q.put(
        damage_event(
            attacker='Woo',
            target='Goblin',
            total_damage=20,
            damage_types={'Fire': 20},
            timestamp=datetime.now(),
        )
    )

    on_log_message = Mock()
    processor.process_queue(q, on_log_message)

    assert any('Data store batch error' in c.args[0] and c.args[1] == 'error' for c in on_log_message.call_args_list)


def test_queued_immunity_mismatch_emits_debug_log() -> None:
    processor, data_store, _ = _build_processor_with_mocks()
    target = 'Goblin'
    damage_type = 'Fire'
    old = datetime.now() - timedelta(seconds=10)
    now = datetime.now()
    processor.immunity_matcher.queue_immunity(
        target=target,
        damage_type=damage_type,
        immunity_points=10,
        timestamp=old,
        line_number=1,
    )

    q = queue.Queue()
    q.put(
        damage_event(
            attacker='Woo',
            target=target,
            total_damage=20,
            damage_types={damage_type: 20},
            timestamp=now,
        )
    )

    on_log_message = Mock()
    processor.process_queue(q, on_log_message, debug_enabled=True)

    assert any('Queue mismatched' in c.args[0] and c.args[1] == 'debug' for c in on_log_message.call_args_list)
    data_store.apply_mutations.assert_called_once()
