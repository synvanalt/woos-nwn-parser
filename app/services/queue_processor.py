"""Queue processing service for log events.

This module handles all event processing from the log parser queue,
including damage tracking, immunity tracking, and attack tracking.
All logic is pure Python with no Tkinter dependencies.
"""

import queue
from datetime import datetime
from typing import Dict, Callable, List, Any

from ..storage import DataStore
from ..parser import LogParser


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
        self.immunity_pct_cache: Dict[str, Dict[str, Any]] = {}
        self.parsed_event_count = 0

    def process_queue(
        self,
        data_queue: queue.Queue,
        on_log_message: Callable[[str, str], None],
        on_dps_updated: Callable[[], None],
        on_target_selected: Callable[[str], None],
        on_immunity_changed: Callable[[str], None],
        on_damage_dealt: Callable[[str], None] = None,
    ) -> None:
        """Process all events in queue and invoke callbacks for UI updates.

        Uses batching to reduce callback overhead - processes all events first,
        then triggers UI callbacks once at the end.

        Args:
            data_queue: Queue of events from LogDirectoryMonitor
            on_log_message: Callback for log messages (message, type)
            on_dps_updated: Callback when DPS data changes
            on_target_selected: Callback to refresh target details
            on_immunity_changed: Callback when immunity data changes
            on_damage_dealt: Callback when damage is dealt to a target
        """
        # Batch tracking - collect what needs updating
        dps_updated = False
        targets_to_refresh: set = set()
        immunity_targets: set = set()
        damage_targets: set = set()
        events_processed = 0

        try:
            while True:
                data = data_queue.get_nowait()
                events_processed += 1

                # Process event and track what needs UI update
                result = self._handle_event_batched(
                    data,
                    on_log_message,
                )

                if result:
                    if result.get('dps_updated'):
                        dps_updated = True
                    if result.get('target'):
                        targets_to_refresh.add(result['target'])
                    if result.get('immunity_target'):
                        immunity_targets.add(result['immunity_target'])
                    if result.get('damage_target'):
                        damage_targets.add(result['damage_target'])

        except queue.Empty:
            pass

        # Now trigger UI callbacks once (batched)
        if dps_updated:
            on_dps_updated()

        # Only refresh unique targets (deduplicated)
        for target in targets_to_refresh:
            on_target_selected(target)

        for target in immunity_targets:
            on_immunity_changed(target)

        if on_damage_dealt:
            for target in damage_targets:
                on_damage_dealt(target)

        # Periodic cleanup of stale immunity entries (every 100 events)
        self.parsed_event_count += events_processed
        if self.parsed_event_count % 100 == 0:
            self.cleanup_stale_immunities(max_age_seconds=5.0)

    def _handle_event_batched(
        self,
        data: Dict[str, Any],
        on_log_message: Callable,
    ) -> Dict[str, Any]:
        """Route event to appropriate handler and return what needs UI update.

        Args:
            data: Event data from queue
            on_log_message: Callback for logging

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
            result = self._handle_damage_dealt_batched(data, on_log_message)
        elif event_type == 'immunity':
            result = self._handle_immunity_batched(data, on_log_message)
        elif event_type in (
            'attack_hit',
            'attack_miss',
            'attack_hit_critical',
            'critical_hit',
        ):
            result = self._handle_attack_batched(data, on_log_message)
        else:
            # Log other message types
            on_log_message(data.get('message', ''), event_type)

        return result

    def _handle_damage_dealt_batched(
        self,
        data: Dict[str, Any],
        on_log_message: Callable,
    ) -> Dict[str, Any]:
        """Handle damage_dealt event (batched version - no immediate callbacks).

        Args:
            data: Event data containing damage information
            on_log_message: Callback for logging

        Returns:
            Dict indicating what needs UI update
        """
        result = {'dps_updated': False, 'damage_target': None}

        try:
            attacker = data.get('attacker')
            if attacker:
                total_damage = data.get('total_damage', 0)
                timestamp = data.get('timestamp', datetime.now())
                damage_types = data.get('damage_types', {})

                # Update DPS tracking
                self.data_store.update_dps_data(
                    attacker, total_damage, timestamp, damage_types
                )
                on_log_message(
                    f"DPS update: {attacker} dealt {total_damage} damage", 'debug'
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
                self.data_store.insert_damage_event(
                    target,
                    dt,
                    0,
                    amount_int,
                    data.get('attacker', ''),
                    data['timestamp'],
                )
        except Exception as e:
            on_log_message(f"Data store error on damage_dealt: {e}", 'error')

        # Process queued immunities (internal, returns if any were processed)
        immunity_processed = self._process_queued_immunities_batched(target, data, on_log_message)

        result['damage_target'] = target
        if immunity_processed:
            result['immunity_target'] = target
        return result

    def _handle_immunity_batched(
        self,
        data: Dict[str, Any],
        on_log_message: Callable,
    ) -> Dict[str, Any]:
        """Handle immunity event (batched version).

        Args:
            data: Event data containing immunity information
            on_log_message: Callback for logging

        Returns:
            Dict indicating what needs UI update
        """
        result = {}

        if not self.parser.parse_immunity:
            on_log_message(
                f"Skipping immunity event for {data.get('target')}/{data.get('damage_type')} "
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
                immunity = data.get('immunity_points', 0)
                damage_dealt = self.damage_buffer[target]['damage_types'].get(
                    damage_type, 0
                )

                try:
                    inferred_amount = int(damage_dealt or 0)
                    self.data_store.record_immunity(
                        target, damage_type, int(immunity or 0), inferred_amount
                    )
                    on_log_message(
                        f"immunity_event: target={target}, type={damage_type}, "
                        f"inferred_amount={inferred_amount}, immunity={immunity}",
                        'debug',
                    )
                except Exception as e:
                    on_log_message(f"Data store error: {e}", 'error')

                result['target'] = target
            else:
                # Queue immunity for later
                self._queue_immunity(target, damage_type, data)

        return result

    def _handle_attack_batched(
        self,
        data: Dict[str, Any],
        on_log_message: Callable,
    ) -> Dict[str, Any]:
        """Handle attack_hit, attack_miss, or critical_hit event (batched version).

        Args:
            data: Event data containing attack information
            on_log_message: Callback for logging

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

        self.data_store.insert_attack_event(
            attacker,
            target,
            event_type,
            data.get('roll'),
            data.get('bonus'),
            data.get('total'),
        )

        on_log_message(
            f"Attack: {attacker} vs {target} ({event_type})", 'debug'
        )

        return {'target': target}

    def _process_queued_immunities_batched(
        self,
        target: str,
        damage_event: Dict[str, Any],
        on_log_message: Callable,
    ) -> bool:
        """Process any immunities waiting for this damage event (no callbacks).

        Args:
            target: Target name
            damage_event: The damage event data
            on_log_message: Callback for logging

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

                if time_diff <= 1:  # Allow 1 second difference
                    try:
                        inferred_amount = int(damage_dealt or 0)
                        self.data_store.record_immunity(
                            target, damage_type, immunity, inferred_amount
                        )
                        on_log_message(
                            f"Processed queued immunity: target={target}, type={damage_type}",
                            'debug',
                        )
                        processed_any = True
                    except Exception as e:
                        on_log_message(f"Data store error processing queued immunity: {e}", 'error')
                else:
                    on_log_message(
                        f"! Immunity time mismatch for {target}/{damage_type}: {time_diff}s apart",
                        'debug',
                    )

            # Clear processed queue
            del self.pending_immunity_queue[target][damage_type]

        # Clean up empty target entries
        if not self.pending_immunity_queue[target]:
            del self.pending_immunity_queue[target]

        return processed_any

    # Keep original methods for backward compatibility
    def _handle_event(
        self,
        data: Dict[str, Any],
        on_log_message: Callable,
        on_dps_updated: Callable,
        on_target_selected: Callable,
        on_immunity_changed: Callable,
        on_damage_dealt: Callable = None,
    ) -> None:
        """Route event to appropriate handler.

        Args:
            data: Event data from queue
            on_log_message: Callback for logging
            on_dps_updated: Callback for DPS updates
            on_target_selected: Callback for target selection
            on_immunity_changed: Callback for immunity changes
            on_damage_dealt: Callback for damage dealt events
        """
        event_type = data.get('type')

        if event_type == 'damage_dealt':
            self._handle_damage_dealt(
                data, on_log_message, on_dps_updated, on_immunity_changed, on_damage_dealt
            )
        elif event_type == 'immunity':
            self._handle_immunity(data, on_log_message, on_target_selected)
        elif event_type in (
            'attack_hit',
            'attack_miss',
            'attack_hit_critical',
            'critical_hit',
        ):
            self._handle_attack(data, on_log_message, on_target_selected)
        else:
            # Log other message types
            on_log_message(data.get('message', ''), event_type)

    def _handle_damage_dealt(
        self,
        data: Dict[str, Any],
        on_log_message: Callable,
        on_dps_updated: Callable,
        on_immunity_changed: Callable,
        on_damage_dealt: Callable = None,
    ) -> None:
        """Handle damage_dealt event.

        Args:
            data: Event data containing damage information
            on_log_message: Callback for logging
            on_dps_updated: Callback when DPS changes
            on_immunity_changed: Callback when immunity matches
            on_damage_dealt: Callback when damage is dealt to a target
        """
        try:
            attacker = data.get('attacker')
            if attacker:
                total_damage = data.get('total_damage', 0)
                timestamp = data.get('timestamp', datetime.now())
                damage_types = data.get('damage_types', {})

                # Update DPS tracking
                self.data_store.update_dps_data(
                    attacker, total_damage, timestamp, damage_types
                )
                on_log_message(
                    f"DPS update: {attacker} dealt {total_damage} damage", 'debug'
                )
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
                self.data_store.insert_damage_event(
                    target,
                    dt,
                    0,
                    amount_int,
                    data.get('attacker', ''),
                    data['timestamp'],
                )
        except Exception as e:
            on_log_message(f"Data store error on damage_dealt: {e}", 'error')

        # Process queued immunities
        self._process_queued_immunities(
            target, data, on_log_message, on_immunity_changed
        )

        # Signal DPS update
        on_dps_updated()

        # Signal damage dealt event
        if on_damage_dealt:
            on_damage_dealt(target)

    def _handle_immunity(
        self,
        data: Dict[str, Any],
        on_log_message: Callable,
        on_target_selected: Callable,
    ) -> None:
        """Handle immunity event.

        Args:
            data: Event data containing immunity information
            on_log_message: Callback for logging
            on_target_selected: Callback when target needs refresh
        """
        if not self.parser.parse_immunity:
            on_log_message(
                f"Skipping immunity event for {data.get('target')}/{data.get('damage_type')} "
                "(parsing disabled)",
                'debug',
            )
            return

        target = data['target']
        damage_type = data.get('damage_type')

        if damage_type:
            # Check if recent damage exists
            if (
                target in self.damage_buffer
                and damage_type in self.damage_buffer[target].get('damage_types', {})
            ):
                immunity = data.get('immunity_points', 0)
                damage_dealt = self.damage_buffer[target]['damage_types'].get(
                    damage_type, 0
                )

                try:
                    inferred_amount = int(damage_dealt or 0)
                    self.data_store.record_immunity(
                        target, damage_type, int(immunity or 0), inferred_amount
                    )
                    on_log_message(
                        f"immunity_event: target={target}, type={damage_type}, "
                        f"inferred_amount={inferred_amount}, immunity={immunity}",
                        'debug',
                    )
                except Exception as e:
                    on_log_message(f"Data store error: {e}", 'error')

                # Signal UI update
                on_target_selected(target)
            else:
                # Queue immunity for later
                self._queue_immunity(target, damage_type, data)

    def _handle_attack(
        self,
        data: Dict[str, Any],
        on_log_message: Callable,
        on_target_selected: Callable,
    ) -> None:
        """Handle attack_hit, attack_miss, or critical_hit event.

        Args:
            data: Event data containing attack information
            on_log_message: Callback for logging
            on_target_selected: Callback when target needs refresh
        """
        attacker = data.get('attacker')
        target = data.get('target')

        if data['type'] in ('attack_hit_critical', 'critical_hit'):
            event_type = 'critical_hit'
        elif data['type'] == 'attack_hit':
            event_type = 'hit'
        else:
            event_type = 'miss'

        self.data_store.insert_attack_event(
            attacker,
            target,
            event_type,
            data.get('roll'),
            data.get('bonus'),
            data.get('total'),
        )

        on_log_message(
            f"Attack: {attacker} vs {target} ({event_type})", 'debug'
        )
        on_target_selected(target)

    def _process_queued_immunities(
        self,
        target: str,
        damage_event: Dict[str, Any],
        on_log_message: Callable,
        on_immunity_changed: Callable,
    ) -> None:
        """Process any immunities waiting for this damage event.

        Args:
            target: Target name
            damage_event: The damage event data
            on_log_message: Callback for logging
            on_immunity_changed: Callback when immunity is processed
        """
        if target not in self.pending_immunity_queue:
            return

        for damage_type in list(self.pending_immunity_queue[target].keys()):
            if damage_type not in damage_event['damage_types']:
                continue

            for queued_immunity in self.pending_immunity_queue[target][
                damage_type
            ]:
                immunity = queued_immunity['immunity']
                immunity_timestamp = queued_immunity['timestamp']
                damage_dealt = damage_event['damage_types'][damage_type]
                damage_timestamp = damage_event['timestamp']

                time_diff = abs(
                    (damage_timestamp - immunity_timestamp).total_seconds()
                )

                if time_diff <= 1:  # Allow 1 second difference
                    try:
                        inferred_amount = int(damage_dealt or 0)
                        self.data_store.record_immunity(
                            target, damage_type, immunity, inferred_amount
                        )
                        on_log_message(
                            f"✓ Processing queued immunity: {target}/{damage_type}: "
                            f"{immunity} pts (time diff: {time_diff}s)",
                            'debug',
                        )
                        on_immunity_changed(target)
                    except Exception as e:
                        on_log_message(
                            f"Data store error on queued immunity: {e}",
                            'error',
                        )
                else:
                    on_log_message(
                        f"! Immunity time mismatch for {target}/{damage_type}: {time_diff}s apart",
                        'debug',
                    )

            # Clear processed queue
            del self.pending_immunity_queue[target][damage_type]

        # Clean up empty entries
        if not self.pending_immunity_queue[target]:
            del self.pending_immunity_queue[target]

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

