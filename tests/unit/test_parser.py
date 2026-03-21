"""Unit tests for the parser session and line parser layers.

Tests regex pattern matching, damage parsing, immunity parsing,
attack parsing, save parsing, and player filtering.
"""

from datetime import datetime

import app.parser_session as parser_session_module
from app.parser import LineParser, ParserSession
from app.parsed_events import (
    AttackCriticalHitEvent,
    AttackHitEvent,
    DamageDealtEvent,
)


class TestParserSessionInitialization:
    """Test suite for ParserSession initialization."""

    def test_default_initialization(self) -> None:
        """Test parser initializes with default values."""
        parser = ParserSession()
        assert parser.player_name is None
        assert parser.parse_immunity is True
        assert not hasattr(parser, "target_ac")
        assert not hasattr(parser, "target_saves")
        assert not hasattr(parser, "target_attack_bonus")

    def test_initialization_with_player_name(self) -> None:
        """Test parser initializes with player name."""
        parser = ParserSession(player_name="TestPlayer")
        assert parser.player_name == "TestPlayer"

    def test_initialization_with_immunity_parsing(self) -> None:
        """Test parser initializes with immunity parsing enabled."""
        parser = ParserSession(parse_immunity=True)
        assert parser.parse_immunity is True


class TestDamageBreakdownParsing:
    """Test suite for parse_damage_breakdown method."""

    def test_parse_single_damage_type(self, parser: ParserSession) -> None:
        """Test parsing single damage type."""
        result = parser.parse_damage_breakdown("50 Physical")
        assert result == {"Physical": 50}

    def test_parse_multiple_damage_types(self, parser: ParserSession) -> None:
        """Test parsing multiple damage types."""
        result = parser.parse_damage_breakdown("30 Physical 20 Fire")
        assert result == {"Physical": 30, "Fire": 20}

    def test_parse_multiword_damage_types(self, parser: ParserSession) -> None:
        """Test parsing multi-word damage types."""
        result = parser.parse_damage_breakdown("50 Positive Energy 30 Divine 20 Pure")
        assert result == {"Positive Energy": 50, "Divine": 30, "Pure": 20}

    def test_parse_complex_breakdown(self, parser: ParserSession) -> None:
        """Test parsing complex damage breakdown with many types."""
        result = parser.parse_damage_breakdown(
            "21 Physical 4 Divine 3 Fire 13 Positive Energy 1 Pure 2 Magical"
        )
        assert result == {
            "Physical": 21,
            "Divine": 4,
            "Fire": 3,
            "Positive Energy": 13,
            "Pure": 1,
            "Magical": 2,
        }

    def test_parse_empty_string(self, parser: ParserSession) -> None:
        """Test parsing empty damage breakdown."""
        result = parser.parse_damage_breakdown("")
        assert result == {}

    def test_parse_with_extra_whitespace(self, parser: ParserSession) -> None:
        """Test parsing with extra whitespace."""
        result = parser.parse_damage_breakdown("  30  Physical   20  Fire  ")
        assert result == {"Physical": 30, "Fire": 20}

    def test_parse_multiword_damage_types_with_extra_whitespace(self, parser: ParserSession) -> None:
        """Whitespace normalization should preserve multi-word damage types."""
        result = parser.parse_damage_breakdown("  50   Positive   Energy   20   Negative  Energy ")
        assert result == {"Positive Energy": 50, "Negative Energy": 20}


