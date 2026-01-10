"""Unit tests for data models.

Tests dataclasses and model methods for combat tracking.
"""

import pytest
from datetime import datetime

from app.models import (
    EnemySaves,
    EnemyAC,
    TargetAttackBonus,
    DamageEvent,
    AttackEvent,
    DAMAGE_TYPE_PALETTE,
)


class TestEnemySaves:
    """Test suite for EnemySaves model."""

    def test_initialization(self) -> None:
        """Test EnemySaves initializes with correct defaults."""
        saves = EnemySaves(name="TestEnemy")
        assert saves.name == "TestEnemy"
        assert saves.fortitude is None
        assert saves.reflex is None
        assert saves.will is None

    def test_update_save_fortitude(self) -> None:
        """Test updating fortitude save."""
        saves = EnemySaves(name="TestEnemy")
        saves.update_save('fort', 10)
        assert saves.fortitude == 10

    def test_update_save_reflex(self) -> None:
        """Test updating reflex save."""
        saves = EnemySaves(name="TestEnemy")
        saves.update_save('ref', 8)
        assert saves.reflex == 8

    def test_update_save_will(self) -> None:
        """Test updating will save."""
        saves = EnemySaves(name="TestEnemy")
        saves.update_save('will', 12)
        assert saves.will == 12

    def test_update_save_keeps_maximum(self) -> None:
        """Test that update_save keeps the maximum value."""
        saves = EnemySaves(name="TestEnemy")
        saves.update_save('fort', 10)
        saves.update_save('fort', 15)  # Higher
        assert saves.fortitude == 15

        saves.update_save('fort', 12)  # Lower
        assert saves.fortitude == 15  # Should not change

    def test_update_save_all_types(self) -> None:
        """Test updating all save types."""
        saves = EnemySaves(name="TestEnemy")
        saves.update_save('fort', 10)
        saves.update_save('ref', 8)
        saves.update_save('will', 12)

        assert saves.fortitude == 10
        assert saves.reflex == 8
        assert saves.will == 12


