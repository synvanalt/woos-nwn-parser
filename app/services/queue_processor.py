"""Queue processing service for log events.

This module handles all event processing from the log parser queue,
including damage tracking, immunity tracking, and attack tracking.
All logic is pure Python with no Tkinter dependencies.
"""

import queue
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any, Callable, Dict, List, Set

from ..models import (
    AttackMutation,
    DamageMutation,
    EpicDodgeMutation,
    SaveMutation,
    StoreMutation,
)
from ..parser import LogParser
from ..storage import DataStore
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
        self.immunity_matcher = ImmunityMatcher()
        self.parsed_event_count = 0
        self.next_immunity_cleanup_event_count = 100
        self._synthetic_line_number = 0

    @property
    def damage_buffer(self) -> Dict[str, Dict]:
        """Compatibility/debug view of recent damage observations."""
        return self.immunity_matcher.latest_damage_by_target

    @property
    def pending_immunity_queue(self) -> Dict[str, Dict[str, list]]:
        """Compatibility/debug view of unmatched immunity observations."""
        return self.immunity_matcher.pending_immunity_queue

    def _get_event_line_number(self, data: Dict[str, Any]) -> int:
        line_number = data.get("line_number")
        if line_number is not None:
            return int(line_number)
        self._synthetic_line_number += 1
        return self._synthetic_line_number

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
        event_type = data.get("type")
        result: Dict[str, Any] = {}

        if event_type == "damage_dealt":
            result = self._handle_damage_dealt_batched(
                data,
                pending_mutations,
                on_log_message,
                debug_enabled,
            )
        elif event_type == "immunity":
            result = self._handle_immunity_batched(
                data,
                pending_mutations,
                on_log_message,
                debug_enabled,
            )
        elif event_type in ("attack_hit", "attack_miss", "attack_hit_critical", "critical_hit"):
            result = self._handle_attack_batched(
                data,
                pending_mutations,
                on_log_message,
                debug_enabled,
            )
        elif event_type == "epic_dodge":
            target = data.get("target")
            if target:
                pending_mutations.append(EpicDodgeMutation(target=target))
                result["target"] = target
            if debug_enabled:
                on_log_message(f"EPIC DODGE: {target}", "debug")
        elif event_type == "death_snippet":
            result["death_event"] = data
        elif event_type == "death_character_identified":
            result["character_identified"] = data
        elif event_type == "save":
            target = data.get("target")
            save_type = data.get("save_type")
            bonus = data.get("bonus")
            if target and save_type and bonus is not None:
                pending_mutations.append(
                    SaveMutation(target=target, save_key=str(save_type), bonus=int(bonus))
                )
                result["target"] = target
            if debug_enabled:
                on_log_message(
                    f"SAVE: {target or 'Unknown'} ({str(save_type or 'Unknown').title()} {bonus or 0})",
                    "debug",
                )
        else:
            message = data.get("message", "")
            if not message:
                message = f"Event: {event_type} - {data}"
            on_log_message(message, event_type)

        return result

    def _handle_damage_dealt_batched(
        self,
        data: Dict[str, Any],
        pending_mutations: List[StoreMutation],
        on_log_message: Callable[[str, str], None],
        debug_enabled: bool,
    ) -> Dict[str, Any]:
        result = {"dps_updated": False, "damage_target": None}
        target = data["target"]
        attacker = data.get("attacker", "")
        timestamp = data.get("timestamp", datetime.now())
        total_damage = int(data.get("total_damage", 0) or 0)
        damage_types = data.get("damage_types", {})

        try:
            if attacker:
                pending_mutations.append(
                    DamageMutation(
                        target=target,
                        damage_type="",
                        total_damage=total_damage,
                        attacker=attacker,
                        timestamp=timestamp,
                        count_for_dps=True,
                        damage_types=damage_types,
                    )
                )
                if debug_enabled:
                    on_log_message(
                        f"DAMAGE: {attacker} vs {target} ({total_damage} damage)",
                        "debug",
                    )
                result["dps_updated"] = True
        except Exception as exc:
            on_log_message(f"DPS tracking error: {exc}", "error")

        line_number = self._get_event_line_number(data)
        self.immunity_matcher.latest_damage_by_target[target] = {
            "damage_types": damage_types,
            "timestamp": timestamp,
            "attacker": attacker,
            "line_number": line_number,
        }
        had_pending_immunity_types = set()
        if debug_enabled:
            had_pending_immunity_types = {
                damage_type
                for damage_type in damage_types
                if self.immunity_matcher.has_pending_immunity(
                    target=target,
                    damage_type=str(damage_type),
                )
            }

        try:
            for damage_type, amount in damage_types.items():
                pending_mutations.append(
                    DamageMutation(
                        target=target,
                        damage_type=damage_type,
                        immunity_absorbed=0,
                        total_damage=amount,
                        attacker=attacker,
                        timestamp=timestamp,
                    )
                )
        except Exception as exc:
            on_log_message(f"Data store error on damage_dealt: {exc}", "error")

        matched_mutations = []
        if self.parser.parse_immunity:
            matched_mutations = self.immunity_matcher.queue_damage_event(
                target=target,
                damage_types=damage_types,
                timestamp=timestamp,
                line_number=line_number,
                attacker=attacker,
            )
            pending_mutations.extend(matched_mutations)

        if debug_enabled:
            matched_types = {mutation.damage_type for mutation in matched_mutations}
            for damage_type in sorted(had_pending_immunity_types - matched_types):
                on_log_message(
                    f"Queue mismatched {target}/{damage_type}",
                    "debug",
                )

        result["damage_target"] = target
        if matched_mutations:
            result["immunity_target"] = target
        return result

    def _handle_immunity_batched(
        self,
        data: Dict[str, Any],
        pending_mutations: List[StoreMutation],
        on_log_message: Callable[[str, str], None],
        debug_enabled: bool,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        if not self.parser.parse_immunity:
            if debug_enabled:
                on_log_message(
                    f"Skipping dmg_absorbed event for {data.get('target')}/{data.get('damage_type')} "
                    "(parsing disabled)",
                    "debug",
                )
            return result

        target = data["target"]
        damage_type = data.get("damage_type")
        if not damage_type:
            return result

        matched_mutations = self.immunity_matcher.queue_immunity(
            target=target,
            damage_type=str(damage_type),
            immunity_points=int(data.get("immunity_points", 0) or 0),
            timestamp=data.get("timestamp", datetime.now()),
            line_number=self._get_event_line_number(data),
        )
        pending_mutations.extend(matched_mutations)

        if matched_mutations:
            if debug_enabled:
                on_log_message(f"IMMUNITY: matched {target}/{damage_type}", "debug")
            result["target"] = target
        elif debug_enabled:
            on_log_message(f"IMMUNITY: queued {target}/{damage_type}", "debug")

        return result

    def _handle_attack_batched(
        self,
        data: Dict[str, Any],
        pending_mutations: List[StoreMutation],
        on_log_message: Callable[[str, str], None],
        debug_enabled: bool,
    ) -> Dict[str, Any]:
        attacker = data.get("attacker")
        target = data.get("target")

        if data["type"] in ("attack_hit_critical", "critical_hit"):
            event_type = "critical_hit"
        elif data["type"] == "attack_hit":
            event_type = "hit"
        else:
            event_type = "miss"

        pending_mutations.append(
            AttackMutation(
                attacker=attacker,
                target=target,
                outcome=event_type,
                roll=data.get("roll"),
                bonus=data.get("bonus"),
                total=data.get("total"),
                was_nat1=bool(data.get("was_nat1", False)),
                was_nat20=bool(data.get("was_nat20", False)),
                is_concealment=bool(data.get("is_concealment", False)),
            )
        )

        if debug_enabled:
            on_log_message(f"ATTACK: {attacker} vs {target} ({event_type})", "debug")

        return {"target": target}

    def cleanup_stale_immunities(self, max_age_seconds: float = 5.0) -> None:
        """Remove pending observations older than max_age_seconds."""
        self.immunity_matcher.cleanup_stale_observations(max_age_seconds=max_age_seconds)
