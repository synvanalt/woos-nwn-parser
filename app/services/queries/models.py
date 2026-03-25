"""Typed read-side DTOs for query-service results."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta


class _MappingCompatMixin:
    """Provide narrow read-only mapping compatibility for legacy callers/tests."""

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and hasattr(self, key)

    def keys(self) -> tuple[str, ...]:
        return tuple(self.__dataclass_fields__)  # type: ignore[attr-defined]

    def items(self) -> Iterator[tuple[str, object]]:
        for key in self.keys():
            yield key, getattr(self, key)


@dataclass(frozen=True, slots=True)
class DpsRow(_MappingCompatMixin):
    """One top-level DPS row for UI/query consumers."""

    character: str
    total_damage: int
    time_seconds: timedelta
    dps: float
    breakdown_token: tuple[tuple[str, int], ...]
    hit_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class DpsBreakdownRow(_MappingCompatMixin):
    """One DPS damage-type breakdown row."""

    damage_type: str
    total_damage: int
    dps: float


@dataclass(frozen=True, slots=True)
class ImmunitySummaryRow(_MappingCompatMixin):
    """One target immunity summary row."""

    damage_type: str
    max_event_damage: int
    max_immunity_damage: int
    immunity_absorbed: int
    sample_count: int
    suppress_temporary_full_immunity: bool


@dataclass(frozen=True, slots=True)
class TargetSummaryRow(_MappingCompatMixin):
    """One Target Stats display row."""

    target: str
    ab: str
    ac: str
    fortitude: str
    reflex: str
    will: str
    damage_taken: str
