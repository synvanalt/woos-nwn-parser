"""Shared parsed-event ingestion logic for live and import workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ..models import (
    AttackMutation,
    DamageMutation,
    EpicDodgeMutation,
    SaveMutation,
    StoreMutation,
)
from .immunity_matcher import ImmunityMatcher


MatcherFactory = Callable[[], ImmunityMatcher]


class _DisabledImmunityMatcher:
    """Compatibility object for disabled-immunity workflows."""

    def __init__(self) -> None:
        self.latest_damage_by_target: dict[str, dict[str, object]] = {}
        self._pending_damage: dict[str, dict[str, object]] = {}

    @property
    def pending_immunity_queue(self) -> dict[str, dict[str, list[dict[str, object]]]]:
        return {}

    def cleanup_stale_observations(self, *, max_age_seconds: float = 5.0) -> None:
        return

    def has_pending_immunity(self, *, target: str, damage_type: str) -> bool:
        return False


@dataclass(slots=True)
class IngestionResult:
    """Normalized result of consuming one parsed event."""

    handled: bool = False
    mutations: list[StoreMutation] = field(default_factory=list)
    target_to_refresh: str | None = None
    immunity_target: str | None = None
    damage_target: str | None = None
    dps_updated: bool = False
    death_event: dict[str, Any] | None = None
    character_identified: dict[str, Any] | None = None


class EventIngestionEngine:
    """Convert parsed parser events into store mutations and side events."""

    def __init__(
        self,
        *,
        parse_immunity: bool,
        matcher_factory: MatcherFactory = ImmunityMatcher,
    ) -> None:
        self.parse_immunity = bool(parse_immunity)
        self._matcher = matcher_factory() if self.parse_immunity else None
        self._disabled_matcher = _DisabledImmunityMatcher()
        self._synthetic_line_number = 0

    @property
    def immunity_matcher(self) -> ImmunityMatcher | _DisabledImmunityMatcher:
        """Expose matcher for compatibility-oriented callers/tests."""
        return self._matcher if self._matcher is not None else self._disabled_matcher

    @property
    def damage_buffer(self) -> dict[str, dict[str, object]]:
        """Compatibility/debug view of recent damage observations."""
        if self._matcher is None:
            return self._disabled_matcher.latest_damage_by_target
        return self._matcher.latest_damage_by_target

    @property
    def pending_immunity_queue(self) -> dict[str, dict[str, list[dict[str, object]]]]:
        """Compatibility/debug view of unmatched immunity observations."""
        if self._matcher is None:
            return self._disabled_matcher.pending_immunity_queue
        return self._matcher.pending_immunity_queue

    def consume(self, parsed_event: dict[str, Any]) -> IngestionResult:
        """Consume one parsed event and return normalized outputs."""
        event_type = parsed_event.get("type")

        if event_type == "damage_dealt":
            return self._consume_damage(parsed_event)
        if event_type == "immunity":
            return self._consume_immunity(parsed_event)
        if event_type in ("attack_hit", "attack_miss", "attack_hit_critical", "critical_hit"):
            return self._consume_attack(parsed_event)
        if event_type == "epic_dodge":
            return self._consume_epic_dodge(parsed_event)
        if event_type == "save":
            return self._consume_save(parsed_event)
        if event_type == "death_snippet":
            return IngestionResult(handled=True, death_event=parsed_event)
        if event_type == "death_character_identified":
            return IngestionResult(handled=True, character_identified=parsed_event)

        return IngestionResult(handled=False)

    def cleanup_stale_immunities(self, max_age_seconds: float = 5.0) -> None:
        """Remove stale immunity observations when matcher support is enabled."""
        if self._matcher is None:
            return
        self._matcher.cleanup_stale_observations(max_age_seconds=max_age_seconds)

    def _event_line_number(self, parsed_event: dict[str, Any]) -> int:
        line_number = parsed_event.get("line_number")
        if line_number is not None:
            return int(line_number)
        self._synthetic_line_number += 1
        return self._synthetic_line_number

    def _consume_damage(self, parsed_event: dict[str, Any]) -> IngestionResult:
        result = IngestionResult(handled=True)
        target = parsed_event["target"]
        attacker = parsed_event.get("attacker", "")
        timestamp = parsed_event.get("timestamp", datetime.now())
        total_damage = int(parsed_event.get("total_damage", 0) or 0)
        damage_types = parsed_event.get("damage_types", {})
        line_number = self._event_line_number(parsed_event)

        if attacker:
            result.mutations.append(
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
            result.dps_updated = True

        for damage_type, amount in damage_types.items():
            result.mutations.append(
                DamageMutation(
                    target=target,
                    damage_type=damage_type,
                    immunity_absorbed=0,
                    total_damage=amount,
                    attacker=attacker,
                    timestamp=timestamp,
                )
            )

        if self._matcher is not None:
            self._matcher.latest_damage_by_target[target] = {
                "damage_types": damage_types,
                "timestamp": timestamp,
                "attacker": attacker,
                "line_number": line_number,
            }
        if self.parse_immunity and self._matcher is not None:
            matched_mutations = self._matcher.queue_damage_event(
                target=target,
                damage_types=damage_types,
                timestamp=timestamp,
                line_number=line_number,
                attacker=attacker,
            )
            result.mutations.extend(matched_mutations)
            if matched_mutations:
                result.immunity_target = target

        result.target_to_refresh = target
        result.damage_target = target
        return result

    def _consume_immunity(self, parsed_event: dict[str, Any]) -> IngestionResult:
        result = IngestionResult(handled=True)
        if not self.parse_immunity or self._matcher is None:
            return result

        target = parsed_event["target"]
        damage_type = parsed_event.get("damage_type")
        if not damage_type:
            return result

        matched_mutations = self._matcher.queue_immunity(
            target=target,
            damage_type=str(damage_type),
            immunity_points=int(parsed_event.get("immunity_points", 0) or 0),
            timestamp=parsed_event.get("timestamp", datetime.now()),
            line_number=self._event_line_number(parsed_event),
        )
        result.mutations.extend(matched_mutations)
        if matched_mutations:
            result.target_to_refresh = target
        return result

    def _consume_attack(self, parsed_event: dict[str, Any]) -> IngestionResult:
        if parsed_event["type"] in ("attack_hit_critical", "critical_hit"):
            outcome = "critical_hit"
        elif parsed_event["type"] == "attack_hit":
            outcome = "hit"
        else:
            outcome = "miss"

        target = parsed_event.get("target")
        return IngestionResult(
            handled=True,
            target_to_refresh=target,
            mutations=[
                AttackMutation(
                    attacker=parsed_event.get("attacker"),
                    target=target,
                    outcome=outcome,
                    roll=parsed_event.get("roll"),
                    bonus=parsed_event.get("bonus"),
                    total=parsed_event.get("total"),
                    was_nat1=bool(parsed_event.get("was_nat1", False)),
                    was_nat20=bool(parsed_event.get("was_nat20", False)),
                    is_concealment=bool(parsed_event.get("is_concealment", False)),
                )
            ],
        )

    def _consume_epic_dodge(self, parsed_event: dict[str, Any]) -> IngestionResult:
        target = parsed_event.get("target")
        result = IngestionResult(handled=True, target_to_refresh=target)
        if target:
            result.mutations.append(EpicDodgeMutation(target=target))
        return result

    def _consume_save(self, parsed_event: dict[str, Any]) -> IngestionResult:
        target = parsed_event.get("target")
        save_type = parsed_event.get("save_type")
        bonus = parsed_event.get("bonus")
        result = IngestionResult(handled=True, target_to_refresh=target)
        if target and save_type and bonus is not None:
            result.mutations.append(
                SaveMutation(target=target, save_key=str(save_type), bonus=int(bonus))
            )
        return result
