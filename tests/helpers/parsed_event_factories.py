from __future__ import annotations

from datetime import datetime

from app.parsed_events import (
    AttackCriticalHitEvent,
    AttackHitEvent,
    AttackMissEvent,
    DamageDealtEvent,
    DeathCharacterIdentifiedEvent,
    DeathSnippetEvent,
    ImmunityObservedEvent,
    SaveObservedEvent,
)


def damage_event(
    *,
    attacker: str = "",
    target: str = "",
    total_damage: int = 0,
    damage_types: dict[str, int] | None = None,
    timestamp: datetime | None = None,
    line_number: int | None = None,
) -> DamageDealtEvent:
    return DamageDealtEvent(
        attacker=attacker,
        target=target,
        total_damage=total_damage,
        damage_types=damage_types or {},
        timestamp=timestamp or datetime.now(),
        line_number=line_number,
    )


def immunity_event(
    *,
    target: str = "",
    damage_type: str = "",
    immunity_points: int = 0,
    dmg_reduced: int | None = None,
    timestamp: datetime | None = None,
    line_number: int | None = None,
) -> ImmunityObservedEvent:
    return ImmunityObservedEvent(
        target=target,
        damage_type=damage_type,
        immunity_points=immunity_points,
        dmg_reduced=immunity_points if dmg_reduced is None else dmg_reduced,
        timestamp=timestamp or datetime.now(),
        line_number=line_number,
    )


def attack_hit_event(
    *,
    attacker: str = "",
    target: str = "",
    roll: int = 0,
    bonus: int | None = None,
    total: int = 0,
    was_nat20: bool = False,
    is_concealment: bool = False,
    timestamp: datetime | None = None,
    line_number: int | None = None,
) -> AttackHitEvent:
    return AttackHitEvent(
        attacker=attacker,
        target=target,
        roll=roll,
        bonus=bonus,
        total=total,
        was_nat20=was_nat20,
        is_concealment=is_concealment,
        timestamp=timestamp or datetime.now(),
        line_number=line_number,
    )


def attack_miss_event(
    *,
    attacker: str = "",
    target: str = "",
    roll: int = 0,
    bonus: int | None = None,
    total: int = 0,
    was_nat1: bool = False,
    is_concealment: bool = False,
    timestamp: datetime | None = None,
    line_number: int | None = None,
) -> AttackMissEvent:
    return AttackMissEvent(
        attacker=attacker,
        target=target,
        roll=roll,
        bonus=bonus,
        total=total,
        was_nat1=was_nat1,
        is_concealment=is_concealment,
        timestamp=timestamp or datetime.now(),
        line_number=line_number,
    )


def critical_hit_event(
    *,
    attacker: str = "",
    target: str = "",
    roll: int = 0,
    bonus: int | None = None,
    total: int = 0,
    was_nat20: bool = False,
    is_concealment: bool = False,
    timestamp: datetime | None = None,
    line_number: int | None = None,
) -> AttackCriticalHitEvent:
    return AttackCriticalHitEvent(
        attacker=attacker,
        target=target,
        roll=roll,
        bonus=bonus,
        total=total,
        was_nat20=was_nat20,
        is_concealment=is_concealment,
        timestamp=timestamp or datetime.now(),
        line_number=line_number,
    )


def save_event(
    *,
    target: str = "",
    save_type: str = "",
    bonus: int = 0,
    timestamp: datetime | None = None,
    line_number: int | None = None,
) -> SaveObservedEvent:
    return SaveObservedEvent(
        target=target,
        save_type=save_type,
        bonus=bonus,
        timestamp=timestamp or datetime.now(),
        line_number=line_number,
    )


def death_snippet_event(
    *,
    target: str = "",
    killer: str = "",
    lines: list[str] | None = None,
    timestamp: datetime | None = None,
    line_number: int | None = None,
) -> DeathSnippetEvent:
    return DeathSnippetEvent(
        target=target,
        killer=killer,
        lines=lines or [],
        timestamp=timestamp or datetime.now(),
        line_number=line_number,
    )


def death_character_identified_event(
    *,
    character_name: str = "",
    timestamp: datetime | None = None,
    line_number: int | None = None,
) -> DeathCharacterIdentifiedEvent:
    return DeathCharacterIdentifiedEvent(
        character_name=character_name,
        timestamp=timestamp or datetime.now(),
        line_number=line_number,
    )
