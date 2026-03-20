"""Queue processing service for log events.

This module handles all event processing from the log parser queue,
including damage tracking, immunity tracking, and attack tracking.
All logic is pure Python with no Tkinter dependencies.
"""

import queue
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Dict, List, Set

from ..models import StoreMutation
from ..parser import LogParser
from ..storage import DataStore
from .event_ingestion import EventIngestionEngine, IngestionResult
from .immunity_matcher import ImmunityMatcher


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
    """Process events from log parser queue."""

    def __init__(self, data_store: DataStore, parser: LogParser) -> None:
        self.data_store = data_store
        self.parser = parser
        self.ingestion_engine = EventIngestionEngine(
            parse_immunity=True,
            matcher_factory=ImmunityMatcher,
        )
        self.parsed_event_count = 0
        self.next_immunity_cleanup_event_count = 100

    @property
    def immunity_matcher(self) -> ImmunityMatcher | None:
        """Compatibility accessor for tests and debug views."""
        return self.ingestion_engine.immunity_matcher

    @property
    def damage_buffer(self) -> Dict[str, Dict]:
        """Compatibility/debug view of recent damage observations."""
        return self.ingestion_engine.damage_buffer

    @property
    def pending_immunity_queue(self) -> Dict[str, Dict[str, list]]:
        """Compatibility/debug view of unmatched immunity observations."""
        return self.ingestion_engine.pending_immunity_queue

    def process_queue(
        self,
        data_queue: queue.Queue,
        on_log_message: Callable[[str, str], None],
        debug_enabled: bool = False,
        max_events: int = 2000,
        max_time_ms: float | None = None,
    ) -> QueueDrainResult:
        """Process a bounded batch of queue events."""
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

                event_result = self._handle_event_batched(
                    data,
                    pending_mutations,
                    on_log_message,
                    debug_enabled,
                )

                if event_result:
                    if event_result.get("dps_updated"):
                        result.dps_updated = True
                    if event_result.get("target"):
                        result.targets_to_refresh.add(event_result["target"])
                    if event_result.get("immunity_target"):
                        result.immunity_targets.add(event_result["immunity_target"])
                    if event_result.get("damage_target"):
                        result.damage_targets.add(event_result["damage_target"])
                    if event_result.get("death_event"):
                        result.death_events.append(event_result["death_event"])
                    if event_result.get("character_identified"):
                        result.character_identity_events.append(event_result["character_identified"])

        except queue.Empty:
            pass

        if pending_mutations:
            try:
                self.data_store.apply_mutations(pending_mutations)
            except Exception as exc:
                on_log_message(f"Data store batch error: {exc}", "error")

        result.backlog_count = self._get_queue_size_hint(data_queue)
        result.has_backlog = result.backlog_count > 0
        result.pressure_state = self._classify_backpressure(
            backlog_count=result.backlog_count,
            queue_maxsize=getattr(data_queue, "maxsize", 0),
        )

        self.parsed_event_count += result.events_processed
        if (
            self.parser.parse_immunity
            and result.events_processed > 0
            and self.parsed_event_count >= self.next_immunity_cleanup_event_count
        ):
            self.cleanup_stale_immunities(max_age_seconds=5.0)
            while self.next_immunity_cleanup_event_count <= self.parsed_event_count:
                self.next_immunity_cleanup_event_count += 100
        elif not self.parser.parse_immunity and self.parsed_event_count >= self.next_immunity_cleanup_event_count:
            while self.next_immunity_cleanup_event_count <= self.parsed_event_count:
                self.next_immunity_cleanup_event_count += 100

        return result

    @staticmethod
    def _get_queue_size_hint(data_queue: queue.Queue) -> int:
        try:
            size = int(data_queue.qsize())
        except (AttributeError, NotImplementedError):
            return 0
        return max(size, 0)

    @staticmethod
    def _classify_backpressure(backlog_count: int, queue_maxsize: int) -> str:
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
        on_log_message: Callable[[str, str], None],
        debug_enabled: bool,
    ) -> Dict[str, Any]:
        self.ingestion_engine.parse_immunity = bool(self.parser.parse_immunity)
        had_pending_immunity_types: set[str] = set()
        if (
            debug_enabled
            and data.get("type") == "damage_dealt"
            and self.parser.parse_immunity
            and self.immunity_matcher is not None
        ):
            target = data.get("target")
            for damage_type in data.get("damage_types", {}):
                if self.immunity_matcher.has_pending_immunity(
                    target=str(target),
                    damage_type=str(damage_type),
                ):
                    had_pending_immunity_types.add(str(damage_type))
        event_result = self.ingestion_engine.consume(data)
        pending_mutations.extend(event_result.mutations)
        self._log_debug_event(
            data=data,
            event_result=event_result,
            had_pending_immunity_types=had_pending_immunity_types,
            on_log_message=on_log_message,
            debug_enabled=debug_enabled,
        )

        if not event_result.handled:
            event_type = data.get("type")
            message = data.get("message", "")
            if not message:
                message = f"Event: {event_type} - {data}"
            on_log_message(message, event_type)

        result: Dict[str, Any] = {}
        if event_result.dps_updated:
            result["dps_updated"] = True
        if event_result.target_to_refresh:
            result["target"] = event_result.target_to_refresh
        if event_result.immunity_target:
            result["immunity_target"] = event_result.immunity_target
        if event_result.damage_target:
            result["damage_target"] = event_result.damage_target
        if event_result.death_event:
            result["death_event"] = event_result.death_event
        if event_result.character_identified:
            result["character_identified"] = event_result.character_identified
        return result

    def _log_debug_event(
        self,
        *,
        data: Dict[str, Any],
        event_result: IngestionResult,
        had_pending_immunity_types: set[str],
        on_log_message: Callable[[str, str], None],
        debug_enabled: bool,
    ) -> None:
        if not debug_enabled:
            return

        event_type = data.get("type")
        if event_type == "damage_dealt":
            attacker = data.get("attacker", "")
            target = data.get("target")
            total_damage = int(data.get("total_damage", 0) or 0)
            if attacker:
                on_log_message(
                    f"DAMAGE: {attacker} vs {target} ({total_damage} damage)",
                    "debug",
                )
            if self.parser.parse_immunity and self.immunity_matcher is not None:
                matched_types = {
                    mutation.damage_type
                    for mutation in event_result.mutations
                    if mutation.kind == "immunity"
                }
                for damage_type in sorted(had_pending_immunity_types - matched_types):
                    on_log_message(f"Queue mismatched {target}/{damage_type}", "debug")
            return

        if event_type == "immunity":
            if not self.parser.parse_immunity:
                on_log_message(
                    f"Skipping dmg_absorbed event for {data.get('target')}/{data.get('damage_type')} "
                    "(parsing disabled)",
                    "debug",
                )
                return
            target = data.get("target")
            damage_type = data.get("damage_type")
            if any(mutation.kind == "immunity" for mutation in event_result.mutations):
                on_log_message(f"IMMUNITY: matched {target}/{damage_type}", "debug")
            else:
                on_log_message(f"IMMUNITY: queued {target}/{damage_type}", "debug")
            return

        if event_type in ("attack_hit", "attack_miss", "attack_hit_critical", "critical_hit"):
            attacker = data.get("attacker")
            target = data.get("target")
            if event_type in ("attack_hit_critical", "critical_hit"):
                outcome = "critical_hit"
            elif event_type == "attack_hit":
                outcome = "hit"
            else:
                outcome = "miss"
            on_log_message(f"ATTACK: {attacker} vs {target} ({outcome})", "debug")
            return

        if event_type == "epic_dodge":
            on_log_message(f"EPIC DODGE: {data.get('target')}", "debug")
            return

        if event_type == "save":
            target = data.get("target")
            save_type = data.get("save_type")
            bonus = data.get("bonus")
            on_log_message(
                f"SAVE: {target or 'Unknown'} ({str(save_type or 'Unknown').title()} {bonus or 0})",
                "debug",
            )

    def cleanup_stale_immunities(self, max_age_seconds: float = 5.0) -> None:
        """Remove pending observations older than max_age_seconds."""
        self.ingestion_engine.cleanup_stale_immunities(max_age_seconds=max_age_seconds)
