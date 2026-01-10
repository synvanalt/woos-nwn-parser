"""Unit tests for LogParser.

Tests regex pattern matching, damage parsing, immunity parsing,
attack parsing, save parsing, and player filtering.
"""

import pytest
from datetime import datetime

from app.parser import LogParser
from app.models import EnemyAC, EnemySaves, TargetAttackBonus


class TestLogParserInitialization:
    """Test suite for LogParser initialization."""

    def test_default_initialization(self) -> None:
        """Test parser initializes with default values."""
        parser = LogParser()
        assert parser.player_name is None
        assert parser.parse_immunity is False
        assert parser.current_target is None
        assert len(parser.current_damage_types) == 0
        assert len(parser.target_ac) == 0
        assert len(parser.target_saves) == 0
        assert len(parser.target_attack_bonus) == 0

    def test_initialization_with_player_name(self) -> None:
        """Test parser initializes with player name."""
        parser = LogParser(player_name="TestPlayer")
        assert parser.player_name == "TestPlayer"

    def test_initialization_with_immunity_parsing(self) -> None:
        """Test parser initializes with immunity parsing enabled."""
        parser = LogParser(parse_immunity=True)
        assert parser.parse_immunity is True


class TestDamageBreakdownParsing:
    """Test suite for parse_damage_breakdown method."""

    def test_parse_single_damage_type(self, parser: LogParser) -> None:
        """Test parsing single damage type."""
        result = parser.parse_damage_breakdown("50 Physical")
        assert result == {"Physical": 50}

    def test_parse_multiple_damage_types(self, parser: LogParser) -> None:
        """Test parsing multiple damage types."""
        result = parser.parse_damage_breakdown("30 Physical 20 Fire")
        assert result == {"Physical": 30, "Fire": 20}

    def test_parse_multiword_damage_types(self, parser: LogParser) -> None:
        """Test parsing multi-word damage types."""
        result = parser.parse_damage_breakdown("50 Positive Energy 30 Divine 20 Pure")
        assert result == {"Positive Energy": 50, "Divine": 30, "Pure": 20}

    def test_parse_complex_breakdown(self, parser: LogParser) -> None:
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

    def test_parse_empty_string(self, parser: LogParser) -> None:
        """Test parsing empty damage breakdown."""
        result = parser.parse_damage_breakdown("")
        assert result == {}

    def test_parse_with_extra_whitespace(self, parser: LogParser) -> None:
        """Test parsing with extra whitespace."""
        result = parser.parse_damage_breakdown("  30  Physical   20  Fire  ")
        assert result == {"Physical": 30, "Fire": 20}


class TestTimestampExtraction:
    """Test suite for extract_timestamp_from_line method."""

    def test_extract_valid_timestamp(self, parser: LogParser) -> None:
        """Test extracting valid timestamp from log line."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Test message"
        result = parser.extract_timestamp_from_line(line)
        assert result is not None
        assert isinstance(result, datetime)
        assert result.hour == 14
        assert result.minute == 30
        assert result.second == 0

    def test_extract_timestamp_different_time(self, parser: LogParser) -> None:
        """Test extracting different timestamp."""
        line = "[CHAT WINDOW TEXT] [Wed Dec 31 21:07:37] Test message"
        result = parser.extract_timestamp_from_line(line)
        assert result is not None
        assert result.hour == 21
        assert result.minute == 7
        assert result.second == 37

    def test_extract_timestamp_invalid_format(self, parser: LogParser) -> None:
        """Test extracting timestamp from invalid format returns None."""
        line = "Invalid line without timestamp"
        result = parser.extract_timestamp_from_line(line)
        assert result is None

    def test_extract_timestamp_missing_brackets(self, parser: LogParser) -> None:
        """Test extracting timestamp without brackets returns None."""
        line = "Thu Jan 09 14:30:00 Test message"
        result = parser.extract_timestamp_from_line(line)
        assert result is None


class TestDamageDealtParsing:
    """Test suite for parsing damage_dealt lines."""

    def test_parse_basic_damage(self, parser: LogParser) -> None:
        """Test parsing basic damage line."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['type'] == 'damage_dealt'
        assert result['attacker'] == 'Woo'
        assert result['target'] == 'Goblin'
        assert result['total_damage'] == 50
        assert result['damage_types'] == {'Physical': 30, 'Fire': 20}
        assert isinstance(result['timestamp'], datetime)

    def test_parse_damage_with_multiword_types(self, parser: LogParser) -> None:
        """Test parsing damage with multi-word damage types."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Lich: 100 (50 Positive Energy 30 Divine 20 Pure)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['damage_types'] == {'Positive Energy': 50, 'Divine': 30, 'Pure': 20}

    def test_parse_damage_player_filter_match(self, parser_with_player: LogParser) -> None:
        """Test parsing damage when player matches filter."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] TestPlayer damages Goblin: 50 (50 Physical)"
        result = parser_with_player.parse_line(line)

        assert result is not None
        assert result['attacker'] == 'TestPlayer'
        assert result['filtered_for_player'] is False

    def test_parse_damage_player_filter_no_match(self, parser_with_player: LogParser) -> None:
        """Test parsing damage when player doesn't match filter."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] OtherPlayer damages Goblin: 50 (50 Physical)"
        result = parser_with_player.parse_line(line)

        # Parser still returns the data but marks it as filtered
        assert result is not None
        assert result['filtered_for_player'] is True


class TestImmunityParsing:
    """Test suite for parsing immunity lines."""

    def test_parse_immunity_disabled(self, parser: LogParser) -> None:
        """Test immunity parsing when disabled returns None."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire"
        result = parser.parse_line(line)
        assert result is None

    def test_parse_immunity_enabled_points(self, parser_with_immunity: LogParser) -> None:
        """Test parsing immunity with 'point(s)'."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire"
        result = parser_with_immunity.parse_line(line)

        assert result is not None
        assert result['type'] == 'immunity'
        assert result['target'] == 'Goblin'
        assert result['damage_type'] == 'Fire'
        assert result['immunity_points'] == 10

    def test_parse_immunity_points_variant(self, parser_with_immunity: LogParser) -> None:
        """Test parsing immunity with 'points'."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Orc : Damage Immunity absorbs 5 points of Cold"
        result = parser_with_immunity.parse_line(line)

        assert result is not None
        assert result['immunity_points'] == 5
        assert result['damage_type'] == 'Cold'

    def test_parse_immunity_point_singular(self, parser_with_immunity: LogParser) -> None:
        """Test parsing immunity with 'point' (singular)."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Dragon : Damage Immunity absorbs 1 point of Fire"
        result = parser_with_immunity.parse_line(line)

        assert result is not None
        assert result['immunity_points'] == 1


class TestAttackParsing:
    """Test suite for parsing attack lines."""

    def test_parse_attack_hit(self, parser: LogParser) -> None:
        """Test parsing attack hit."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (14 + 5 = 19)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['type'] == 'attack_hit'
        assert result['attacker'] == 'Woo'
        assert result['target'] == 'Goblin'
        assert result['roll'] == 14
        assert result['bonus'] == '5'
        assert result['total'] == 19

    def test_parse_attack_miss(self, parser: LogParser) -> None:
        """Test parsing attack miss."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *miss*: (8 + 5 = 13)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['type'] == 'attack_miss'
        assert result['roll'] == 8
        assert result['total'] == 13

    def test_parse_attack_critical_hit(self, parser: LogParser) -> None:
        """Test parsing critical hit."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *critical hit*: (18 + 5 = 23)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['type'] == 'attack_hit_critical'
        assert result['roll'] == 18

    def test_parse_attack_natural_1(self, parser: LogParser) -> None:
        """Test parsing natural 1 miss."""
        line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *miss*: (1 + 5 = 6)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['type'] == 'attack_miss'
        assert result['was_nat1'] is True

    def test_parse_attack_tracks_ac(self, parser: LogParser) -> None:
        """Test that parsing attacks updates AC tracking."""
        hit_line = "Woo attacks Goblin: *hit*: (16 + 5 = 21)"
        parser.parse_line(hit_line)

        assert 'Goblin' in parser.target_ac
        assert parser.target_ac['Goblin'].min_hit == 21

        miss_line = "Woo attacks Goblin: *miss*: (10 + 5 = 15)"
        parser.parse_line(miss_line)

        assert parser.target_ac['Goblin'].max_miss == 15

    def test_parse_attack_tracks_bonus(self, parser: LogParser) -> None:
        """Test that parsing attacks updates attack bonus tracking."""
        line = "Goblin attacks Woo: *hit*: (15 + 8 = 23)"
        parser.parse_line(line)

        assert 'Goblin' in parser.target_attack_bonus
        assert parser.target_attack_bonus['Goblin'].max_bonus == 8


