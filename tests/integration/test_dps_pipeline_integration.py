"""Integration tests for full DPS calculation pipeline.

Tests the complete flow: log parsing → storage → DPS service → formatted output.
"""

import pytest
from pathlib import Path
from datetime import datetime, timedelta

from app.parser import LogParser
from app.storage import DataStore
from app.services.dps_service import DPSCalculationService
from app.utils import parse_and_import_file


class TestDPSPipelineIntegration:
    """Test suite for complete DPS calculation pipeline."""

    def test_complete_dps_pipeline(self, temp_log_dir: Path) -> None:
        """Test complete pipeline from log file to DPS display."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 100 (60 Fire 40 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo attacks Goblin: *hit*: (15 + 5 = 20)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Woo damages Goblin: 50 (30 Fire 20 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:06] Woo attacks Goblin: *hit*: (16 + 5 = 21)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:10] Rogue damages Orc: 80 (80 Cold)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:11] Rogue attacks Orc: *miss*: (8 + 8 = 16)
"""
        log_file.write_text(content)

        # Parse file
        parser = LogParser()
        database = DataStore()
        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        # Create DPS service
        dps_service = DPSCalculationService(database)

        # Get DPS display data
        dps_list = dps_service.get_dps_display_data(target_filter="All")

        # Should have data for both characters
        assert len(dps_list) == 2

        characters = {d['character'] for d in dps_list}
        assert 'Woo' in characters
        assert 'Rogue' in characters

        # Check that hit rates are included
        for dps_info in dps_list:
            assert 'hit_rate' in dps_info
            assert dps_info['hit_rate'] >= 0.0

    def test_dps_with_target_filtering(self, temp_log_dir: Path) -> None:
        """Test DPS calculation with target filtering."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 100 (100 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Woo damages Orc: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:10] Rogue damages Goblin: 80 (80 Cold)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)

        # Filter by Goblin
        dps_list = dps_service.get_dps_display_data(target_filter="Goblin")

        # Should only include damage to Goblin
        total_damage = sum(d['total_damage'] for d in dps_list)
        assert total_damage == 180  # 100 + 80

    def test_dps_per_character_mode(self, temp_log_dir: Path) -> None:
        """Test DPS calculation in per_character mode."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 100 (100 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:10] Woo damages Goblin: 50 (50 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)
        dps_service.set_time_tracking_mode("per_character")

        dps_list = dps_service.get_dps_display_data()

        assert len(dps_list) == 1
        assert dps_list[0]['character'] == 'Woo'
        assert dps_list[0]['total_damage'] == 150

    def test_dps_global_mode(self, temp_log_dir: Path) -> None:
        """Test DPS calculation in global mode."""
        log_file = temp_log_dir / "test.txt"

        base_time = "[Thu Jan 09 14:30:00]"
        content = f"""[CHAT WINDOW TEXT] {base_time} Woo damages Goblin: 100 (100 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:10] Rogue damages Orc: 50 (50 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)
        dps_service.set_time_tracking_mode("global")

        # Global start time should be set automatically
        assert dps_service.global_start_time is not None

        dps_list = dps_service.get_dps_display_data()

        # Both characters should use same time window
        assert len(dps_list) == 2

    def test_damage_type_breakdown(self, temp_log_dir: Path) -> None:
        """Test damage type breakdown in full pipeline."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Dragon: 100 (60 Fire 40 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Woo damages Dragon: 50 (30 Fire 20 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)

        breakdown = dps_service.get_damage_type_breakdown("Woo", target_filter="All")

        assert len(breakdown) == 2

        # Sorted by total damage descending
        assert breakdown[0]['damage_type'] == 'Fire'
        assert breakdown[0]['total_damage'] == 90
        assert breakdown[1]['damage_type'] == 'Physical'
        assert breakdown[1]['total_damage'] == 60

    def test_hit_rate_integration(self, temp_log_dir: Path) -> None:
        """Test hit rate calculation integrated with DPS."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (15 + 5 = 20)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo damages Goblin: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo attacks Goblin: *hit*: (16 + 5 = 21)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Woo damages Goblin: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:04] Woo attacks Goblin: *miss*: (8 + 5 = 13)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Woo attacks Goblin: *hit*: (17 + 5 = 22)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:06] Woo damages Goblin: 50 (50 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)
        dps_list = dps_service.get_dps_display_data()

        assert len(dps_list) == 1
        woo_data = dps_list[0]

        # Hit rate should be calculated: 3 hits, 1 miss = 75%
        assert woo_data['hit_rate'] == pytest.approx(75.0, abs=0.1)

    def test_multiple_characters_and_targets(self, temp_log_dir: Path) -> None:
        """Test pipeline with multiple characters and targets."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 100 (100 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Rogue damages Goblin: 80 (80 Cold)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Mage damages Orc: 120 (120 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Woo damages Orc: 50 (50 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)

        # All targets
        dps_all = dps_service.get_dps_display_data(target_filter="All")
        assert len(dps_all) == 3

        # Filter by Goblin
        dps_goblin = dps_service.get_dps_display_data(target_filter="Goblin")
        assert len(dps_goblin) == 2  # Woo and Rogue

        # Filter by Orc
        dps_orc = dps_service.get_dps_display_data(target_filter="Orc")
        assert len(dps_orc) == 2  # Woo and Mage

    def test_auto_refresh_mode_detection(self, temp_log_dir: Path) -> None:
        """Test auto-refresh mode detection for global mode."""
        log_file = temp_log_dir / "test.txt"
        log_file.write_text("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 100 (100 Physical)\n")

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)

        # Test mode switching
        dps_service.set_time_tracking_mode("per_character")
        assert dps_service.time_tracking_mode == "per_character"

        dps_service.set_time_tracking_mode("global")
        assert dps_service.time_tracking_mode == "global"


class TestComplexScenarios:
    """Test suite for complex real-world scenarios."""

    def test_long_combat_session(self, temp_log_dir: Path) -> None:
        """Test processing a long combat session."""
        log_file = temp_log_dir / "test.txt"

        # Generate a long combat session
        lines = []
        for i in range(100):
            lines.append(f"[CHAT WINDOW TEXT] [Thu Jan 09 14:30:{i:02d}] Woo damages Goblin: {10+i} (10 Physical)\n")

        log_file.write_text("".join(lines))

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)
        dps_list = dps_service.get_dps_display_data()

        assert len(dps_list) == 1
        assert dps_list[0]['total_damage'] > 0

    def test_immunity_with_dps_calculation(self, temp_log_dir: Path) -> None:
        """Test DPS calculation with immunity tracking."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Dragon: 50 (30 Physical 20 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Dragon : Damage Immunity absorbs 10 point(s) of Fire
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Woo damages Dragon: 50 (30 Physical 20 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Dragon : Damage Immunity absorbs 10 points of Fire
"""
        log_file.write_text(content)

        parser = LogParser(parse_immunity=True)
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        # Check immunity was tracked
        immunity_info = database.get_immunity_for_target_and_type("Dragon", "Fire")
        assert immunity_info['max_immunity'] == 10

        # Check DPS still calculates correctly
        dps_service = DPSCalculationService(database)
        dps_list = dps_service.get_dps_display_data()

        assert len(dps_list) == 1
        assert dps_list[0]['total_damage'] == 100

