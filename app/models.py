"""Data models for Woo's NWN Parser application.

This module contains dataclasses representing various entities tracked
by the combat log parser: enemies, saving throws, armor class, and damage events.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# Palette for damage type colors (case-insensitive substring matching)
DAMAGE_TYPE_PALETTE = {
    'physical':  '#D97706',  # rich orange
    'fire':      '#DC2626',  # deep red
    'cold':      '#0EA5E9',  # icy blue
    'acid':      '#10B981',  # emerald green
    'electrical':'#2563EB',  # electric blue
    'sonic':     '#F59E0B',  # amber
    'negative':  '#6B7280',  # dark gray
    'positive':  '#D1D5DB',  # light gray
    'pure':      '#E879F9',  # magenta
    'magical':   '#8B5CF6',  # violet
    'divine':    '#FACC15',  # golden yellow
}


@dataclass
class EnemySaves:
    """Tracks saving throws for an enemy."""
    name: str
    fortitude: Optional[int] = None
    reflex: Optional[int] = None
    will: Optional[int] = None

    def update_save(self, save_type: str, bonus: int) -> None:
        """Update a save type with the given bonus, keeping the maximum.

        Args:
            save_type: Type of save ('fort', 'ref', 'will')
            bonus: Bonus value to record
        """
        if save_type == 'fort':
            if self.fortitude is None or bonus > self.fortitude:
                self.fortitude = bonus
        elif save_type == 'ref':
            if self.reflex is None or bonus > self.reflex:
                self.reflex = bonus
        elif save_type == 'will':
            if self.will is None or bonus > self.will:
                self.will = bonus


@dataclass
class EnemyAC:
    """Tracks armor class estimates for an enemy."""
    name: str
    min_hit: Optional[int] = None
    max_miss: Optional[int] = None

    def record_hit(self, total: int) -> None:
        """Record a successful attack roll total.

        Args:
            total: The attack roll total (d20 + bonuses)
        """
        if self.min_hit is None or total < self.min_hit:
            self.min_hit = total

    def record_miss(self, total: int, was_nat1: bool = False) -> None:
        """Record a failed attack roll total, excluding natural 1s.

        Args:
            total: The attack roll total
            was_nat1: Whether this was a natural 1 (excluded from AC estimation)
        """
        if not was_nat1:
            if self.max_miss is None or total > self.max_miss:
                self.max_miss = total

    def get_ac_estimate(self) -> str:
        """Return an estimated AC based on recorded hits and misses.

        Returns:
            String representation of estimated AC, e.g. "18", "15-16", "≤14"
        """
        if self.min_hit is not None and self.max_miss is not None:
            if self.max_miss + 1 == self.min_hit:
                return str(self.min_hit)
            elif self.max_miss < self.min_hit:
                return f"{self.max_miss + 1}-{self.min_hit}"
            else:
                return f"~{self.min_hit}"
        elif self.min_hit is not None:
            return f"≤{self.min_hit}"
        elif self.max_miss is not None:
            return f">{self.max_miss}"
        return "?"


@dataclass
class TargetAttackBonus:
    """Tracks most common attack bonus for an enemy.

    Uses the mode (most frequent value) to determine the typical attack bonus,
    filtering out temporary buffs or debuffs that may skew the maximum value.
    """
    name: str
    max_bonus: Optional[int] = None
    _bonus_counts: dict[int, int] = field(default_factory=dict, repr=False)

    def record_bonus(self, bonus: int) -> None:
        """Record an attack bonus and update to the most frequent value.

        Args:
            bonus: The attack bonus value
        """
        # Increment count for this bonus value
        self._bonus_counts[bonus] = self._bonus_counts.get(bonus, 0) + 1

        # Update max_bonus to the most frequent value
        # In case of tie, prefer the higher bonus
        most_common_bonus = max(self._bonus_counts.items(), key=lambda x: (x[1], x[0]))[0]
        self.max_bonus = most_common_bonus

    def get_bonus_display(self) -> str:
        """Return the most common attack bonus found for this target.

        Returns:
            String representation of attack bonus, e.g. "15" or "?"
        """
        if self.max_bonus is not None:
            return str(self.max_bonus)
        return "?"


@dataclass
class DamageEvent:
    """Represents a single damage event record."""
    target: str
    damage_type: str
    immunity_absorbed: int = 0
    total_damage_dealt: int = 0
    attacker: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AttackEvent:
    """Represents a single attack roll."""
    attacker: str
    target: str
    outcome: str  # 'hit', 'critical_hit', 'miss', 'concealed'
    roll: Optional[int] = None
    bonus: Optional[int] = None
    total: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