class TestTimestampExtraction:
    """Test suite for extract_timestamp_from_line method."""

    def test_extract_valid_timestamp(self, parser: ParserSession) -> None:
        """Test extracting valid timestamp from log line."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Test message"
        result = parser.extract_timestamp_from_line(line)
        assert result is not None
        assert isinstance(result, datetime)
        assert result.hour == 14
        assert result.minute == 30
        assert result.second == 0

    def test_extract_timestamp_different_time(self, parser: ParserSession) -> None:
        """Test extracting different timestamp."""
        line = "[CHAT WINDOW TEXT] [Wed Dec 31 21:07:37] Test message"
        result = parser.extract_timestamp_from_line(line)
        assert result is not None
        assert result.hour == 21
        assert result.minute == 7
        assert result.second == 37

    def test_extract_timestamp_invalid_format(self, parser: ParserSession) -> None:
        """Test extracting timestamp from invalid format returns None."""
        line = "Invalid line without timestamp"
        result = parser.extract_timestamp_from_line(line)
        assert result is None

    def test_extract_timestamp_invalid_numeric_fields(self, parser: ParserSession) -> None:
        """Invalid numeric timestamp fields should return None without raising."""
        line = "[CHAT WINDOW TEXT] [Thu Jan xx 14:30:00] Test message"
        result = parser.extract_timestamp_from_line(line)
        assert result is None

    def test_extract_timestamp_invalid_calendar_date(self, parser: ParserSession) -> None:
        """Invalid calendar dates should return None without raising."""
        line = "[CHAT WINDOW TEXT] [Thu Feb 31 14:30:00] Test message"
        result = parser.extract_timestamp_from_line(line)
        assert result is None

    def test_extract_timestamp_missing_brackets(self, parser: ParserSession) -> None:
        """Test extracting timestamp without brackets returns None."""
        line = "Thu Jan 09 14:30:00 Test message"
        result = parser.extract_timestamp_from_line(line)
        assert result is None

    def test_extract_timestamp_preserves_date(self, parser: ParserSession) -> None:
        """Test that timestamp extraction preserves the date from the log.

        This is critical for correctly calculating elapsed time when gameplay
        crosses midnight. Without date preservation, a timestamp like 19:46:31
        on one day and 00:42:47 on the next day would be incorrectly calculated
        as negative time or 23+ hours elapsed.
        """
        # Parse two timestamps on consecutive days
        line1 = "[CHAT WINDOW TEXT] [Mon Jan 19 19:46:31] Woo damages Goblin: 10 (10 Physical)"
        line2 = "[CHAT WINDOW TEXT] [Tue Jan 20 00:42:47] Woo damages Goblin: 10 (10 Physical)"

        ts1 = parser.extract_timestamp_from_line(line1)
        ts2 = parser.extract_timestamp_from_line(line2)

        assert ts1 is not None
        assert ts2 is not None

        # Verify individual timestamp components
        assert ts1.day == 19
        assert ts1.hour == 19
        assert ts1.minute == 46
        assert ts1.second == 31

        assert ts2.day == 20
        assert ts2.hour == 0
        assert ts2.minute == 42
        assert ts2.second == 47

        # Verify elapsed time calculation is correct (not negative or ~24 hours)
        elapsed = ts2 - ts1
        elapsed_seconds = elapsed.total_seconds()

        # Expected elapsed time: ~4 hours, 56 minutes, 16 seconds = ~17776 seconds
        # Should be positive and less than 24 hours (86400 seconds)
        assert elapsed_seconds > 0, "Elapsed time should be positive when crossing midnight"
        assert elapsed_seconds < 86400, "Elapsed time should be less than 24 hours"
        assert 17700 < elapsed_seconds < 17800, f"Expected ~17776 seconds, got {elapsed_seconds}"

    def test_extract_timestamp_rolls_year_forward_across_december_to_january(self) -> None:
        session = ParserSession(anchor_year=2025)

        ts1 = session.extract_timestamp_from_line("[CHAT WINDOW TEXT] [Wed Dec 31 23:59:59] Test message")
        ts2 = session.extract_timestamp_from_line("[CHAT WINDOW TEXT] [Thu Jan 01 00:00:01] Test message")

        assert ts1 == datetime(2025, 12, 31, 23, 59, 59)
        assert ts2 == datetime(2026, 1, 1, 0, 0, 1)


class TestSplitParserLayers:
    """Test suite for direct LineParser and ParserSession usage."""

    def test_line_parser_parses_damage_without_session_state(self) -> None:
        parser = LineParser()
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)"
        timestamp = datetime(2026, 1, 9, 14, 30, 0)

        result = parser.parse_line(
            line,
            line_number=1,
            get_timestamp=lambda: timestamp,
        )

        assert result is not None
        assert result.type == "damage_dealt"
        assert result.timestamp == timestamp

    def test_parser_session_emits_death_snippet_without_logparser_facade(self) -> None:
        session = ParserSession(anchor_year=2026)
        session.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:34] HYDROXYS attacks Woo Wildrock: *hit*: (10 + 60 = 70)"
        )
        session.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] HYDROXYS killed Woo Wildrock"
        )

        result = session.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:37] Your God refuses to hear your prayers!"
        )

        assert result is not None
        assert result.type == "death_snippet"
        assert result.target == "Woo Wildrock"


class TestDamageDealtParsing:
    """Test suite for parsing damage_dealt lines."""

    def test_parse_basic_damage(self, parser: ParserSession) -> None:
        """Test parsing basic damage line."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'damage_dealt'
        assert result.attacker == 'Woo'
        assert result.target == 'Goblin'
        assert result.total_damage == 50
        assert result.damage_types == {'Physical': 30, 'Fire': 20}
        assert isinstance(result.timestamp, datetime)

    def test_parse_damage_with_multiword_types(self, parser: ParserSession) -> None:
        """Test parsing damage with multi-word damage types."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Lich: 100 (50 Positive Energy 30 Divine 20 Pure)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.damage_types == {'Positive Energy': 50, 'Divine': 30, 'Pure': 20}

    def test_parse_damage_player_filter_match(self, parser_with_player: ParserSession) -> None:
        """Test parsing damage when player matches filter."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] TestPlayer damages Goblin: 50 (50 Physical)"
        result = parser_with_player.parse_line(line)

        assert result is not None
        assert isinstance(result, DamageDealtEvent)
        assert result.attacker == 'TestPlayer'

    def test_parse_damage_player_filter_no_match(self, parser_with_player: ParserSession) -> None:
        """Damage events still emit normally even when player_name differs."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] OtherPlayer damages Goblin: 50 (50 Physical)"
        result = parser_with_player.parse_line(line)

        assert result is not None
        assert isinstance(result, DamageDealtEvent)
        assert result.attacker == "OtherPlayer"


class TestImmunityParsing:
    """Test suite for parsing immunity lines."""

    def test_parse_immunity_disabled(self, parser: ParserSession) -> None:
        """Test immunity parsing when disabled returns None."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire"
        result = parser.parse_line(line)
        assert result is None

    def test_parse_immunity_enabled_points(self, parser_with_immunity: ParserSession) -> None:
        """Test parsing immunity with 'point(s)'."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire"
        result = parser_with_immunity.parse_line(line)

        assert result is not None
        assert result.type == 'immunity'
        assert result.target == 'Goblin'
        assert result.damage_type == 'Fire'
        assert result.immunity_points == 10

    def test_parse_immunity_points_variant(self, parser_with_immunity: ParserSession) -> None:
        """Test parsing immunity with 'points'."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Orc : Damage Immunity absorbs 5 points of Cold"
        result = parser_with_immunity.parse_line(line)

        assert result is not None
        assert result.immunity_points == 5
        assert result.damage_type == 'Cold'

    def test_parse_immunity_point_singular(self, parser_with_immunity: ParserSession) -> None:
        """Test parsing immunity with 'point' (singular)."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Dragon : Damage Immunity absorbs 1 point of Fire"
        result = parser_with_immunity.parse_line(line)

        assert result is not None
        assert result.immunity_points == 1


class TestAttackParsing:
    """Test suite for parsing attack lines."""

    def test_parse_attack_hit(self, parser: ParserSession) -> None:
        """Test parsing attack hit."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (14 + 5 = 19)"
        result = parser.parse_line(line)

        assert result is not None
        assert isinstance(result, AttackHitEvent)
        assert result.type == 'attack_hit'
        assert result.attacker == 'Woo'
        assert result.target == 'Goblin'
        assert result.roll == 14
        assert result.bonus == 5
        assert result.total == 19

    def test_parse_attack_miss(self, parser: ParserSession) -> None:
        """Test parsing attack miss."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *miss*: (8 + 5 = 13)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_miss'
        assert result.roll == 8
        assert result.total == 13

    def test_parse_attack_critical_hit(self, parser: ParserSession) -> None:
        """Test parsing critical hit."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *critical hit*: (18 + 5 = 23)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit_critical'
        assert result.roll == 18

    def test_parse_attack_natural_1(self, parser: ParserSession) -> None:
        """Test parsing natural 1 miss."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *miss*: (1 + 5 = 6)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_miss'
        assert result.was_nat1 is True

    def test_parse_attack_natural_20(self, parser: ParserSession) -> None:
        """Test parsing natural 20 hit."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (20 + 5 = 25)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit'
        assert result.was_nat20 is True

    def test_parse_attack_preserves_totals_for_downstream_ac_tracking(self, parser: ParserSession) -> None:
        """Test attack events preserve totals for downstream AC tracking."""
        hit_line = "Woo attacks Goblin: *hit*: (16 + 5 = 21)"
        hit_result = parser.parse_line(hit_line)

        miss_line = "Woo attacks Goblin: *miss*: (10 + 5 = 15)"
        miss_result = parser.parse_line(miss_line)

        assert hit_result is not None
        assert hit_result.type == 'attack_hit'
        assert hit_result.target == 'Goblin'
        assert hit_result.total == 21
        assert miss_result is not None
        assert miss_result.type == 'attack_miss'
        assert miss_result.target == 'Goblin'
        assert miss_result.total == 15

    def test_parse_attack_emits_bonus_for_downstream_tracking(self, parser: ParserSession) -> None:
        """Test that parsing attacks emits bonus data for downstream tracking."""
        line = "Goblin attacks Woo: *hit*: (15 + 8 = 23)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.attacker == 'Goblin'
        assert result.bonus == 8

    def test_parse_concealment_miss_excluded_from_ac(self, parser: ParserSession) -> None:
        """Test that concealment misses are excluded from AC estimation.

        When an attack misses due to concealment (displacement, invisibility, etc.),
        the attack roll total doesn't reveal information about the target's AC.
        These should be completely excluded from AC tracking.
        """
        hit_result = parser.parse_line("Orc attacks Hero: *hit*: (10 + 30 = 40)")
        concealment_result = parser.parse_line(
            "Orc attacks Hero: *attacker miss chance: 50%*: (19 + 60 = 79)"
        )

        assert hit_result is not None
        assert hit_result.type == 'attack_hit'
        assert hit_result.total == 40
        assert concealment_result is not None
        assert concealment_result.type == 'attack_miss'
        assert concealment_result.is_concealment is True
        assert concealment_result.total == 79

    def test_parse_concealment_miss_does_not_drop_event(self, parser: ParserSession) -> None:
        """Concealment-only attacks should still emit miss events."""
        line = "Dragon attacks Mage: *attacker miss chance: 50%*: (15 + 70 = 85)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_miss'
        assert result.is_concealment is True
        assert result.target == 'Mage'

    def test_parse_concealment_with_regular_misses(self, parser: ParserSession) -> None:
        """Test that concealment misses don't interfere with regular AC estimation.

        Scenario: Enemy has displacement. Some attacks miss normally (too low roll),
        others miss due to concealment (high roll but concealment triggers).
        Only the normal misses should affect AC estimation.
        """
        miss_result = parser.parse_line("Warrior attacks DisplacedBoss: *miss*: (8 + 30 = 38)")
        concealment_result = parser.parse_line(
            "Warrior attacks DisplacedBoss: *attacker miss chance: 50%*: (18 + 30 = 48)"
        )
        hit_result = parser.parse_line("Warrior attacks DisplacedBoss: *hit*: (15 + 30 = 45)")

        assert miss_result is not None
        assert miss_result.type == 'attack_miss'
        assert miss_result.is_concealment is False
        assert miss_result.total == 38
        assert concealment_result is not None
        assert concealment_result.is_concealment is True
        assert hit_result is not None
        assert hit_result.type == 'attack_hit'
        assert hit_result.total == 45

    def test_parse_concealment_percentage_variations(self, parser: ParserSession) -> None:
        """Test parsing concealment misses with different percentages."""
        hit_result = parser.parse_line("Rogue attacks Target: *hit*: (10 + 40 = 50)")
        concealment_results = [
            parser.parse_line("Rogue attacks Target: *attacker miss chance: 20%*: (15 + 40 = 55)"),
            parser.parse_line("Rogue attacks Target: *attacker miss chance: 50%*: (18 + 40 = 58)"),
            parser.parse_line("Rogue attacks Target: *attacker miss chance: 100%*: (19 + 40 = 59)"),
        ]

        assert hit_result is not None
        assert hit_result.type == 'attack_hit'
        assert all(result is not None and result.is_concealment is True for result in concealment_results)

    def test_parse_target_concealed_without_outcome_is_ignored(self, parser: ParserSession) -> None:
        """No-outcome target-concealed lines should not emit attacks or affect stats."""
        line = (
            "[CHAT WINDOW TEXT] [Sat Oct 18 21:12:56] Attack Of Opportunity : Flurry of Blows : "
            "Woo Whirlwind attacks Cerberus : *target concealed: 50%* : (3 + 17 = 20)"
        )
        result = parser.parse_line(line)

        assert result is None

    def test_parse_target_concealed_with_explicit_outcome(self, parser: ParserSession) -> None:
        """Target-concealed lines with explicit outcome should parse as attacks."""
        line = (
            "[CHAT WINDOW TEXT] [Sat Oct 18 21:12:56] Attack Of Opportunity : Flurry of Blows : "
            "Woo Whirlwind attacks Cerberus : *target concealed: 50%* : "
            "(19 + 17 = 36) : *critical hit*"
        )
        result = parser.parse_line(line)

        assert result is not None
        assert isinstance(result, AttackCriticalHitEvent)
        assert result.type == 'attack_hit_critical'
        assert result.attacker == 'Woo Whirlwind'
        assert result.target == 'Cerberus'
        assert result.roll == 19
        assert result.bonus == 17
        assert result.total == 36

    def test_parse_target_concealed_malformed_roll_falls_back_cleanly(self, parser: ParserSession) -> None:
        """Malformed target-concealed fast-path lines should fail cleanly."""
        line = (
            "[CHAT WINDOW TEXT] [Sat Oct 18 21:12:56] Woo Whirlwind attacks Cerberus : "
            "*target concealed: 50%* : (19 + seventeen = 36) : *hit*"
        )
        result = parser.parse_line(line)

        assert result is None

    def test_parse_concealment_real_world_scenario(self, parser: ParserSession) -> None:
        """Test real-world scenario from user's logs.

        This reproduces the bug where Woo Wildrock's AC was incorrectly estimated
        as 97 due to concealment misses being treated as regular misses.
        """
        results = [
            parser.parse_line("Enemy attacks WooWildrock: *hit*: (10 + 50 = 60)"),
            parser.parse_line("Enemy attacks WooWildrock: *hit*: (12 + 45 = 57)"),
            parser.parse_line("Enemy attacks WooWildrock: *miss*: (2 + 53 = 55)"),
            parser.parse_line("Enemy attacks WooWildrock: *attacker miss chance: 50%*: (19 + 60 = 79)"),
            parser.parse_line("Enemy attacks WooWildrock: *attacker miss chance: 50%*: (18 + 56 = 74)"),
            parser.parse_line("Enemy attacks WooWildrock: *hit*: (11 + 45 = 56)"),
        ]

        assert [result.type if result else None for result in results] == [
            'attack_hit',
            'attack_hit',
            'attack_miss',
            'attack_miss',
            'attack_miss',
            'attack_hit',
        ]
        assert results[3] is not None and results[3].is_concealment is True
        assert results[4] is not None and results[4].is_concealment is True


