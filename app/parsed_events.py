"""Typed parser-output event models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, ClassVar, Literal, TypeAlias


@dataclass(slots=True, frozen=True)
class ParsedEventBase:
    """Common fields and light compatibility helpers for parsed events."""

    timestamp: datetime
    line_number: int | None = None
    EVENT_TYPE: ClassVar[str] = "event"

    @property
    def type(self) -> str:
        return self.EVENT_TYPE

    def __getitem__(self, key: str) -> Any:
        if key == "type":
            return self.type
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except AttributeError:
            return default

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["type"] = self.type
        return payload


@dataclass(slots=True, frozen=True)
class DamageDealtEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["damage_dealt"]] = "damage_dealt"

    attacker: str = ""
    target: str = ""
    total_damage: int = 0
    damage_types: dict[str, int] | None = None


@dataclass(slots=True, frozen=True)
class ImmunityObservedEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["immunity"]] = "immunity"

    target: str = ""
    damage_type: str = ""
    immunity_points: int = 0
    dmg_reduced: int = 0


@dataclass(slots=True, frozen=True)
class AttackHitEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["attack_hit"]] = "attack_hit"

    attacker: str = ""
    target: str = ""
    roll: int = 0
    bonus: int | None = None
    total: int = 0
    was_nat20: bool = False
    is_concealment: bool = False


@dataclass(slots=True, frozen=True)
class AttackCriticalHitEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["attack_hit_critical"]] = "attack_hit_critical"

    attacker: str = ""
    target: str = ""
    roll: int = 0
    bonus: int | None = None
    total: int = 0
    was_nat20: bool = False
    is_concealment: bool = False


@dataclass(slots=True, frozen=True)
class AttackMissEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["attack_miss"]] = "attack_miss"

    attacker: str = ""
    target: str = ""
    roll: int = 0
    bonus: int | None = None
    total: int = 0
    was_nat1: bool = False
    is_concealment: bool = False


@dataclass(slots=True, frozen=True)
class SaveObservedEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["save"]] = "save"

    target: str = ""
    save_type: str = ""
    bonus: int = 0


@dataclass(slots=True, frozen=True)
class EpicDodgeEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["epic_dodge"]] = "epic_dodge"

    target: str = ""


@dataclass(slots=True, frozen=True)
class DeathSnippetEvent(ParsedEventBase):
    EVENT_TYPE: ClassVar[Literal["death_snippet"]] = "death_snippet"

    target: str = ""
    killer: str = ""
    lines: list[str] | None = None


@dataclass(slots=True, frozen=True)
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

LegacyParsedEventPayload: TypeAlias = dict[str, Any]


def coerce_parsed_event(value: ParsedEvent | LegacyParsedEventPayload) -> ParsedEvent | LegacyParsedEventPayload:
    """Convert legacy dict payloads into typed parsed events when recognized."""
    if not isinstance(value, dict):
        return value

    event_type = value.get("type")
    timestamp = value.get("timestamp")
    if not isinstance(timestamp, datetime):
        timestamp = datetime.now()
    line_number = value.get("line_number")

    common = {
        "timestamp": timestamp,
        "line_number": line_number,
    }
    if event_type == "damage_dealt":
        return DamageDealtEvent(
            attacker=str(value.get("attacker", "")),
            target=str(value.get("target", "")),
            total_damage=int(value.get("total_damage", 0) or 0),
            damage_types=dict(value.get("damage_types", {}) or {}),
            **common,
        )
    if event_type == "immunity":
        immunity_points = int(value.get("immunity_points", 0) or 0)
        return ImmunityObservedEvent(
            target=str(value.get("target", "")),
            damage_type=str(value.get("damage_type", "")),
            immunity_points=immunity_points,
            dmg_reduced=int(value.get("dmg_reduced", immunity_points) or 0),
            **common,
        )
    if event_type == "attack_hit":
        return AttackHitEvent(
            attacker=str(value.get("attacker", "")),
            target=str(value.get("target", "")),
            roll=int(value.get("roll", 0) or 0),
            bonus=_coerce_optional_int(value.get("bonus")),
            total=int(value.get("total", 0) or 0),
            was_nat20=bool(value.get("was_nat20", False)),
            is_concealment=bool(value.get("is_concealment", False)),
            **common,
        )
    if event_type in {"attack_hit_critical", "critical_hit"}:
        return AttackCriticalHitEvent(
            attacker=str(value.get("attacker", "")),
            target=str(value.get("target", "")),
            roll=int(value.get("roll", 0) or 0),
            bonus=_coerce_optional_int(value.get("bonus")),
            total=int(value.get("total", 0) or 0),
            was_nat20=bool(value.get("was_nat20", False)),
            is_concealment=bool(value.get("is_concealment", False)),
            **common,
        )
    if event_type == "attack_miss":
        return AttackMissEvent(
            attacker=str(value.get("attacker", "")),
            target=str(value.get("target", "")),
            roll=int(value.get("roll", 0) or 0),
            bonus=_coerce_optional_int(value.get("bonus")),
            total=int(value.get("total", 0) or 0),
            was_nat1=bool(value.get("was_nat1", False)),
            is_concealment=bool(value.get("is_concealment", False)),
            **common,
        )
    if event_type == "save":
        return SaveObservedEvent(
            target=str(value.get("target", "")),
            save_type=str(value.get("save_type", "")),
            bonus=int(value.get("bonus", 0) or 0),
            **common,
        )
    if event_type == "epic_dodge":
        return EpicDodgeEvent(target=str(value.get("target", "")), **common)
    if event_type == "death_snippet":
        return DeathSnippetEvent(
            target=str(value.get("target", "")),
            killer=str(value.get("killer", "")),
            lines=list(value.get("lines", []) or []),
            **common,
        )
    if event_type == "death_character_identified":
        return DeathCharacterIdentifiedEvent(
            character_name=str(value.get("character_name", "")),
            **common,
        )
    return value


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
