"""Typed parser-output event models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal, TypeAlias


@dataclass(slots=True)
class ParsedEventBase:
    """Common fields for parsed events."""

    timestamp: datetime
    line_number: int | None = None
    EVENT_TYPE: ClassVar[str] = "event"

    @property
    def type(self) -> str:
        return self.EVENT_TYPE


@dataclass(slots=True)
class DamageDealtEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["damage_dealt"]] = "damage_dealt"

    attacker: str = ""
    target: str = ""
    total_damage: int = 0
    damage_types: dict[str, int] | None = None


@dataclass(slots=True)
class ImmunityObservedEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["immunity"]] = "immunity"

    target: str = ""
    damage_type: str = ""
    immunity_points: int = 0
    dmg_reduced: int = 0


@dataclass(slots=True)
class AttackHitEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["attack_hit"]] = "attack_hit"

    attacker: str = ""
    target: str = ""
    roll: int = 0
    bonus: int | None = None
    total: int = 0
    was_nat20: bool = False
    is_concealment: bool = False


@dataclass(slots=True)
class AttackCriticalHitEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["attack_hit_critical"]] = "attack_hit_critical"

    attacker: str = ""
    target: str = ""
    roll: int = 0
    bonus: int | None = None
    total: int = 0
    was_nat20: bool = False
    is_concealment: bool = False


@dataclass(slots=True)
class AttackMissEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["attack_miss"]] = "attack_miss"

    attacker: str = ""
    target: str = ""
    roll: int = 0
    bonus: int | None = None
    total: int = 0
    was_nat1: bool = False
    is_concealment: bool = False


@dataclass(slots=True)
class SaveObservedEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["save"]] = "save"

    target: str = ""
    save_type: str = ""
    bonus: int = 0


@dataclass(slots=True)
class EpicDodgeEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["epic_dodge"]] = "epic_dodge"

    target: str = ""


@dataclass(slots=True)
class DeathSnippetEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["death_snippet"]] = "death_snippet"

    target: str = ""
    killer: str = ""
    lines: list[str] | None = None


@dataclass(slots=True)
class DeathCharacterIdentifiedEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["death_character_identified"]] = "death_character_identified"

    character_name: str = ""


ParsedEvent: TypeAlias = (
    DamageDealtEvent
    | ImmunityObservedEvent
    | AttackHitEvent
    | AttackCriticalHitEvent
    | AttackMissEvent
    | SaveObservedEvent
    | EpicDodgeEvent
    | DeathSnippetEvent
    | DeathCharacterIdentifiedEvent
)