class TestEpicDodgeParsing:
    """Test suite for parsing Epic Dodge indicator lines."""

    def test_parse_epic_dodge_marks_target(self, parser: ParserSession) -> None:
        """Test parsing Epic Dodge line emits target info."""
        line = "[CHAT WINDOW TEXT] [Fri Feb 13 11:34:03] Epic Undead Monk : Epic Dodge : Attack evaded"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == "epic_dodge"
        assert result.target == "Epic Undead Monk"

    def test_parse_epic_dodge_emits_event(self, parser: ParserSession) -> None:
        """Test Epic Dodge line emits a queue event for downstream consumers."""
        line = "Epic Undead Monk : Epic Dodge : Attack evaded"
        result = parser.parse_line(line)
        assert result is not None
        assert result.type == "epic_dodge"
        assert result.target == "Epic Undead Monk"

    def test_parse_epic_dodge_preserves_target_name(self, parser: ParserSession) -> None:
        """Test Epic Dodge parsing preserves complex target names."""
        line = "[CHAT WINDOW TEXT] [Fri Feb 13 11:34:03] 10 AC DUMMY - Chaotic Evil - Boss Damage Reduction : Epic Dodge : Attack evaded"
        result = parser.parse_line(line)

        target = "10 AC DUMMY - Chaotic Evil - Boss Damage Reduction"
        assert result is not None
        assert result.target == target


