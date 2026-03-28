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
        self._matcher_factory = matcher_factory
        self._parse_immunity = False
        self._matcher: ImmunityMatcher | None = None
        self.parse_immunity = bool(parse_immunity)
        self._synthetic_line_number = 0

    @property
    def parse_immunity(self) -> bool:
        return self._parse_immunity

    @parse_immunity.setter
    def parse_immunity(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self._parse_immunity:
            return
        self._parse_immunity = enabled
        if enabled:
            self._matcher = self._matcher_factory()
        else:
            self._matcher = None

    def consume(self, parsed_event: ParsedEvent) -> IngestionResult:
        """Consume one parsed event and return normalized outputs."""
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

    def append_import_mutations(
        self,
        parsed_event: ParsedEvent,
        mutations: list[StoreMutation],
    ) -> bool:
        """Append only import-relevant mutations without wrapper allocation."""
        if isinstance(parsed_event, DamageDealtEvent):
            self._append_damage_mutations(parsed_event, mutations)
            return True
        if isinstance(parsed_event, ImmunityObservedEvent):
            self._append_immunity_mutations(parsed_event, mutations)
            return True
        if isinstance(parsed_event, (AttackHitEvent, AttackCriticalHitEvent, AttackMissEvent)):
            mutations.append(self._build_attack_mutation(parsed_event))
            return True
        if isinstance(parsed_event, EpicDodgeEvent):
            if parsed_event.target:
                mutations.append(EpicDodgeMutation(target=parsed_event.target))
            return True
        if isinstance(parsed_event, SaveObservedEvent):
            if parsed_event.target and parsed_event.save_type and parsed_event.bonus is not None:
                mutations.append(
                    SaveMutation(
                        target=parsed_event.target,
                        save_key=str(parsed_event.save_type),
                        bonus=int(parsed_event.bonus),
                    )
                )
            return True
        if isinstance(parsed_event, (DeathSnippetEvent, DeathCharacterIdentifiedEvent)):
            return True
        return False

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
        result.dps_updated, matched_immunity = self._append_damage_mutations(parsed_event, result.mutations)
        target = parsed_event.target
        if matched_immunity:
            result.immunity_target = target
        result.target_to_refresh = target
        result.damage_target = target
        return result

    def _append_damage_mutations(
        self,
        parsed_event: DamageDealtEvent,
        mutations: list[StoreMutation],
    ) -> tuple[bool, bool]:
        target = parsed_event.target
        attacker = parsed_event.attacker
        timestamp = parsed_event.timestamp
        total_damage = int(parsed_event.total_damage)
        damage_types = parsed_event.damage_types or {}
        line_number = self._event_line_number(parsed_event)

        dps_updated = False
        matched_immunity = False
        if attacker:
            mutations.append(
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
            dps_updated = True

        for damage_type, amount in damage_types.items():
            mutations.append(
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
            mutations.extend(matched_mutations)
            matched_immunity = bool(matched_mutations)
        return dps_updated, matched_immunity

    def _consume_immunity(self, parsed_event: ImmunityObservedEvent) -> IngestionResult:
        result = IngestionResult(handled=True)
        target = parsed_event.target
        before_count = len(result.mutations)
        self._append_immunity_mutations(parsed_event, result.mutations)
        if len(result.mutations) > before_count:
            result.target_to_refresh = target
        return result

    def _append_immunity_mutations(
        self,
        parsed_event: ImmunityObservedEvent,
        mutations: list[StoreMutation],
    ) -> None:
        if not self.parse_immunity or self._matcher is None:
            return

        target = parsed_event.target
        damage_type = parsed_event.damage_type
        if not damage_type:
            return

        mutations.extend(
            self._matcher.queue_immunity(
                target=target,
                damage_type=str(damage_type),
                immunity_points=int(parsed_event.immunity_points),
                timestamp=parsed_event.timestamp,
                line_number=self._event_line_number(parsed_event),
            )
        )

    def _consume_attack(
        self,
        parsed_event: AttackHitEvent | AttackCriticalHitEvent | AttackMissEvent,
    ) -> IngestionResult:
        target = parsed_event.target
        return IngestionResult(
            handled=True,
            target_to_refresh=target,
            mutations=[self._build_attack_mutation(parsed_event)],
        )

    def _build_attack_mutation(
        self,
        parsed_event: AttackHitEvent | AttackCriticalHitEvent | AttackMissEvent,
    ) -> AttackMutation:
        if isinstance(parsed_event, AttackCriticalHitEvent):
            outcome = "critical_hit"
        elif isinstance(parsed_event, AttackHitEvent):
            outcome = "hit"
        else:
            outcome = "miss"

        return AttackMutation(
            attacker=parsed_event.attacker,
            target=parsed_event.target,
            outcome=outcome,
            roll=parsed_event.roll,
            bonus=parsed_event.bonus,
            total=parsed_event.total,
            was_nat1=bool(parsed_event.was_nat1) if isinstance(parsed_event, AttackMissEvent) else False,
            was_nat20=bool(parsed_event.was_nat20)
            if isinstance(parsed_event, (AttackHitEvent, AttackCriticalHitEvent))
            else False,
            is_concealment=bool(parsed_event.is_concealment),
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
