"""Queue processing service for log events.

This module handles all event processing from the log parser queue,
including damage tracking, immunity tracking, and attack tracking.
All logic is pure Python with no Tkinter dependencies.
"""

import queue
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Dict, Callable, List, Any, Set

from ..models import (
    AttackMutation,
    DamageMutation,
    EpicDodgeMutation,
    ImmunityMutation,
    SaveMutation,
    StoreMutation,
)
from ..storage import DataStore
from ..parser import LogParser


@dataclass
class QueueDrainResult:
    """Result of one queue-drain pass."""

    events_processed: int = 0
    dps_updated: bool = False
    targets_to_refresh: Set[str] = field(default_factory=set)
    immunity_targets: Set[str] = field(default_factory=set)
    damage_targets: Set[str] = field(default_factory=set)
    death_events: List[Dict[str, Any]] = field(default_factory=list)
    character_identity_events: List[Dict[str, Any]] = field(default_factory=list)
    has_backlog: bool = False
    backlog_count: int = 0
    pressure_state: str = "normal"


class QueueProcessor:
    """Process events from log parser queue.

    Handles:
    - damage_dealt: DPS and damage type tracking
    - immunity: Immunity value tracking with queuing
    - attack_hit/miss/critical: Attack tracking

    Delegates UI updates via callbacks to keep this class pure Python.
    """

    def __init__(self, data_store: DataStore, parser: LogParser) -> None:
        """Initialize the queue processor.

        Args:
            data_store: Reference to the data store
            parser: Reference to the log parser
        """
        self.data_store = data_store
        self.parser = parser
        self.damage_buffer: Dict[str, Dict] = {}
        self.pending_immunity_queue: Dict[str, Dict[str, list]] = {}
        self.parsed_event_count = 0
        self.next_immunity_cleanup_event_count = 100

    def process_queue(
        self,
        data_queue: queue.Queue,
        on_log_message: Callable[[str, str], None],
        debug_enabled: bool = False,
        max_events: int = 2000,
        max_time_ms: float | None = None,
    ) -> QueueDrainResult:
        """Process a bounded batch of queue events.

        Args:
            data_queue: Queue of events from LogDirectoryMonitor
            on_log_message: Callback for log messages (message, type)
            debug_enabled: Whether to emit debug messages
            max_events: Maximum events to process in this call
            max_time_ms: Maximum wall-clock budget for this call

        Returns:
            QueueDrainResult with dirty-state information for batched UI refreshes
        """
        result = QueueDrainResult()
        started = perf_counter()
        pending_mutations: List[StoreMutation] = []

        try:
            while result.events_processed < max_events:
                if max_time_ms is not None:
                    elapsed_ms = (perf_counter() - started) * 1000.0
                    if elapsed_ms >= max_time_ms:
                        break

                data = data_queue.get_nowait()
                result.events_processed += 1

                # Process event and track what needs UI update
                event_result = self._handle_event_batched(
                    data,
                    pending_mutations,
                    on_log_message,
                    debug_enabled,
                )

                if event_result:
                    if event_result.get('dps_updated'):
                        result.dps_updated = True
                    if event_result.get('target'):
                        result.targets_to_refresh.add(event_result['target'])
                    if event_result.get('immunity_target'):
                        result.immunity_targets.add(event_result['immunity_target'])
                    if event_result.get('damage_target'):
                        result.damage_targets.add(event_result['damage_target'])
                    if event_result.get('death_event'):
                        result.death_events.append(event_result['death_event'])
                    if event_result.get('character_identified'):
                        result.character_identity_events.append(event_result['character_identified'])

        except queue.Empty:
            pass

        if pending_mutations:
            try:
                self.data_store.apply_mutations(pending_mutations)
            except Exception as e:
                on_log_message(f"Data store batch error: {e}", 'error')

        result.backlog_count = self._get_queue_size_hint(data_queue)
        result.has_backlog = result.backlog_count > 0
        result.pressure_state = self._classify_backpressure(
            backlog_count=result.backlog_count,
            queue_maxsize=getattr(data_queue, "maxsize", 0),
        )

        # Periodic cleanup of stale immunity entries (every 100 processed events)
        self.parsed_event_count += result.events_processed
        if (
            result.events_processed > 0
            and self.parsed_event_count >= self.next_immunity_cleanup_event_count
        ):
            self.cleanup_stale_immunities(max_age_seconds=5.0)
            while self.next_immunity_cleanup_event_count <= self.parsed_event_count:
                self.next_immunity_cleanup_event_count += 100

        return result

    @staticmethod
    def _get_queue_size_hint(data_queue: queue.Queue) -> int:
        """Return an approximate queue size without relying on exactness."""
        try:
            size = int(data_queue.qsize())
        except (AttributeError, NotImplementedError):
            return 0
        return max(size, 0)

    @staticmethod
    def _classify_backpressure(backlog_count: int, queue_maxsize: int) -> str:
        """Classify queue pressure for scheduling decisions only."""
        if backlog_count <= 0:
            return "normal"

        if queue_maxsize and queue_maxsize > 0:
            pressured_threshold = max(1, queue_maxsize // 2)
            saturated_threshold = max(pressured_threshold + 1, int(queue_maxsize * 0.85))
        else:
            pressured_threshold = 2000
            saturated_threshold = 3400

        if backlog_count >= saturated_threshold:
            return "saturated"
        if backlog_count >= pressured_threshold:
            return "pressured"
        return "normal"

    def _handle_event_batched(
        self,
        data: Dict[str, Any],
        pending_mutations: List[StoreMutation],
        on_log_message: Callable,
        debug_enabled: bool,
    ) -> Dict[str, Any]:
        """Route event to appropriate handler and return what needs UI update.

        Args:
            data: Event data from queue
            on_log_message: Callback for logging
            debug_enabled: Whether to emit debug messages

        Returns:
            Dict with keys indicating what needs updating:
            - dps_updated: bool
            - target: str (for target selection refresh)
            - immunity_target: str (for immunity refresh)
            - damage_target: str (for damage dealt)
        """
        event_type = data.get('type')
        result = {}

        if event_type == 'damage_dealt':
            result = self._handle_damage_dealt_batched(
                data, pending_mutations, on_log_message, debug_enabled
            )
        elif event_type == 'immunity':
            result = self._handle_immunity_batched(
                data, pending_mutations, on_log_message, debug_enabled
            )
        elif event_type in (
            'attack_hit',
            'attack_miss',
            'attack_hit_critical',
            'critical_hit',
        ):
            result = self._handle_attack_batched(
                data, pending_mutations, on_log_message, debug_enabled
            )
        elif event_type == 'epic_dodge':
            target = data.get('target')
            if target:
                pending_mutations.append(EpicDodgeMutation(target=target))
                result['target'] = target
            if debug_enabled:
                on_log_message(f"EPIC DODGE: {target}", 'debug')
        elif event_type == 'death_snippet':
            result['death_event'] = data
        elif event_type == 'death_character_identified':
            result['character_identified'] = data
        elif event_type == 'save':
            target = data.get('target')
            save_type = data.get('save_type')
            bonus = data.get('bonus')
            if target and save_type and bonus is not None:
                pending_mutations.append(
                    SaveMutation(target=target, save_key=str(save_type), bonus=int(bonus))
                )
                result['target'] = target
            if debug_enabled:
                on_log_message(
                    f"⚕️ SAVE: {target or 'Unknown'} ({str(save_type or 'Unknown').title()} {bonus or 0})",
                    'debug'
                )
        else:
            # Log other message types with proper formatting
            message = data.get('message', '')
            if not message:
                # If no message, create one from the event data
                message = f"Event: {event_type} - {data}"
            on_log_message(message, event_type)

        return result

    def _handle_damage_dealt_batched(
        self,
        data: Dict[str, Any],
        pending_mutations: List[StoreMutation],
        on_log_message: Callable,
        debug_enabled: bool,
    ) -> Dict[str, Any]:
        """Handle damage_dealt event (batched version - no immediate callbacks).

        Args:
            data: Event data containing damage information
            on_log_message: Callback for logging
            debug_enabled: Whether to emit debug messages

        Returns:
            Dict indicating what needs UI update
        """
        result = {'dps_updated': False, 'damage_target': None}

        try:
            attacker = data.get('attacker')
            if attacker:
                target = data.get('target')
                total_damage = data.get('total_damage', 0)
                timestamp = data.get('timestamp', datetime.now())
                damage_types = data.get('damage_types', {})

                pending_mutations.append(
                    DamageMutation(
                        target=target,
                        damage_type="",
                        total_damage=int(total_damage or 0),
                        attacker=attacker,
                        timestamp=timestamp,
                        count_for_dps=True,
                        damage_types={k: int(v or 0) for k, v in damage_types.items()},
                    )
                )
                if debug_enabled:
                    on_log_message(
                        f"💥 DAMAGE: {attacker} vs {target} ({total_damage} damage)", 'debug'
                    )
                result['dps_updated'] = True
        except Exception as e:
            on_log_message(f"DPS tracking error: {e}", 'error')

        # Buffer damage for immunity matching
        target = data['target']
        self.damage_buffer[target] = {
            'damage_types': data['damage_types'],
            'timestamp': data['timestamp'],
            'attacker': data.get('attacker', ''),
        }

        # Insert damage events
        try:
            for dt, amount in data['damage_types'].items():
                amount_int = int(amount or 0)
                pending_mutations.append(
                    DamageMutation(
                        target=target,
                        damage_type=dt,
                        immunity_absorbed=0,
                        total_damage=amount_int,
                        attacker=data.get('attacker', ''),
                        timestamp=data['timestamp'],
                    )
                )
        except Exception as e:
            on_log_message(f"Data store error on damage_dealt: {e}", 'error')

        # Process queued immunities (internal, returns if any were processed)
        immunity_processed = self._process_queued_immunities_batched(
            target, data, pending_mutations, on_log_message, debug_enabled
        )

        result['damage_target'] = target
        if immunity_processed:
            result['immunity_target'] = target
        return result

    def _handle_immunity_batched(
        self,
        data: Dict[str, Any],
        pending_mutations: List[StoreMutation],
        on_log_message: Callable,
        debug_enabled: bool,
    ) -> Dict[str, Any]:
        """Handle dmg_absorbed event (batched version).

        Args:
            data: Event data containing dmg_absorbed information
            on_log_message: Callback for logging
            debug_enabled: Whether to emit debug messages

        Returns:
            Dict indicating what needs UI update
        """
        result = {}

        if not self.parser.parse_immunity:
            if debug_enabled:
                on_log_message(
                    f"Skipping dmg_absorbed event for {data.get('target')}/{data.get('damage_type')} "
                    "(parsing disabled)",
                    'debug',
                )
            return result

        target = data['target']
        damage_type = data.get('damage_type')

        if damage_type:
            # Check if recent damage exists
            if (
                target in self.damage_buffer
                and damage_type in self.damage_buffer[target].get('damage_types', {})
            ):
                dmg_absorbed = data.get('immunity_points', 0)
                damage_dealt = self.damage_buffer[target]['damage_types'].get(
                    damage_type, 0
                )

                try:
                    dmg_inflicted = int(damage_dealt or 0)
                    pending_mutations.append(
                        ImmunityMutation(
                            target=target,
                            damage_type=damage_type,
                            immunity_points=int(dmg_absorbed or 0),
                            damage_dealt=dmg_inflicted,
                        )
                    )
                    if debug_enabled:
                        on_log_message(
                            f"🛟 IMMUNITY: {target} absorbed {dmg_absorbed} {damage_type} (inflicted {dmg_inflicted})",
                            'debug',
                        )
                except Exception as e:
                    on_log_message(f"Data store error: {e}", 'error')

                result['target'] = target
            else:
                # Queue dmg_absorbed for later
                self._queue_immunity(target, damage_type, data)

        return result

    def _handle_attack_batched(
        self,
        data: Dict[str, Any],
        pending_mutations: List[StoreMutation],
        on_log_message: Callable,
        debug_enabled: bool,
    ) -> Dict[str, Any]:
        """Handle attack_hit, attack_miss, or critical_hit event (batched version).

        Args:
            data: Event data containing attack information
            on_log_message: Callback for logging
            debug_enabled: Whether to emit debug messages

        Returns:
            Dict indicating what needs UI update
        """
        attacker = data.get('attacker')
        target = data.get('target')

        if data['type'] in ('attack_hit_critical', 'critical_hit'):
            event_type = 'critical_hit'
        elif data['type'] == 'attack_hit':
            event_type = 'hit'
        else:
            event_type = 'miss'

        pending_mutations.append(
            AttackMutation(
                attacker=attacker,
                target=target,
                outcome=event_type,
                roll=data.get('roll'),
                bonus=data.get('bonus'),
                total=data.get('total'),
                was_nat1=bool(data.get('was_nat1', False)),
                was_nat20=bool(data.get('was_nat20', False)),
                is_concealment=bool(data.get('is_concealment', False)),
            )
        )

        if debug_enabled:
            on_log_message(
                f"⚔️ ATTACK: {attacker} vs {target} ({event_type})", 'debug'
            )

        return {'target': target}

    def _process_queued_immunities_batched(
        self,
        target: str,
        damage_event: Dict[str, Any],
        pending_mutations: List[StoreMutation],
        on_log_message: Callable,
        debug_enabled: bool,
    ) -> bool:
        """Process any immunities waiting for this damage event (no callbacks).

        Args:
            target: Target name
            damage_event: The damage event data
            on_log_message: Callback for logging
            debug_enabled: Whether to emit debug messages

        Returns:
            True if any immunities were processed, False otherwise
        """
        if target not in self.pending_immunity_queue:
            return False

        processed_any = False
        for damage_type in list(self.pending_immunity_queue[target].keys()):
            if damage_type not in damage_event['damage_types']:
                continue

            for queued_immunity in self.pending_immunity_queue[target][damage_type]:
                immunity = queued_immunity['immunity']
                immunity_timestamp = queued_immunity['timestamp']
                damage_dealt = damage_event['damage_types'].get(damage_type, 0)
                damage_timestamp = damage_event['timestamp']

                time_diff = abs(
                    (damage_timestamp - immunity_timestamp).total_seconds()
                )

                if time_diff <= 1:  # Allow 1-second difference
                    try:
                        inferred_amount = int(damage_dealt or 0)
                        pending_mutations.append(
                            ImmunityMutation(
                                target=target,
                                damage_type=damage_type,
                                immunity_points=immunity,
                                damage_dealt=inferred_amount,
                            )
                        )
                        if debug_enabled:
                            on_log_message(
                                f"🛟 IMMUNITY: Queue processed {target}/{damage_type}",
                                'debug',
                            )
                        processed_any = True
                    except Exception as e:
                        on_log_message(f"Data store error processing queued immunity: {e}", 'error')
                else:
                    if debug_enabled:
                        on_log_message(
                            f"🛟 IMMUNITY: Queue mismatched {target}/{damage_type} ({time_diff:.1f}s)",
                            'debug',
                        )

            # Clear processed queue
            del self.pending_immunity_queue[target][damage_type]

        # Clean up empty target entries
        if not self.pending_immunity_queue[target]:
            del self.pending_immunity_queue[target]

        return processed_any

    def _queue_immunity(
        self, target: str, damage_type: str, data: Dict[str, Any]
    ) -> None:
        """Queue immunity event for later processing.

        Args:
            target: Target name
            damage_type: Type of damage
            data: Event data
        """
        immunity = data.get('immunity_points', 0)
        timestamp = data.get('timestamp', datetime.now())

        if target not in self.pending_immunity_queue:
            self.pending_immunity_queue[target] = {}

        if damage_type not in self.pending_immunity_queue[target]:
            self.pending_immunity_queue[target][damage_type] = []

        self.pending_immunity_queue[target][damage_type].append(
            {'immunity': immunity, 'timestamp': timestamp}
        )

    def cleanup_stale_immunities(self, max_age_seconds: float = 5.0) -> None:
        """Remove immunity entries older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age in seconds before removal
        """
        now = datetime.now()
        targets_to_remove = []

        for target in self.pending_immunity_queue:
            damage_types_to_remove = []

            for damage_type in self.pending_immunity_queue[target]:
                # Filter out old entries
                self.pending_immunity_queue[target][damage_type] = [
                    entry
                    for entry in self.pending_immunity_queue[target][damage_type]
                    if (now - entry['timestamp']).total_seconds()
                    <= max_age_seconds
                ]

                # Track empty damage type entries for removal
                if not self.pending_immunity_queue[target][damage_type]:
                    damage_types_to_remove.append(damage_type)

            # Remove empty damage type entries
            for damage_type in damage_types_to_remove:
                del self.pending_immunity_queue[target][damage_type]

            # Track empty target entries for removal
            if not self.pending_immunity_queue[target]:
                targets_to_remove.append(target)

        # Remove empty target entries
        for target in targets_to_remove:
            del self.pending_immunity_queue[target]