class TestAttackPrefixCombinations:
    """Test suite for parsing attack lines with various prefix combinations.

    Tests the fix for handling ability names (e.g., Flurry of Blows, Sneak Attack),
    Off Hand attacks, and Attack of Opportunity prefixes in all combinations.
    """

    def test_parse_attack_with_single_ability(self, parser: ParserSession) -> None:
        """Test parsing attack with single ability prefix (Flurry of Blows)."""
        line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:08:04] Flurry of Blows : Woo Whirlwind attacks 10 AC DUMMY - Chaotic Evil - Boss Damage Reduction : *hit* : (5 + 66 = 71)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit'
        assert result.attacker == 'Woo Whirlwind'
        assert result.target == '10 AC DUMMY - Chaotic Evil - Boss Damage Reduction'
        assert result.roll == 5
        assert result.bonus == 66
        assert result.total == 71

    def test_parse_attack_with_two_abilities(self, parser: ParserSession) -> None:
        """Test parsing attack with two ability prefixes (Flurry of Blows + Sneak Attack)."""
        line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:22:07] Flurry of Blows : Sneak Attack : Woo Whirlwind attacks 10 AC DUMMY - Chaotic Evil - Boss Damage Reduction : *hit* : (5 + 57 = 62)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit'
        assert result.attacker == 'Woo Whirlwind'
        assert result.target == '10 AC DUMMY - Chaotic Evil - Boss Damage Reduction'
        assert result.roll == 5
        assert result.bonus == 57
        assert result.total == 62

    def test_parse_attack_off_hand_only(self, parser: ParserSession) -> None:
        """Test parsing off-hand attack without ability prefix."""
        line = "[CHAT WINDOW TEXT] [Wed Dec 31 21:07:58] Off Hand : Woo Wildrock attacks Ash-Tusk Clan High Priest : *hit* : (6 + 66 = 72)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit'
        assert result.attacker == 'Woo Wildrock'
        assert result.target == 'Ash-Tusk Clan High Priest'
        assert result.roll == 6
        assert result.bonus == 66
        assert result.total == 72

    def test_parse_attack_off_hand_with_single_ability(self, parser: ParserSession) -> None:
        """Test parsing off-hand attack with single ability (Death Attack)."""
        line = "[CHAT WINDOW TEXT] [Wed Dec 31 21:08:21] Off Hand : Death Attack : GENERAL KORGAN attacks Woo Wildrock : *critical hit* : (18 + 65 = 83 : Threat Roll: 8 + 65 = 73)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit_critical'
        assert result.attacker == 'GENERAL KORGAN'
        assert result.target == 'Woo Wildrock'
        assert result.roll == 18
        assert result.bonus == 65
        assert result.total == 83

    def test_parse_attack_with_threat_roll_hit(self, parser: ParserSession) -> None:
        """Threat-roll hit lines should still parse as hits."""
        line = (
            "[CHAT WINDOW TEXT] [Sat Oct 18 21:15:19] Tyrmon's Fighter attacks Cerberus : "
            "*hit* : (20 + 50 = 70 : Threat Roll: 1 + 50 = 51)"
        )
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == "attack_hit"
        assert result.attacker == "Tyrmon's Fighter"
        assert result.target == "Cerberus"
        assert result.roll == 20
        assert result.bonus == 50
        assert result.total == 70

    def test_parse_attack_off_hand_with_two_abilities(self, parser: ParserSession) -> None:
        """Test parsing off-hand attack with two abilities (Flurry of Blows + Sneak Attack)."""
        line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:23:38] Off Hand : Flurry of Blows : Sneak Attack : Woo Whirlwind attacks 10 AC DUMMY - Chaotic Evil - Boss Damage Reduction : *hit* : (9 + 45 = 54)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit'
        assert result.attacker == 'Woo Whirlwind'
        assert result.target == '10 AC DUMMY - Chaotic Evil - Boss Damage Reduction'
        assert result.roll == 9
        assert result.bonus == 45
        assert result.total == 54

    def test_parse_attack_of_opportunity_only(self, parser: ParserSession) -> None:
        """Test parsing attack of opportunity without other prefixes."""
        line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:08:04] Attack Of Opportunity : Woo Whirlwind attacks 10 AC DUMMY : *hit* : (5 + 66 = 71)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit'
        assert result.attacker == 'Woo Whirlwind'
        assert result.target == '10 AC DUMMY'
        assert result.roll == 5
        assert result.bonus == 66
        assert result.total == 71

    def test_parse_attack_no_prefix(self, parser: ParserSession) -> None:
        """Test parsing basic attack without any prefix (regression test)."""
        line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:08:54] Woo Whirlwind attacks 10 AC DUMMY - Chaotic Evil - Boss Damage Reduction : *hit* : (10 + 61 = 71)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit'
        assert result.attacker == 'Woo Whirlwind'
        assert result.target == '10 AC DUMMY - Chaotic Evil - Boss Damage Reduction'
        assert result.roll == 10
        assert result.bonus == 61
        assert result.total == 71

    def test_parse_attack_with_ability_miss(self, parser: ParserSession) -> None:
        """Test parsing miss with ability prefix."""
        line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:08:04] Flurry of Blows : Woo Whirlwind attacks 10 AC DUMMY : *miss* : (3 + 66 = 69)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_miss'
        assert result.attacker == 'Woo Whirlwind'
        assert result.target == '10 AC DUMMY'
        assert result.roll == 3
        assert result.total == 69

    def test_parse_attack_with_ability_preserves_roll_data(self, parser: ParserSession) -> None:
        """Test that attacks with ability prefixes preserve roll data."""
        hit_line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:22:07] Flurry of Blows : Sneak Attack : Woo Whirlwind attacks 10 AC DUMMY : *hit* : (5 + 57 = 62)"
        hit_result = parser.parse_line(hit_line)

        miss_line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:22:08] Flurry of Blows : Woo Whirlwind attacks 10 AC DUMMY : *miss* : (2 + 57 = 59)"
        miss_result = parser.parse_line(miss_line)

        assert hit_result is not None
        assert hit_result.total == 62
        assert miss_result is not None
        assert miss_result.total == 59

    def test_parse_attack_with_three_word_ability(self, parser: ParserSession) -> None:
        """Test parsing attack with multi-word ability names."""
        line = "[CHAT WINDOW TEXT] [Sun Jan 11 20:08:04] Circle Kick Attack : Woo Whirlwind attacks Training Dummy : *hit* : (15 + 50 = 65)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'attack_hit'
        assert result.attacker == 'Woo Whirlwind'
        assert result.target == 'Training Dummy'
        assert result.roll == 15
        assert result.total == 65

    def test_parse_attack_with_plus_sign_ability_prefix(self, parser: ParserSession) -> None:
        """Ability prefixes containing '+' should still preserve the attacker name."""
        line = (
            "[CHAT WINDOW TEXT] [Fri May 23 20:41:07] Sneak Attack + Death Attack : "
            "SpecialistBuby attacks Cursed Beholder Tyrant : *hit* : (12 + 62 = 74)"
        )
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == "attack_hit"
        assert result.attacker == "SpecialistBuby"
        assert result.target == "Cursed Beholder Tyrant"
        assert result.roll == 12
        assert result.bonus == 62
        assert result.total == 74