class TestEnemyAC:
    """Test suite for EnemyAC model."""

    def test_initialization(self) -> None:
        """Test EnemyAC initializes with correct defaults."""
        ac = EnemyAC(name="TestEnemy")
        assert ac.name == "TestEnemy"
        assert ac.min_hit is None
        assert ac.max_miss is None

    def test_record_hit(self) -> None:
        """Test recording a hit updates min_hit."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_hit(20)
        assert ac.min_hit == 20

    def test_record_hit_keeps_minimum(self) -> None:
        """Test record_hit keeps the minimum value."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_hit(20)
        ac.record_hit(15)  # Lower
        assert ac.min_hit == 15

        ac.record_hit(25)  # Higher
        assert ac.min_hit == 15  # Should not change

    def test_record_miss(self) -> None:
        """Test recording a miss updates max_miss."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_miss(15)
        assert ac.max_miss == 15

    def test_record_miss_keeps_maximum(self) -> None:
        """Test record_miss keeps the maximum value."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_miss(15)
        ac.record_miss(18)  # Higher
        assert ac.max_miss == 18

        ac.record_miss(12)  # Lower
        assert ac.max_miss == 18  # Should not change

    def test_record_miss_ignores_natural_1(self) -> None:
        """Test that natural 1 misses are ignored."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_miss(5, was_nat1=True)
        assert ac.max_miss is None  # Should not record natural 1

        ac.record_miss(15, was_nat1=False)
        assert ac.max_miss == 15

        ac.record_miss(3, was_nat1=True)
        assert ac.max_miss == 15  # Should not change

    def test_get_ac_estimate_exact(self) -> None:
        """Test AC estimation when max_miss + 1 == min_hit."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_hit(16)
        ac.record_miss(15)
        estimate = ac.get_ac_estimate()
        assert estimate == "16"

    def test_get_ac_estimate_range(self) -> None:
        """Test AC estimation when there's a range."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_hit(18)
        ac.record_miss(14)
        estimate = ac.get_ac_estimate()
        assert estimate == "15-18"

    def test_get_ac_estimate_only_hits(self) -> None:
        """Test AC estimation with only hits recorded."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_hit(20)
        estimate = ac.get_ac_estimate()
        assert estimate == "≤20"

    def test_get_ac_estimate_only_misses(self) -> None:
        """Test AC estimation with only misses recorded."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_miss(15)
        estimate = ac.get_ac_estimate()
        assert estimate == ">15"

    def test_get_ac_estimate_no_data(self) -> None:
        """Test AC estimation with no data."""
        ac = EnemyAC(name="TestEnemy")
        estimate = ac.get_ac_estimate()
        assert estimate == "?"

    def test_get_ac_estimate_conflicting_data(self) -> None:
        """Test AC estimation when max_miss > min_hit (shouldn't happen but handle it)."""
        ac = EnemyAC(name="TestEnemy")
        ac.record_hit(15)
        ac.record_miss(20)
        estimate = ac.get_ac_estimate()
        assert estimate == "~15"  # Shows approximation


class TestTargetAttackBonus:
    """Test suite for TargetAttackBonus model."""

    def test_initialization(self) -> None:
        """Test TargetAttackBonus initializes correctly."""
        tab = TargetAttackBonus(name="TestEnemy")
        assert tab.name == "TestEnemy"
        assert tab.max_bonus is None

    def test_record_bonus(self) -> None:
        """Test recording an attack bonus."""
        tab = TargetAttackBonus(name="TestEnemy")
        tab.record_bonus(10)
        assert tab.max_bonus == 10

    def test_record_bonus_keeps_maximum(self) -> None:
        """Test record_bonus keeps the maximum value."""
        tab = TargetAttackBonus(name="TestEnemy")
        tab.record_bonus(10)
        tab.record_bonus(15)  # Higher
        assert tab.max_bonus == 15

        tab.record_bonus(8)  # Lower
        assert tab.max_bonus == 15  # Should not change

    def test_record_negative_bonus(self) -> None:
        """Test recording negative attack bonus."""
        tab = TargetAttackBonus(name="WeakEnemy")
        tab.record_bonus(-3)
        assert tab.max_bonus == -3

    def test_get_bonus_display_no_data(self) -> None:
        """Test display with no data."""
        tab = TargetAttackBonus(name="TestEnemy")
        display = tab.get_bonus_display()
        assert display == "?"

    def test_get_bonus_display_positive(self) -> None:
        """Test display with positive bonus."""
        tab = TargetAttackBonus(name="TestEnemy")
        tab.record_bonus(10)
        display = tab.get_bonus_display()
        assert display == "+10"

    def test_get_bonus_display_negative(self) -> None:
        """Test display with negative bonus."""
        tab = TargetAttackBonus(name="WeakEnemy")
        tab.record_bonus(-5)
        display = tab.get_bonus_display()
        assert display == "-5"

    def test_get_bonus_display_zero(self) -> None:
        """Test display with zero bonus."""
        tab = TargetAttackBonus(name="TestEnemy")
        tab.record_bonus(0)
        display = tab.get_bonus_display()
        assert display == "+0"


class TestDamageEvent:
    """Test suite for DamageEvent dataclass."""

    def test_initialization(self) -> None:
        """Test DamageEvent initializes with required fields."""
        event = DamageEvent(
            target="Goblin",
            damage_type="Fire",
            immunity_absorbed=10,
            total_damage_dealt=40,
            attacker="Woo"
        )
        assert event.target == "Goblin"
        assert event.damage_type == "Fire"
        assert event.immunity_absorbed == 10
        assert event.total_damage_dealt == 40
        assert event.attacker == "Woo"
        assert isinstance(event.timestamp, datetime)

    def test_initialization_with_defaults(self) -> None:
        """Test DamageEvent with default values."""
        event = DamageEvent(target="Orc", damage_type="Cold")
        assert event.immunity_absorbed == 0
        assert event.total_damage_dealt == 0
        assert event.attacker == ""
        assert isinstance(event.timestamp, datetime)

    def test_initialization_with_timestamp(self) -> None:
        """Test DamageEvent with custom timestamp."""
        ts = datetime(2026, 1, 9, 14, 30, 0)
        event = DamageEvent(
            target="Dragon",
            damage_type="Fire",
            timestamp=ts
        )
        assert event.timestamp == ts


class TestAttackEvent:
    """Test suite for AttackEvent dataclass."""

    def test_initialization(self) -> None:
        """Test AttackEvent initializes with required fields."""
        event = AttackEvent(
            attacker="Woo",
            target="Goblin",
            outcome="hit",
            roll=15,
            bonus=5,
            total=20
        )
        assert event.attacker == "Woo"
        assert event.target == "Goblin"
        assert event.outcome == "hit"
        assert event.roll == 15
        assert event.bonus == 5
        assert event.total == 20
        assert isinstance(event.timestamp, datetime)

    def test_initialization_with_defaults(self) -> None:
        """Test AttackEvent with default values."""
        event = AttackEvent(attacker="Rogue", target="Orc", outcome="miss")
        assert event.roll is None
        assert event.bonus is None
        assert event.total is None
        assert isinstance(event.timestamp, datetime)

    def test_initialization_with_timestamp(self) -> None:
        """Test AttackEvent with custom timestamp."""
        ts = datetime(2026, 1, 9, 14, 30, 0)
        event = AttackEvent(
            attacker="Mage",
            target="Dragon",
            outcome="critical_hit",
            timestamp=ts
        )
        assert event.timestamp == ts


class TestDamageTypePalette:
    """Test suite for DAMAGE_TYPE_PALETTE constant."""

    def test_palette_exists(self) -> None:
        """Test that damage type palette is defined."""
        assert DAMAGE_TYPE_PALETTE is not None
        assert isinstance(DAMAGE_TYPE_PALETTE, dict)

    def test_palette_contains_common_types(self) -> None:
        """Test palette contains common damage types."""
        expected_types = ['physical', 'fire', 'cold', 'acid', 'electrical']
        for dtype in expected_types:
            assert dtype in DAMAGE_TYPE_PALETTE

    def test_palette_colors_are_hex(self) -> None:
        """Test all palette colors are valid hex codes."""
        for color in DAMAGE_TYPE_PALETTE.values():
            assert isinstance(color, str)
            assert color.startswith('#')
            assert len(color) == 7  # #RRGGBB format

