"""Shared mutation builders for tests using the public-first DataStore API."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.models import (
    AttackMutation,
    DamageMutation,
    EpicDodgeMutation,
    ImmunityMutation,
    SaveMutation,
    StoreMutation,
)
from app.storage import DataStore


def apply(store: DataStore, *mutations: StoreMutation | Iterable[StoreMutation]) -> None:
    """Apply one batch of mutations, flattening iterables for convenience."""
    flattened: list[StoreMutation] = []
    for mutation in mutations:
        if isinstance(mutation, (DamageMutation, AttackMutation, ImmunityMutation, SaveMutation, EpicDodgeMutation)):
            flattened.append(mutation)
        else:
            flattened.extend(mutation)
    store.apply_mutations(flattened)


def damage_row(
    *,
    target: str,
    damage_type: str,
    total_damage: int,
    attacker: str = "",
    timestamp: datetime | None = None,
    immunity_absorbed: int = 0,
) -> DamageMutation:
    """Build one stored damage row."""
    return DamageMutation(
        target=target,
        damage_type=damage_type,
        total_damage=total_damage,
        attacker=attacker,
        timestamp=timestamp or datetime.now(),
        immunity_absorbed=immunity_absorbed,
    )


def dps_update(
    *,
    attacker: str,
    total_damage: int,
    timestamp: datetime,
    damage_types: dict[str, int] | None = None,
    target: str = "",
) -> DamageMutation:
    """Build the DPS-only mutation used for one logical damage_dealt event."""
    return DamageMutation(
        target=target,
        total_damage=total_damage,
        attacker=attacker,
        timestamp=timestamp,
        count_for_dps=True,
        damage_types=damage_types,
    )


def damage_dealt(
    *,
    attacker: str,
    target: str,
    timestamp: datetime,
    damage_types: dict[str, int],
    immunities: dict[str, int] | None = None,
) -> list[StoreMutation]:
    """Build the full production-equivalent mutation set for one damage_dealt event."""
    normalized = {damage_type: int(amount or 0) for damage_type, amount in damage_types.items()}
    mutations: list[StoreMutation] = [
        dps_update(
            attacker=attacker,
            target=target,
            total_damage=sum(normalized.values()),
            timestamp=timestamp,
            damage_types=normalized,
        )
    ]
    immunity_map = immunities or {}
    for damage_type, amount in normalized.items():
        mutations.append(
            damage_row(
                target=target,
                damage_type=damage_type,
                total_damage=amount,
                attacker=attacker,
                timestamp=timestamp,
                immunity_absorbed=int(immunity_map.get(damage_type, 0)),
            )
        )
    return mutations


def attack(
    *,
    attacker: str,
    target: str,
    outcome: str,
    roll: int | None = None,
    bonus: int | None = None,
    total: int | None = None,
    was_nat1: bool = False,
    was_nat20: bool = False,
    is_concealment: bool = False,
) -> AttackMutation:
    """Build one attack mutation."""
    return AttackMutation(
        attacker=attacker,
        target=target,
        outcome=outcome,
        roll=roll,
        bonus=bonus,
        total=total,
        was_nat1=was_nat1,
        was_nat20=was_nat20,
        is_concealment=is_concealment,
    )


def immunity(*, target: str, damage_type: str, immunity_points: int, damage_dealt: int) -> ImmunityMutation:
    """Build one immunity mutation."""
    return ImmunityMutation(
        target=target,
        damage_type=damage_type,
        immunity_points=immunity_points,
        damage_dealt=damage_dealt,
    )


def save(*, target: str, save_key: str, bonus: int) -> SaveMutation:
    """Build one save mutation."""
    return SaveMutation(target=target, save_key=save_key, bonus=bonus)


def epic_dodge(*, target: str) -> EpicDodgeMutation:
    """Build one epic-dodge mutation."""
    return EpicDodgeMutation(target=target)