class TestSaveParsing:
    """Test suite for parsing save lines."""

    def test_parse_fortitude_save(self, parser: ParserSession) -> None:
        """Test parsing fortitude save."""
        line = "SAVE: Goblin: Fortitude Save: *success*: (12 + 3 = 15 vs. DC: 20)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.type == 'save'
        assert result.target == 'Goblin'
        assert result.save_type == 'fort'
        assert result.bonus == 3

    def test_parse_reflex_save(self, parser: ParserSession) -> None:
        """Test parsing reflex save."""
        line = "Orc: Reflex Save: *failed*: (6 + 2 = 8 vs. DC: 15)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.save_type == 'ref'
        assert result.bonus == 2

    def test_parse_will_save(self, parser: ParserSession) -> None:
        """Test parsing will save."""
        line = "Dragon: Will Save: *success*: (16 + 10 = 26 vs. DC: 25)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.save_type == 'will'
        assert result.bonus == 10

    def test_parse_save_preserves_bonus_for_downstream_tracking(self, parser: ParserSession) -> None:
        """Test that parsing saves preserves bonus data."""
        line = "SAVE: Goblin: Fortitude Save: *success*: (12 + 5 = 17 vs. DC: 20)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.target == 'Goblin'
        assert result.save_type == 'fort'
        assert result.bonus == 5


