"""Utility functions for Woo's NWN Parser.

This module contains helper functions for file parsing and data processing
that are independent of the UI.
"""

import math
import queue
import time
from typing import Any, Callable, Dict, List, Optional

from .parser import LogParser

ABORT_CHECK_MASK = 0x3FF
PROGRESS_REPORT_EVERY_LINES = 10_000
IMPORT_RESULT_QUEUE_MAXSIZE = 512
IMPORT_QUEUE_PUT_TIMEOUT_SEC = 0.05
IMPORT_QUEUE_ABORT_PUT_GRACE_SEC = 0.20


# Forward damage logic (AUTHORITATIVE)
def compute_dmg_reduced(dmg_before_immunity: int, immunity: float) -> int:
    """
    Computes the damage reduced according to the game's rules:
    - Immunity is a percentage in steps of 5%
    - If immunity == 0 → no damage reduction
    - If immunity > 0 → at least 1 damage is shaved off

    Args:
        dmg_before_immunity: Original damage amount
        immunity: Immunity percentage (0.0 to 1.0)

    Returns:
        Damage reduced by immunity
    """
    if dmg_before_immunity <= 0:
        return 0

    if immunity <= 0:
        return 0

    raw = math.floor(dmg_before_immunity * immunity)
    return max(1, raw)


def compute_dmg_after(dmg_before_immunity: int, immunity: float) -> int:
    """
    Computes damage after immunity is applied.

    Args:
        dmg_before_immunity: Original damage amount
        immunity: Immunity percentage (0.0 to 1.0)

    Returns:
        Damage after immunity reduction
    """
    dmg_reduced = compute_dmg_reduced(dmg_before_immunity, immunity)
    return max(0, dmg_before_immunity - dmg_reduced)


# Reverse immunity % solver
def reverse_immunity(dmg_after_immunity: int, dmg_reduced: int) -> List[float]:
    """
    Returns ALL immunity values (in 5% steps) that could have produced
    the observed dmg_reduced for the given dmg_before_immunity.

    Uses mathematical bounds to optimize search space.

    Args:
        dmg_after_immunity: Damage after immunity reduction (total_damage_dealt)
        dmg_reduced: Damage reduced by immunity (immunity_absorbed)

    Returns:
        List of possible immunity percentages (0.0 to 1.0)
    """

    immunity_step = 0.01
    allowed_immunities = [i * immunity_step for i in range(int(1 / immunity_step) + 1)]
    dmg_before_immunity = dmg_after_immunity + dmg_reduced

    if dmg_before_immunity <= 0:
        return [0.0]

    if dmg_reduced <= 0:
        return [0.0]

    # Mathematical bounds: find the range where immunity could produce dmg_reduced
    min_immunity = (dmg_reduced / dmg_before_immunity) - (1 * immunity_step)
    max_immunity = (dmg_reduced / dmg_before_immunity) + (1 * immunity_step)

    matches = []
    for immunity in allowed_immunities:
        # Use bounds check to reduce unnecessary calls
        if min_immunity <= immunity <= max_immunity:
            # Verify (due to floor function edge cases)
            if compute_dmg_reduced(dmg_before_immunity, immunity) == dmg_reduced:
                matches.append(immunity)

    return matches


# Immunity picker
def pick_immunity(matches: List[float]) -> Optional[float]:
    """
    Picks a single immunity value from possible matches.
    Uses 'min' strategy for most conservative estimate.

    Args:
        matches: List of possible immunity percentages

    Returns:
        Immunity percentage as integer (0-100), or None if no matches
    """
    if not matches:
        return None

    # Use minimum as most conservative estimate
    return int(min(matches) * 100)


# Main calculation function
def calculate_immunity_percentage(max_damage: int, max_absorbed: int) -> Optional[int]:
    """
    Calculates the immunity percentage based on max damage and max absorption.

    This is the main entry point for immunity % calculation.

    Args:
        max_damage: Maximum damage dealt (per damage type)
        max_absorbed: Maximum damage absorbed (per damage type)

    Returns:
        Immunity percentage (5, 10, 15, ..., 95, 100) or None if unknown
    """
    if max_damage <= 0:
        return None

    if max_absorbed <= 0:
        return 0  # No immunity observed

    matches = reverse_immunity(max_damage, max_absorbed)
    return pick_immunity(matches)


