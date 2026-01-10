"""Integration tests for parser and storage.

Tests end-to-end log file parsing and data storage.
"""

import pytest
from pathlib import Path
from datetime import datetime

from app.parser import LogParser
from app.storage import DataStore
from app.utils import parse_and_import_file


class TestParserStorageIntegration:
    """Test suite for parser and storage integration."""

    def test_parse_and_store_damage_events(self, temp_log_dir: Path) -> None:
        """Test parsing damage events and storing in database."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Rogue damages Orc: 40 (40 Cold)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True
        assert len(database.events) == 3  # Physical, Fire, Cold
        assert len(database.dps_data) == 2  # Woo, Rogue

    def test_parse_and_store_immunity_events(self, temp_log_dir: Path) -> None:
        """Test parsing immunity events with matching damage."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire
"""
        log_file.write_text(content)

        parser = LogParser(parse_immunity=True)
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        # Check immunity was recorded
        immunity_info = database.get_immunity_for_target_and_type("Goblin", "Fire")
        assert immunity_info['max_immunity'] == 10
        assert immunity_info['sample_count'] == 1

    def test_parse_and_store_attack_events(self, temp_log_dir: Path) -> None:
        """Test parsing attack events and AC tracking."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (16 + 5 = 21)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo attacks Goblin: *miss*: (10 + 5 = 15)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo attacks Goblin: *critical hit*: (18 + 5 = 23)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True
        assert len(database.attacks) == 3

        # Check AC was tracked
        assert 'Goblin' in parser.target_ac
        assert parser.target_ac['Goblin'].min_hit == 21
        assert parser.target_ac['Goblin'].max_miss == 15

    def test_parse_and_store_save_events(self, temp_log_dir: Path) -> None:
        """Test parsing save events and tracking."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] SAVE: Goblin: Fortitude Save: *success*: (12 + 5 = 17 vs. DC: 20)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Goblin: Reflex Save: *failed*: (6 + 3 = 9 vs. DC: 15)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        # Check saves were tracked
        assert 'Goblin' in parser.target_saves
        assert parser.target_saves['Goblin'].fortitude == 5
        assert parser.target_saves['Goblin'].reflex == 3

    def test_parse_complete_combat_session(self, sample_combat_session: Path) -> None:
        """Test parsing a complete combat session."""
        parser = LogParser(parse_immunity=True)
        database = DataStore()

        result = parse_and_import_file(str(sample_combat_session), parser, database)

        assert result['success'] is True

        # Verify various data was collected
        assert len(database.events) > 0
        assert len(database.attacks) > 0
        assert len(database.dps_data) > 0

        # Verify targets were tracked
        targets = database.get_all_targets()
        assert "Goblin" in targets
        assert "Orc" in targets

        # Verify DPS calculations work
        dps_list = database.get_dps_data(time_tracking_mode="by_character")
        assert len(dps_list) > 0

    def test_parse_with_player_filter(self, temp_log_dir: Path) -> None:
        """Test parsing with player name filter."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] OtherPlayer damages Orc: 40 (40 Physical)
"""
        log_file.write_text(content)

        parser = LogParser(player_name="Woo")
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        # Both should be tracked for DPS
        assert len(database.dps_data) == 2

    def test_parse_multiword_damage_types(self, temp_log_dir: Path) -> None:
        """Test parsing damage with multi-word damage types."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Lich: 100 (50 Positive Energy 30 Divine 20 Pure)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True
        assert len(database.events) == 3

        damage_types = database.get_all_damage_types()
        assert "Positive Energy" in damage_types
        assert "Divine" in damage_types
        assert "Pure" in damage_types

    def test_dps_breakdown_by_type(self, temp_log_dir: Path) -> None:
        """Test DPS breakdown by damage type after parsing."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Dragon: 100 (60 Fire 40 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Woo damages Dragon: 50 (30 Fire 20 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        # Get damage breakdown
        breakdown = database.get_dps_breakdown_by_type("Woo", time_tracking_mode="by_character")

        assert len(breakdown) == 2

        # Find Fire and Physical in breakdown
        fire_breakdown = next((b for b in breakdown if b['damage_type'] == 'Fire'), None)
        physical_breakdown = next((b for b in breakdown if b['damage_type'] == 'Physical'), None)

        assert fire_breakdown is not None
        assert fire_breakdown['total_damage'] == 90
        assert physical_breakdown is not None
        assert physical_breakdown['total_damage'] == 60

    def test_hit_rate_calculation(self, temp_log_dir: Path) -> None:
        """Test hit rate calculation after parsing attacks."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (15 + 5 = 20)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo damages Goblin: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo attacks Goblin: *hit*: (16 + 5 = 21)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Woo damages Goblin: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:04] Woo attacks Goblin: *miss*: (8 + 5 = 13)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        # Get hit rate
        hit_rates = database.get_hit_rate_for_damage_dealers()

        assert "Woo" in hit_rates
        assert hit_rates["Woo"] == pytest.approx(66.67, abs=0.1)

    def test_target_summary(self, temp_log_dir: Path) -> None:
        """Test getting complete target summary after parsing."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (16 + 5 = 21)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo damages Goblin: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo attacks Goblin: *miss*: (10 + 5 = 15)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] SAVE: Goblin: Fortitude Save: *success*: (12 + 5 = 17 vs. DC: 20)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:04] Goblin attacks Woo: *hit*: (14 + 8 = 22)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        # Get target summary
        summary = database.get_all_targets_summary(parser)

        goblin_summary = next((s for s in summary if s['target'] == 'Goblin'), None)
        assert goblin_summary is not None
        assert goblin_summary['ab'] == '+8'  # Attack bonus
        assert goblin_summary['ac'] == '16-21'  # AC estimate
        assert goblin_summary['fortitude'] == '5'


class TestErrorHandling:
    """Test suite for error handling in integration."""

    def test_parse_malformed_lines(self, temp_log_dir: Path) -> None:
        """Test that malformed lines don't break parsing."""
        log_file = temp_log_dir / "test.txt"
        content = """This is not a valid line
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (50 Physical)
Another invalid line
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo attacks Goblin: *hit*: (15 + 5 = 20)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True
        assert len(database.events) == 1
        assert len(database.attacks) == 1

    def test_parse_empty_file(self, temp_log_dir: Path) -> None:
        """Test parsing empty file doesn't error."""
        log_file = temp_log_dir / "empty.txt"
        log_file.write_text("")

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True
        assert result['lines_processed'] == 0