class TestSaveParsing:
    """Test suite for parsing save lines."""

    def test_parse_fortitude_save(self, parser: LogParser) -> None:
        """Test parsing fortitude save."""
        line = "SAVE: Goblin: Fortitude Save: *success*: (12 + 3 = 15 vs. DC: 20)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['type'] == 'save'
        assert result['target'] == 'Goblin'
        assert result['save_type'] == 'fort'
        assert result['bonus'] == 3

    def test_parse_reflex_save(self, parser: LogParser) -> None:
        """Test parsing reflex save."""
        line = "Orc: Reflex Save: *failed*: (6 + 2 = 8 vs. DC: 15)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['save_type'] == 'ref'
        assert result['bonus'] == 2

    def test_parse_will_save(self, parser: LogParser) -> None:
        """Test parsing will save."""
        line = "Dragon: Will Save: *success*: (16 + 10 = 26 vs. DC: 25)"
        result = parser.parse_line(line)

        assert result is not None
        assert result['save_type'] == 'will'
        assert result['bonus'] == 10

    def test_parse_save_tracks_bonuses(self, parser: LogParser) -> None:
        """Test that parsing saves updates save tracking."""
        line = "SAVE: Goblin: Fortitude Save: *success*: (12 + 5 = 17 vs. DC: 20)"
        parser.parse_line(line)

        assert 'Goblin' in parser.target_saves
        assert parser.target_saves['Goblin'].fortitude == 5


class TestEdgeCases:
    """Test suite for edge cases and error handling."""

    def test_parse_empty_line(self, parser: LogParser) -> None:
        """Test parsing empty line returns None."""
        result = parser.parse_line("")
        assert result is None

    def test_parse_whitespace_only(self, parser: LogParser) -> None:
        """Test parsing whitespace-only line returns None."""
        result = parser.parse_line("   \t\n   ")
        assert result is None

    def test_parse_invalid_line(self, parser: LogParser) -> None:
        """Test parsing line with no matching pattern returns None."""
        result = parser.parse_line("This is not a valid log line")
        assert result is None

    def test_parse_line_without_timestamp(self, parser: LogParser) -> None:
        """Test parsing line without timestamp uses current time."""
        line = "Woo attacks Goblin: *hit*: (14 + 5 = 19)"
        result = parser.parse_line(line)

        assert result is not None
        assert isinstance(result['timestamp'], datetime)

    def test_parse_malformed_damage_breakdown(self, parser: LogParser) -> None:
        """Test parsing malformed damage breakdown."""
        result = parser.parse_damage_breakdown("Invalid 50 Stuff")
        # Should handle gracefully, returning what it can parse
        assert isinstance(result, dict)

