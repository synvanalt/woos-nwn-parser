"""Typed read-side DTOs for query-service results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class DpsRow:
    """One top-level DPS row for UI/query consumers."""

    character: str
    total_damage: int
    time_seconds: timedelta
    dps: float
    breakdown_token: tuple[tuple[str, int], ...]
    hit_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class DpsBreakdownRow:
    """One DPS damage-type breakdown row."""

    damage_type: str
    total_damage: int
    dps: float


@dataclass(frozen=True, slots=True)
class ImmunityDisplayRow:
    """One prepared target immunity display row for the UI."""

    damage_type: str
    max_damage_display: str
    absorbed_display: str
    immunity_pct_display: str
    samples_display: str


@dataclass(frozen=True, slots=True)
class TargetSummaryRow:
    """One Target Stats display row."""

    target: str
    ab: str
    ac: str
    fortitude: str
    reflex: str
    will: str
    damage_taken: str
