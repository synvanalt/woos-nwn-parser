"""Utility functions for Woo's NWN Parser.

This module contains helper functions for file parsing and data processing
that are independent of the UI.
"""

import math
import queue
import time
from typing import Any, Callable, Dict, Iterator, List, Optional

from .parser import ParserSession
from .services.event_ingestion import EventIngestionEngine, IngestionAccumulator
from .services.immunity_matcher import ImmunityMatcher

ABORT_CHECK_MASK = 0x3FF
PROGRESS_REPORT_EVERY_LINES = 10_000
IMPORT_RESULT_QUEUE_MAXSIZE = 512
IMPORT_QUEUE_PUT_TIMEOUT_SEC = 0.05
IMPORT_QUEUE_ABORT_PUT_GRACE_SEC = 0.20
IMPORT_MUTATION_BATCH_SIZE = 2000
IMPORT_STREAM_CHUNK_SIZE = 4000
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


def pick_closest_immunity(dmg_after_immunity: int, dmg_reduced: int) -> int:
    """
    Picks the closest simulated immunity percentage when no exact reverse match exists.

    Ties resolve to the lower immunity percentage.
    """
    dmg_before_immunity = dmg_after_immunity + dmg_reduced
    best_pct = 0
    best_distance: int | None = None

    for pct in range(101):
        simulated_reduced = compute_dmg_reduced(dmg_before_immunity, pct / 100)
        distance = abs(simulated_reduced - dmg_reduced)
        if best_distance is None or distance < best_distance or (distance == best_distance and pct < best_pct):
            best_pct = pct
            best_distance = distance

    return best_pct


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
    exact_immunity = pick_immunity(matches)
    if exact_immunity is not None:
        return exact_immunity
    return pick_closest_immunity(max_damage, max_absorbed)


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
        parser: ParserSession instance
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
        ingestion_engine = EventIngestionEngine(
            parse_immunity=parser.parse_immunity,
            matcher_factory=ImmunityMatcher,
        )

        last_progress_report = 0
        accumulated = IngestionAccumulator()

        def flush_mutations() -> None:
            if accumulated.mutations:
                database.apply_mutations(accumulated.mutations)
                accumulated.mutations.clear()

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            if should_abort and should_abort():
                flush_mutations()
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
                    flush_mutations()
                    return {
                        'success': True,
                        'lines_processed': lines_processed,
                        'error': None,
                        'aborted': True
                    }

                lines_processed += 1
                parsed_data = parser.parse_line(line)
                if parsed_data:
                    accumulated.append(
                        ingestion_engine.consume(parsed_data),
                        include_side_events=False,
                    )

                    if len(accumulated.mutations) >= IMPORT_MUTATION_BATCH_SIZE:
                        flush_mutations()

                if progress_callback and (lines_processed % PROGRESS_REPORT_EVERY_LINES) == 0:
                    progress_callback(lines_processed)
                    last_progress_report = lines_processed

        if progress_callback and lines_processed > last_progress_report:
            progress_callback(lines_processed)

        flush_mutations()

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
    death_fallback_line: str = ParserSession.DEFAULT_DEATH_FALLBACK_LINE,
    should_abort: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Parse a log file and return operation payloads (no datastore mutation)."""
    try:
        parser = _build_import_parser(
            parse_immunity=parse_immunity,
            death_character_name=death_character_name,
            death_fallback_line=death_fallback_line,
        )
        lines_processed, aborted, ops = _collect_file_ops(
            file_path,
            parser=parser,
            should_abort=should_abort,
        )
        if aborted:
            return {
                'success': True,
                'aborted': True,
                'lines_processed': lines_processed,
                'error': None,
            }

        return {
            'success': True,
            'aborted': False,
            'lines_processed': lines_processed,
            'error': None,
            'ops': ops,
        }
    except Exception as e:
        return {
            'success': False,
            'aborted': False,
            'lines_processed': 0,
            'error': str(e),
        }


def _build_import_parser(
    *,
    parse_immunity: bool,
    death_character_name: str,
    death_fallback_line: str,
) -> ParserSession:
    """Build and configure a parser for import workflows."""
    parser = ParserSession(parse_immunity=parse_immunity)
    parser.set_death_character_name(death_character_name)
    parser.set_death_fallback_line(death_fallback_line)
    return parser


def _collect_file_ops(
    file_path: str,
    *,
    parser: ParserSession,
    should_abort: Optional[Callable[[], bool]] = None,
) -> tuple[int, bool, Dict[str, List[Any]]]:
    """Collect all import operations for a file."""
    lines_processed = 0
    ingestion_engine = EventIngestionEngine(
        parse_immunity=parser.parse_immunity,
        matcher_factory=ImmunityMatcher,
    )
    accumulated = IngestionAccumulator()

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as handle:
        if should_abort and should_abort():
            return lines_processed, True, {}

        for line in handle:
            if (
                should_abort
                and lines_processed
                and (lines_processed & ABORT_CHECK_MASK) == 0
                and should_abort()
            ):
                return lines_processed, True, {}

            lines_processed += 1
            parsed_data = parser.parse_line(line)
            if not parsed_data:
                continue

            accumulated.append(ingestion_engine.consume(parsed_data))

    return lines_processed, False, accumulated.build_import_ops()


def iter_file_ops_chunks(
    file_path: str,
    *,
    parse_immunity: bool = False,
    death_character_name: str = "",
    death_fallback_line: str = ParserSession.DEFAULT_DEATH_FALLBACK_LINE,
    should_abort: Optional[Callable[[], bool]] = None,
    chunk_size: int = IMPORT_STREAM_CHUNK_SIZE,
) -> Iterator[Dict[str, List[Any]]]:
    """Yield import operation chunks directly from file parsing."""
    parser = _build_import_parser(
        parse_immunity=parse_immunity,
        death_character_name=death_character_name,
        death_fallback_line=death_fallback_line,
    )
    chunk_size = max(1, int(chunk_size))
    lines_processed = 0
    ingestion_engine = EventIngestionEngine(
        parse_immunity=parser.parse_immunity,
        matcher_factory=ImmunityMatcher,
    )
    pending = IngestionAccumulator()

    def flush_pending(force: bool = False) -> Iterator[Dict[str, List[Any]]]:
        nonlocal pending
        while (
            len(pending.mutations) >= chunk_size
            or len(pending.death_events) >= chunk_size
            or len(pending.character_identity_events) >= chunk_size
            or (force and pending.has_import_ops())
        ):
            yield pending.pop_import_ops_chunk(chunk_size)

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as handle:
        if should_abort and should_abort():
            return

        for line in handle:
            if (
                should_abort
                and lines_processed
                and (lines_processed & ABORT_CHECK_MASK) == 0
                and should_abort()
            ):
                return

            lines_processed += 1
            parsed_data = parser.parse_line(line)
            if not parsed_data:
                continue

            pending.append(ingestion_engine.consume(parsed_data))
            yield from flush_pending()

    yield from flush_pending(force=True)


def import_worker_process(
    file_paths: List[str],
    parse_immunity: bool,
    abort_event,
    result_queue,
    death_character_name: str = "",
    death_fallback_line: str = ParserSession.DEFAULT_DEATH_FALLBACK_LINE,
) -> None:
    """Process target for multiprocessing import pipeline."""
    chunk_size = IMPORT_STREAM_CHUNK_SIZE

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

        try:
            for ops_chunk in iter_file_ops_chunks(
                file_path,
                parse_immunity=parse_immunity,
                death_character_name=death_character_name,
                death_fallback_line=death_fallback_line,
                should_abort=abort_event.is_set,
                chunk_size=chunk_size,
            ):
                if not _put_with_backpressure({
                    'event': 'ops_chunk',
                    'index': index,
                    'total_files': total_files,
                    'file_name': file_name,
                    'ops': ops_chunk,
                }):
                    _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
                    return
            if abort_event.is_set():
                _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
                return
        except Exception as exc:
            if not _put_with_backpressure({
                'event': 'file_error',
                'index': index,
                'total_files': total_files,
                'file_name': file_name,
                'error': str(exc),
            }):
                _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
                return
            continue

        if not _put_with_backpressure({
            'event': 'file_completed',
            'index': index,
            'total_files': total_files,
            'file_name': file_name,
        }):
            _put_with_backpressure({'event': 'aborted'}, force_on_abort=True)
            return

    _put_with_backpressure({'event': 'done'})
