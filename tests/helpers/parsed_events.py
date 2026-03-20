"""Test-only helpers for building typed parsed events from legacy-style fixtures."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.parsed_events import (
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


def from_dict(payload: dict[str, Any]) -> ParsedEvent | dict[str, Any]:
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, datetime):
        timestamp = datetime.now()
    line_number = payload.get("line_number")
    event_type = payload["type"]

    if event_type == "damage_dealt":
        return DamageDealtEvent(
            attacker=str(payload.get("attacker", "")),
            target=str(payload.get("target", "")),
            total_damage=int(payload.get("total_damage", 0) or 0),
            damage_types=dict(payload.get("damage_types", {}) or {}),
            timestamp=timestamp,
            line_number=line_number,
        )
    if event_type == "immunity":
        immunity_points = int(payload.get("immunity_points", 0) or 0)
        return ImmunityObservedEvent(
            target=str(payload.get("target", "")),
            damage_type=str(payload.get("damage_type", "")),
            immunity_points=immunity_points,
            dmg_reduced=int(payload.get("dmg_reduced", immunity_points) or 0),
            timestamp=timestamp,
            line_number=line_number,
        )
    if event_type == "attack_hit":
        return AttackHitEvent(
            attacker=str(payload.get("attacker", "")),
            target=str(payload.get("target", "")),
            roll=int(payload.get("roll", 0) or 0),
            bonus=_optional_int(payload.get("bonus")),
            total=int(payload.get("total", 0) or 0),
            was_nat20=bool(payload.get("was_nat20", False)),
            is_concealment=bool(payload.get("is_concealment", False)),
            timestamp=timestamp,
            line_number=line_number,
        )
    if event_type in {"attack_hit_critical", "critical_hit"}:
        return AttackCriticalHitEvent(
            attacker=str(payload.get("attacker", "")),
            target=str(payload.get("target", "")),
            roll=int(payload.get("roll", 0) or 0),
            bonus=_optional_int(payload.get("bonus")),
            total=int(payload.get("total", 0) or 0),
            was_nat20=bool(payload.get("was_nat20", False)),
            is_concealment=bool(payload.get("is_concealment", False)),
            timestamp=timestamp,
            line_number=line_number,
        )
    if event_type == "attack_miss":
        return AttackMissEvent(
            attacker=str(payload.get("attacker", "")),
            target=str(payload.get("target", "")),
            roll=int(payload.get("roll", 0) or 0),
            bonus=_optional_int(payload.get("bonus")),
            total=int(payload.get("total", 0) or 0),
            was_nat1=bool(payload.get("was_nat1", False)),
            is_concealment=bool(payload.get("is_concealment", False)),
            timestamp=timestamp,
            line_number=line_number,
        )
    if event_type == "save":
        return SaveObservedEvent(
            target=str(payload.get("target", "")),
            save_type=str(payload.get("save_type", "")),
            bonus=int(payload.get("bonus", 0) or 0),
            timestamp=timestamp,
            line_number=line_number,
        )
    if event_type == "epic_dodge":
        return EpicDodgeEvent(
            target=str(payload.get("target", "")),
            timestamp=timestamp,
            line_number=line_number,
        )
    if event_type == "death_snippet":
        return DeathSnippetEvent(
            target=str(payload.get("target", "")),
            killer=str(payload.get("killer", "")),
            lines=list(payload.get("lines", []) or []),
            timestamp=timestamp,
            line_number=line_number,
        )
    if event_type == "death_character_identified":
        return DeathCharacterIdentifiedEvent(
            character_name=str(payload.get("character_name", "")),
            timestamp=timestamp,
            line_number=line_number,
        )
    return payload


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
