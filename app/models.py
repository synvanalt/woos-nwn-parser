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
    """Tracks armor class estimates for an enemy.

    Tracks all hit totals to handle cases where the target was temporarily
    debuffed (flat-footed, blinded, etc.). When a miss total exceeds existing
    hit totals, those hits are discarded as they likely occurred when the
    target had reduced AC.
    """
    name: str
    max_miss: Optional[int] = None
    _hits: list[int] = field(default_factory=list, repr=False)

    @property
    def min_hit(self) -> Optional[int]:
        """Return the minimum hit total, or None if no valid hits recorded."""
        return min(self._hits) if self._hits else None

    def record_hit(self, total: int, was_nat20: bool = False) -> None:
        """Record a successful attack roll total, excluding natural 20s.

        Args:
            total: The attack roll total (d20 + bonuses)
            was_nat20: Whether this was a natural 20 (excluded from AC estimation)
        """
        if not was_nat20:
            # Only add if it's above max_miss (if we have one)
            # This prevents adding hits that are already invalidated
            if self.max_miss is None or total > self.max_miss:
                self._hits.append(total)

    def record_miss(self, total: int, was_nat1: bool = False) -> None:
        """Record a failed attack roll total, excluding natural 1s.

        When a new max_miss is recorded that exceeds existing hit totals,
        those hits are discarded as they likely occurred when the target
        had temporarily reduced AC (flat-footed, blinded, etc.).

        Args:
            total: The attack roll total
            was_nat1: Whether this was a natural 1 (excluded from AC estimation)
        """
        if not was_nat1:
            if self.max_miss is None or total > self.max_miss:
                self.max_miss = total
                # Remove all hits that are now invalidated by this miss
                # (hits <= max_miss shouldn't have hit if target had true AC)
                self._hits = [h for h in self._hits if h > self.max_miss]

    def get_ac_estimate(self) -> str:
        """Return an estimated AC based on recorded hits and misses.

        Returns:
            String representation of estimated AC, e.g. "18", "15-16", "≤14"
        """
        min_hit = self.min_hit

        if min_hit is not None and self.max_miss is not None:
            if self.max_miss + 1 == min_hit:
                return str(min_hit)
            elif self.max_miss < min_hit:
                return f"{self.max_miss + 1}-{min_hit}"
            else:
                # This case should now be rare due to automatic cleanup
                return f"~{min_hit}"
        elif min_hit is not None:
            return f"≤{min_hit}"
        elif self.max_miss is not None:
            return f">{self.max_miss}"
        return "-"


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
            String representation of attack bonus, e.g. "15" or "-"
        """
        if self.max_bonus is not None:
            return str(self.max_bonus)
        return "-"


@dataclass(slots=True)
class DamageEvent:
    """Represents a single damage event record."""
    target: str
    damage_type: str
    immunity_absorbed: int = 0
    total_damage_dealt: int = 0
    attacker: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class AttackEvent:
    """Represents a single attack roll."""
    attacker: str
    target: str
    outcome: str  # 'hit', 'critical_hit', 'miss', 'concealed'
    roll: Optional[int] = None
    bonus: Optional[int] = None
    total: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