def parse_and_import_file(
    file_path: str,
    parser,
    database,
    *,
    should_abort: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Dict:
    """Parse a log file and import data into database.

    Does not depend on GUI components, making it testable without Tkinter.

    Note: This function does NOT clear existing data. The caller should clear
    data before calling this function if needed (e.g., when processing multiple
    files, clear once before the first file, not before each file).

    Args:
        file_path: Path to the log file
        parser: LogParser instance
        database: DataStore instance

    Returns:
        dict with keys:
        - 'success' (bool)
        - 'lines_processed' (int)
        - 'error' (str or None)
        - 'aborted' (bool)
    """
    try:

        lines_processed = 0
        # Track the last damage_dealt for each target to match immunities
        last_damage_dealt = {}

        last_progress_report = 0

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            if should_abort and should_abort():
                return {
                    'success': True,
                    'lines_processed': lines_processed,
                    'error': None,
                    'aborted': True
                }

            for line in f:
                # Keep cancellation responsive during large file imports.
                if (
                    should_abort
                    and lines_processed
                    and (lines_processed & ABORT_CHECK_MASK) == 0
                    and should_abort()
                ):
                    return {
                        'success': True,
                        'lines_processed': lines_processed,
                        'error': None,
                        'aborted': True
                    }

                lines_processed += 1
                parsed_data = parser.parse_line(line)
                if parsed_data:
                    if parsed_data['type'] == 'damage_dealt':
                        target = parsed_data['target']
                        attacker = parsed_data['attacker']
                        timestamp = parsed_data['timestamp']
                        total_damage = parsed_data['total_damage']

                        # Always track DPS data for all characters
                        damage_types = parsed_data.get('damage_types', {})
                        database.update_dps_data(attacker, total_damage, timestamp, damage_types)

                        # Always store target damage events for complete data tracking (consistent with monitoring behavior)
                        # Store all damage types from this damage_dealt event
                        for dt, amount in parsed_data['damage_types'].items():
                            amount_int = int(amount or 0)
                            database.insert_damage_event(target, dt, 0, amount_int, attacker, timestamp)
                        # Remember this damage event for immunity matching
                        last_damage_dealt[target] = {
                            'damage_types': parsed_data['damage_types'],
                            'timestamp': timestamp,
                            'attacker': attacker
                        }

                    elif parsed_data['type'] == 'immunity':
                        target = parsed_data['target']
                        damage_type = parsed_data['damage_type']
                        immunity_points = parsed_data['immunity_points']

                        # Try to match with the last damage_dealt for this target
                        if target in last_damage_dealt:
                            damage_types = last_damage_dealt[target]['damage_types']
                            if damage_type in damage_types:
                                # Use the damage amount from the matched damage_dealt
                                damage_amount = int(damage_types[damage_type] or 0)
                                # Record immunity data separately (not as duplicate damage events)
                                database.record_immunity(target, damage_type, immunity_points, damage_amount)

                    # Handle attack events
                    elif parsed_data['type'] == 'attack_hit':
                        database.insert_attack_event(
                            parsed_data['attacker'],
                            parsed_data['target'],
                            'hit',
                            parsed_data.get('roll'),
                            parsed_data.get('bonus'),
                            parsed_data.get('total'),
                            was_nat1=bool(parsed_data.get('was_nat1', False)),
                            was_nat20=bool(parsed_data.get('was_nat20', False)),
                            is_concealment=bool(parsed_data.get('is_concealment', False)),
                        )
                    elif parsed_data['type'] == 'attack_hit_critical':
                        database.insert_attack_event(
                            parsed_data['attacker'],
                            parsed_data['target'],
                            'critical_hit',
                            parsed_data.get('roll'),
                            parsed_data.get('bonus'),
                            parsed_data.get('total'),
                            was_nat1=bool(parsed_data.get('was_nat1', False)),
                            was_nat20=bool(parsed_data.get('was_nat20', False)),
                            is_concealment=bool(parsed_data.get('is_concealment', False)),
                        )
                    elif parsed_data['type'] == 'attack_miss':
                        database.insert_attack_event(
                            parsed_data['attacker'],
                            parsed_data['target'],
                            'miss',
                            parsed_data.get('roll'),
                            parsed_data.get('bonus'),
                            parsed_data.get('total'),
                            was_nat1=bool(parsed_data.get('was_nat1', False)),
                            was_nat20=bool(parsed_data.get('was_nat20', False)),
                            is_concealment=bool(parsed_data.get('is_concealment', False)),
                        )
                    elif parsed_data['type'] == 'save':
                        database.record_target_save(
                            parsed_data['target'],
                            parsed_data['save_type'],
                            parsed_data['bonus'],
                        )
                    elif parsed_data['type'] == 'epic_dodge':
                        database.mark_target_epic_dodge(parsed_data['target'])

                if progress_callback and (lines_processed % PROGRESS_REPORT_EVERY_LINES) == 0:
                    progress_callback(lines_processed)
                    last_progress_report = lines_processed

        if progress_callback and lines_processed > last_progress_report:
            progress_callback(lines_processed)

        return {
            'success': True,
            'lines_processed': lines_processed,
            'error': None,
            'aborted': False
        }
    except Exception as e:
        return {
            'success': False,
            'lines_processed': 0,
            'error': str(e),
            'aborted': False
        }


def parse_file_to_ops(
    file_path: str,
    *,
    parse_immunity: bool = False,
    death_character_name: str = "",
    death_fallback_line: str = LogParser.DEFAULT_DEATH_FALLBACK_LINE,
    should_abort: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Parse a log file and return operation payloads (no datastore mutation)."""
    try:
        parser = LogParser(parse_immunity=parse_immunity)
        parser.set_death_character_name(death_character_name)
        parser.set_death_fallback_line(death_fallback_line)
        lines_processed = 0
        last_damage_dealt = {}

        dps_updates = []
        damage_events = []
        immunity_records = []
        attack_events = []
        save_events = []
        epic_dodge_targets = []
        death_snippets = []

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            if should_abort and should_abort():
                return {
                    'success': True,
                    'aborted': True,
                    'lines_processed': lines_processed,
                    'error': None,
                }

            for line in f:
                if (
                    should_abort
                    and lines_processed
                    and (lines_processed & ABORT_CHECK_MASK) == 0
                    and should_abort()
                ):
                    return {
                        'success': True,
                        'aborted': True,
                        'lines_processed': lines_processed,
                        'error': None,
                    }

                lines_processed += 1
                parsed_data = parser.parse_line(line)
                if not parsed_data:
                    continue

                if parsed_data['type'] == 'damage_dealt':
                    target = parsed_data['target']
                    attacker = parsed_data['attacker']
                    timestamp = parsed_data['timestamp']
                    total_damage = parsed_data['total_damage']
                    damage_types = parsed_data.get('damage_types', {})

                    dps_updates.append((attacker, total_damage, timestamp, damage_types))
                    for dt, amount in damage_types.items():
                        damage_events.append((target, dt, 0, int(amount or 0), attacker, timestamp))

                    last_damage_dealt[target] = {
                        'damage_types': damage_types,
                    }

                elif parsed_data['type'] == 'immunity':
                    target = parsed_data['target']
                    damage_type = parsed_data['damage_type']
                    immunity_points = parsed_data['immunity_points']
                    if target in last_damage_dealt:
                        damage_types = last_damage_dealt[target]['damage_types']
                        if damage_type in damage_types:
                            damage_amount = int(damage_types[damage_type] or 0)
                            immunity_records.append((target, damage_type, immunity_points, damage_amount))

                elif parsed_data['type'] == 'attack_hit':
                    attack_events.append((
                        parsed_data['attacker'],
                        parsed_data['target'],
                        'hit',
                        parsed_data.get('roll'),
                        parsed_data.get('bonus'),
                        parsed_data.get('total'),
                        False,
                        bool(parsed_data.get('was_nat20', False)),
                        bool(parsed_data.get('is_concealment', False)),
                    ))
                elif parsed_data['type'] == 'attack_hit_critical':
                    attack_events.append((
                        parsed_data['attacker'],
                        parsed_data['target'],
                        'critical_hit',
                        parsed_data.get('roll'),
                        parsed_data.get('bonus'),
                        parsed_data.get('total'),
                        False,
                        bool(parsed_data.get('was_nat20', False)),
                        bool(parsed_data.get('is_concealment', False)),
                    ))
                elif parsed_data['type'] == 'attack_miss':
                    attack_events.append((
                        parsed_data['attacker'],
                        parsed_data['target'],
                        'miss',
                        parsed_data.get('roll'),
                        parsed_data.get('bonus'),
                        parsed_data.get('total'),
                        bool(parsed_data.get('was_nat1', False)),
                        False,
                        bool(parsed_data.get('is_concealment', False)),
                    ))
                elif parsed_data['type'] == 'save':
                    save_events.append((
                        parsed_data.get('target'),
                        parsed_data.get('save_type'),
                        parsed_data.get('bonus'),
                    ))
                elif parsed_data['type'] == 'epic_dodge':
                    epic_dodge_targets.append(parsed_data.get('target'))
                elif parsed_data['type'] == 'death_snippet':
                    death_snippets.append({
                        'target': parsed_data.get('target', ''),
                        'killer': parsed_data.get('killer', ''),
                        'lines': parsed_data.get('lines', []),
                        'timestamp': parsed_data.get('timestamp'),
                        'type': 'death_snippet',
                    })

        return {
            'success': True,
            'aborted': False,
            'lines_processed': lines_processed,
            'error': None,
            'ops': {
                'dps_updates': dps_updates,
                'damage_events': damage_events,
                'immunity_records': immunity_records,
                'attack_events': attack_events,
                'save_events': save_events,
                'epic_dodge_targets': epic_dodge_targets,
                'death_snippets': death_snippets,
            },
            'parser_state': {},
        }
    except Exception as e:
        return {
            'success': False,
            'aborted': False,
            'lines_processed': 0,
            'error': str(e),
        }


def import_worker_process(
    file_paths: List[str],
    parse_immunity: bool,
    abort_event,
    result_queue,
    death_character_name: str = "",
    death_fallback_line: str = LogParser.DEFAULT_DEATH_FALLBACK_LINE,
) -> None:
    """Process target for multiprocessing import pipeline."""
    chunk_size = 2000

    def _put_with_backpressure(
        event: Dict[str, Any],
        *,
        force_on_abort: bool = False,
    ) -> bool:
        """Enqueue worker events with bounded blocking and abort responsiveness."""
        started_at = time.monotonic()
        while True:
            if abort_event.is_set() and not force_on_abort:
                return False
            try:
                result_queue.put(event, timeout=IMPORT_QUEUE_PUT_TIMEOUT_SEC)
                return True
            except queue.Full:
                if abort_event.is_set() and not force_on_abort:
                    return False
                if force_on_abort and (time.monotonic() - started_at) >= IMPORT_QUEUE_ABORT_PUT_GRACE_SEC:
                    return False

    def _slice_chunks(values: List, size: int) -> List[List]:
        return [values[i:i + size] for i in range(0, len(values), size)]

    total_files = len(file_paths)
    for index, file_path in enumerate(file_paths, start=1):
        if abort_event.is_set():
            _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
            return

        file_name = file_path.replace("\\", "/").split("/")[-1]
        if not _put_with_backpressure({
            'event': 'file_started',
            'index': index,
            'total_files': total_files,
            'file_name': file_name,
        }):
            _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
            return

        result = parse_file_to_ops(
            file_path,
            parse_immunity=parse_immunity,
            death_character_name=death_character_name,
            death_fallback_line=death_fallback_line,
            should_abort=abort_event.is_set,
        )

        if result.get('aborted'):
            _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
            return

        if not result.get('success'):
            if not _put_with_backpressure({
                'event': 'file_error',
                'index': index,
                'total_files': total_files,
                'file_name': file_name,
                'error': result.get('error', 'Unknown error'),
            }):
                _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
                return
            continue

        ops = result.get('ops', {})
        dps_chunks = _slice_chunks(ops.get('dps_updates', []), chunk_size)
        damage_chunks = _slice_chunks(ops.get('damage_events', []), chunk_size)
        immunity_chunks = _slice_chunks(ops.get('immunity_records', []), chunk_size)
        attack_chunks = _slice_chunks(ops.get('attack_events', []), chunk_size)
        save_chunks = _slice_chunks(ops.get('save_events', []), chunk_size)
        epic_dodge_chunks = _slice_chunks(ops.get('epic_dodge_targets', []), chunk_size)
        death_chunks = _slice_chunks(ops.get('death_snippets', []), chunk_size)

        max_chunk_count = max(
            len(dps_chunks),
            len(damage_chunks),
            len(immunity_chunks),
            len(attack_chunks),
            len(save_chunks),
            len(epic_dodge_chunks),
            len(death_chunks),
            0,
        )

        for chunk_idx in range(max_chunk_count):
            if not _put_with_backpressure({
                'event': 'ops_chunk',
                'index': index,
                'total_files': total_files,
                'file_name': file_name,
                'ops': {
                    'dps_updates': dps_chunks[chunk_idx] if chunk_idx < len(dps_chunks) else [],
                    'damage_events': damage_chunks[chunk_idx] if chunk_idx < len(damage_chunks) else [],
                    'immunity_records': immunity_chunks[chunk_idx] if chunk_idx < len(immunity_chunks) else [],
                    'attack_events': attack_chunks[chunk_idx] if chunk_idx < len(attack_chunks) else [],
                    'save_events': save_chunks[chunk_idx] if chunk_idx < len(save_chunks) else [],
                    'epic_dodge_targets': epic_dodge_chunks[chunk_idx] if chunk_idx < len(epic_dodge_chunks) else [],
                    'death_snippets': death_chunks[chunk_idx] if chunk_idx < len(death_chunks) else [],
                },
            }):
                _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
                return

        if not _put_with_backpressure({
            'event': 'file_completed',
            'index': index,
            'total_files': total_files,
            'file_name': file_name,
            'parser_state': result.get('parser_state', {}),
        }):
            _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
            return

    _put_with_backpressure({'event': 'done'})