class TestEdgeCases:
    """Test suite for edge cases and error handling."""

    def test_parse_empty_line(self, parser: ParserSession) -> None:
        """Test parsing empty line returns None."""
        result = parser.parse_line("")
        assert result is None

    def test_parse_whitespace_only(self, parser: ParserSession) -> None:
        """Test parsing whitespace-only line returns None."""
        result = parser.parse_line("   \t\n   ")
        assert result is None

    def test_parse_invalid_line(self, parser: ParserSession) -> None:
        """Test parsing line with no matching pattern returns None."""
        result = parser.parse_line("This is not a valid log line")
        assert result is None

    def test_parse_line_without_timestamp(self, parser: ParserSession) -> None:
        """Test parsing line without timestamp uses current time."""
        line = "Woo attacks Goblin: *hit*: (14 + 5 = 19)"
        result = parser.parse_line(line)

        assert result is not None
        assert isinstance(result.timestamp, datetime)

    def test_parse_line_with_malformed_timestamp_uses_single_cached_fallback_now(
        self,
        parser: ParserSession,
        monkeypatch,
    ) -> None:
        """Malformed timestamps should call datetime.now() only once per line parse."""
        calls = 0

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                nonlocal calls
                calls += 1
                return cls(2026, 3, 9, 12, 0, 0)

        monkeypatch.setattr(parser_session_module, "datetime", FixedDatetime)

        line = "[CHAT WINDOW TEXT] [Thu Jan xx 14:30:00] Woo attacks Goblin: *hit*: (14 + 5 = 19)"
        result = parser.parse_line(line)

        assert result is not None
        assert result.timestamp == FixedDatetime(2026, 3, 9, 12, 0, 0)
        assert calls == 1

    def test_parse_malformed_damage_breakdown(self, parser: ParserSession) -> None:
        """Test parsing malformed damage breakdown."""
        result = parser.parse_damage_breakdown("Invalid 50 Stuff")
        # Should handle gracefully, returning what it can parse
        assert isinstance(result, dict)


