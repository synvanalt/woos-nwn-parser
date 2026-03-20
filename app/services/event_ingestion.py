"""Shared parsed-event ingestion logic for live and import workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from ..models import (
    AttackMutation,
    DamageMutation,
    EpicDodgeMutation,
    SaveMutation,
    StoreMutation,
)
from ..parsed_events import (
    AttackCriticalHitEvent,
    AttackHitEvent,
    AttackMissEvent,
    coerce_parsed_event,
    DamageDealtEvent,
    DeathCharacterIdentifiedEvent,
    DeathSnippetEvent,
    EpicDodgeEvent,
    ImmunityObservedEvent,
    ParsedEvent,
    SaveObservedEvent,
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
    death_event: DeathSnippetEvent | None = None
    character_identified: DeathCharacterIdentifiedEvent | None = None


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

    def consume(self, parsed_event: ParsedEvent | dict[str, object]) -> IngestionResult:
        """Consume one parsed event and return normalized outputs."""
        parsed_event = coerce_parsed_event(parsed_event)
        if isinstance(parsed_event, DamageDealtEvent):
            return self._consume_damage(parsed_event)
        if isinstance(parsed_event, ImmunityObservedEvent):
            return self._consume_immunity(parsed_event)
        if isinstance(parsed_event, (AttackHitEvent, AttackCriticalHitEvent, AttackMissEvent)):
            return self._consume_attack(parsed_event)
        if isinstance(parsed_event, EpicDodgeEvent):
            return self._consume_epic_dodge(parsed_event)
        if isinstance(parsed_event, SaveObservedEvent):
            return self._consume_save(parsed_event)
        if isinstance(parsed_event, DeathSnippetEvent):
            return IngestionResult(handled=True, death_event=parsed_event)
        if isinstance(parsed_event, DeathCharacterIdentifiedEvent):
            return IngestionResult(handled=True, character_identified=parsed_event)

        return IngestionResult(handled=False)

    def cleanup_stale_immunities(self, max_age_seconds: float = 5.0) -> None:
        """Remove stale immunity observations when matcher support is enabled."""
        if self._matcher is None:
            return
        self._matcher.cleanup_stale_observations(max_age_seconds=max_age_seconds)

    def _event_line_number(self, parsed_event: ParsedEvent) -> int:
        line_number = parsed_event.line_number
        if line_number is not None:
            return int(line_number)
        self._synthetic_line_number += 1
        return self._synthetic_line_number

    def _consume_damage(self, parsed_event: DamageDealtEvent) -> IngestionResult:
        result = IngestionResult(handled=True)
        target = parsed_event.target
        attacker = parsed_event.attacker
        timestamp = parsed_event.timestamp
        total_damage = int(parsed_event.total_damage)
        damage_types = parsed_event.damage_types or {}
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

    def _consume_immunity(self, parsed_event: ImmunityObservedEvent) -> IngestionResult:
        result = IngestionResult(handled=True)
        if not self.parse_immunity or self._matcher is None:
            return result

        target = parsed_event.target
        damage_type = parsed_event.damage_type
        if not damage_type:
            return result

        matched_mutations = self._matcher.queue_immunity(
            target=target,
            damage_type=str(damage_type),
            immunity_points=int(parsed_event.immunity_points),
            timestamp=parsed_event.timestamp,
            line_number=self._event_line_number(parsed_event),
        )
        result.mutations.extend(matched_mutations)
        if matched_mutations:
            result.target_to_refresh = target
        return result

    def _consume_attack(
        self,
        parsed_event: AttackHitEvent | AttackCriticalHitEvent | AttackMissEvent,
    ) -> IngestionResult:
        if isinstance(parsed_event, AttackCriticalHitEvent):
            outcome = "critical_hit"
        elif isinstance(parsed_event, AttackHitEvent):
            outcome = "hit"
        else:
            outcome = "miss"

        target = parsed_event.target
        return IngestionResult(
            handled=True,
            target_to_refresh=target,
            mutations=[
                AttackMutation(
                    attacker=parsed_event.attacker,
                    target=target,
                    outcome=outcome,
                    roll=parsed_event.roll,
                    bonus=parsed_event.bonus,
                    total=parsed_event.total,
                    was_nat1=bool(getattr(parsed_event, "was_nat1", False)),
                    was_nat20=bool(getattr(parsed_event, "was_nat20", False)),
                    is_concealment=bool(parsed_event.is_concealment),
                )
            ],
        )

    def _consume_epic_dodge(self, parsed_event: EpicDodgeEvent) -> IngestionResult:
        target = parsed_event.target
        result = IngestionResult(handled=True, target_to_refresh=target)
        if target:
            result.mutations.append(EpicDodgeMutation(target=target))
        return result

    def _consume_save(self, parsed_event: SaveObservedEvent) -> IngestionResult:
        target = parsed_event.target
        save_type = parsed_event.save_type
        bonus = parsed_event.bonus
        result = IngestionResult(handled=True, target_to_refresh=target)
        if target and save_type and bonus is not None:
            result.mutations.append(
                SaveMutation(target=target, save_key=str(save_type), bonus=int(bonus))
            )
        return result