class TestDeathSnippetParsing:
    """Test suite for death snippet extraction behavior."""

    def test_prayer_line_triggers_death_snippet_event(self, parser: ParserSession) -> None:
        parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:34] HYDROXYS THE TRAVELER OF PLANES attacks Woo Wildrock: *hit*: (10 + 60 = 70)"
        )
        parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:35] woo wildrock attacks HYDROXYS THE TRAVELER OF PLANES: *miss*: (1 + 40 = 41)"
        )
        parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] HYDROXYS THE TRAVELER OF PLANES killed Woo Wildrock"
        )

        result = parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"
        )

        assert result is not None
        assert result.type == 'death_snippet'
        assert result.target == 'Woo Wildrock'
        assert result.killer == 'HYDROXYS THE TRAVELER OF PLANES'
        assert result.lines[-1].endswith("Your God refuses to hear your prayers!")

        snippet_joined = "\n".join(result.lines)
        assert "HYDROXYS THE TRAVELER OF PLANES attacks Woo Wildrock" in snippet_joined
        # Case-sensitive matching: lower-case name line should not be included.
        assert "woo wildrock attacks" not in snippet_joined

    def test_prayer_line_without_recent_kill_within_cap_returns_none(self, parser: ParserSession) -> None:
        parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:30] Monster killed Hero"
        )
        for i in range(501):
            parser.parse_line(
                f"[CHAT WINDOW TEXT] [Tue Jan 13 19:59:31] Filler line {i}"
            )

        result = parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"
        )
        assert result is None

    def test_death_snippet_uses_exact_token_boundaries_case_sensitive(self, parser: ParserSession) -> None:
        parser.parse_line("[CHAT WINDOW TEXT] [Tue Jan 13 19:59:30] Orc attacks Ann: *hit*: (10 + 10 = 20)")
        parser.parse_line("[CHAT WINDOW TEXT] [Tue Jan 13 19:59:31] Orc attacks Anna: *hit*: (10 + 10 = 20)")
        parser.parse_line("[CHAT WINDOW TEXT] [Tue Jan 13 19:59:32] Orc killed Ann")

        result = parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:33] Your God refuses to hear your prayers!"
        )

        assert result is not None
        snippet_joined = "\n".join(result.lines)
        assert "Orc attacks Ann" in snippet_joined
        assert "Orc attacks Anna" not in snippet_joined

    def test_whisper_identifies_character_name_and_emits_event(self, parser: ParserSession) -> None:
        result = parser.parse_line(
            "[CHAT WINDOW TEXT] [Sat Mar  7 17:53:39] Woo Wildrock: [Whisper] wooparseme"
        )

        assert result is not None
        assert result.type == "death_character_identified"
        assert result.character_name == "Woo Wildrock"
        assert parser.death_character_name == "Woo Wildrock"

    def test_whisper_token_matching_is_case_insensitive(self, parser: ParserSession) -> None:
        result = parser.parse_line(
            "[CHAT WINDOW TEXT] [Sat Mar  7 17:53:39] Woo Wildrock: [Whisper] WoOPaRsEmE"
        )
        assert result is not None
        assert result.type == "death_character_identified"
        assert result.character_name == "Woo Wildrock"

    def test_character_known_uses_killed_line_and_ignores_fallback(self, parser: ParserSession) -> None:
        parser.set_death_character_name("Woo Wildrock")
        parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:34] HYDROXYS attacks Woo Wildrock: *hit*: (10 + 60 = 70)"
        )
        death_event = parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] HYDROXYS killed Woo Wildrock"
        )

        assert death_event is not None
        assert death_event.type == "death_snippet"
        assert death_event.target == "Woo Wildrock"
        assert death_event.killer == "HYDROXYS"
        assert death_event.lines[-1].endswith("HYDROXYS killed Woo Wildrock")

        fallback_event = parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:37] Your God refuses to hear your prayers!"
        )
        assert fallback_event is None

    def test_character_known_requires_case_sensitive_target_match(self, parser: ParserSession) -> None:
        parser.set_death_character_name("Woo Wildrock")
        result = parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] HYDROXYS killed woo wildrock"
        )
        assert result is None

    def test_fallback_line_can_be_customized(self, parser: ParserSession) -> None:
        parser.set_death_fallback_line("You have fallen.")
        parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:34] HYDROXYS killed Woo Wildrock"
        )
        result = parser.parse_line(
            "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] You have fallen."
        )

        assert result is not None
        assert result.type == "death_snippet"
        assert result.target == "Woo Wildrock"

