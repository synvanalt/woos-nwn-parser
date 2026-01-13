"""End-to-end tests for complete combat sessions.

Tests full application behavior from log file to all calculated metrics.
"""

import pytest
from pathlib import Path
from datetime import datetime

from app.parser import LogParser
from app.storage import DataStore
from app.services.dps_service import DPSCalculationService
from app.utils import parse_and_import_file, calculate_immunity_percentage


class TestCompleteCombatSession:
    """Test suite for complete combat session scenarios."""

    def test_full_party_combat(self, temp_log_dir: Path) -> None:
        """Test complete combat session with full party."""
        log_file = temp_log_dir / "combat.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Warrior attacks Goblin Chief: *hit*: (16 + 10 = 26)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Warrior damages Goblin Chief: 45 (45 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Rogue attacks Goblin Chief: *hit*: (18 + 8 = 26)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Rogue damages Goblin Chief: 60 (50 Physical 10 Acid)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:04] Mage attacks Goblin Chief: *hit*: (14 + 5 = 19)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Mage damages Goblin Chief: 80 (80 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Goblin Chief : Damage Immunity absorbs 20 point(s) of Fire
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:06] Cleric attacks Goblin Chief: *miss*: (8 + 6 = 14)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:07] Warrior attacks Goblin Chief: *hit*: (15 + 10 = 25)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:08] Warrior damages Goblin Chief: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:09] Rogue attacks Goblin Chief: *critical hit*: (20 + 8 = 28)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:10] Rogue damages Goblin Chief: 90 (75 Physical 15 Acid)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:11] SAVE: Goblin Chief: Fortitude Save: *failed*: (8 + 5 = 13 vs. DC: 20)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:12] Goblin Chief attacks Warrior: *hit*: (16 + 12 = 28)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:13] Goblin Chief damages Warrior: 25 (25 Physical)
"""
        log_file.write_text(content)

        # Parse with immunity tracking
        parser = LogParser(parse_immunity=True)
        database = DataStore()
        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True
        assert result['error'] is None

        # Verify all data was collected

        # 1. Damage Events
        assert len(database.events) > 0
        targets = database.get_all_targets()
        assert "Goblin Chief" in targets
        assert "Warrior" in targets

        # 2. DPS Calculations
        dps_service = DPSCalculationService(database)
        dps_list = dps_service.get_dps_display_data(target_filter="Goblin Chief")

        # Should have DPS for Warrior, Rogue, and Mage
        characters = {d['character'] for d in dps_list}
        assert 'Warrior' in characters
        assert 'Rogue' in characters
        assert 'Mage' in characters
        assert 'Cleric' not in characters  # Cleric missed, no damage

        # Verify total damage
        warrior_dps = next((d for d in dps_list if d['character'] == 'Warrior'), None)
        assert warrior_dps is not None
        assert warrior_dps['total_damage'] == 95  # 45 + 50

        rogue_dps = next((d for d in dps_list if d['character'] == 'Rogue'), None)
        assert rogue_dps is not None
        assert rogue_dps['total_damage'] == 150  # 60 + 90

        mage_dps = next((d for d in dps_list if d['character'] == 'Mage'), None)
        assert mage_dps is not None
        assert mage_dps['total_damage'] == 80

        # 3. Hit Rates
        warrior_hit_rate = warrior_dps['hit_rate']
        assert warrior_hit_rate == 100.0  # 2 hits, 0 misses

        rogue_hit_rate = rogue_dps['hit_rate']
        assert rogue_hit_rate == 100.0  # 1 hit, 1 crit, 0 misses

        mage_hit_rate = mage_dps['hit_rate']
        assert mage_hit_rate == 100.0  # 1 hit, 0 misses

        # 4. Attack Stats
        stats = database.get_attack_stats_for_target("Goblin Chief")
        assert stats is not None
        assert stats['hits'] == 4  # Warrior(2), Rogue(1), Mage(1)
        assert stats['crits'] == 1  # Rogue crit
        assert stats['misses'] == 1  # Cleric miss
        assert stats['hit_rate'] == pytest.approx(83.33, abs=0.1)  # 5 successful / 6 total

        # 5. AC Estimation
        assert 'Goblin Chief' in parser.target_ac
        ac_estimate = parser.target_ac['Goblin Chief'].get_ac_estimate()
        # Should be between 14 (miss) and 19 (min hit)
        assert ac_estimate != "?"

        # 6. Attack Bonus Tracking
        assert 'Goblin Chief' in parser.target_attack_bonus
        ab_display = parser.target_attack_bonus['Goblin Chief'].get_bonus_display()
        assert ab_display == "+12"

        # 7. Saves Tracking
        assert 'Goblin Chief' in parser.target_saves
        assert parser.target_saves['Goblin Chief'].fortitude == 5

        # 8. Immunity Tracking
        immunity_info = database.get_immunity_for_target_and_type("Goblin Chief", "Fire")
        assert immunity_info['max_immunity'] == 20
        assert immunity_info['max_damage'] == 80

        # Calculate immunity percentage
        immunity_pct = calculate_immunity_percentage(
            immunity_info['max_damage'],
            immunity_info['max_immunity']
        )
        assert immunity_pct is not None
        assert immunity_pct >= 0 and immunity_pct <= 100

        # 9. Damage Type Breakdown
        rogue_breakdown = dps_service.get_damage_type_breakdown("Rogue", target_filter="Goblin Chief")
        assert len(rogue_breakdown) == 2

        physical = next((b for b in rogue_breakdown if b['damage_type'] == 'Physical'), None)
        acid = next((b for b in rogue_breakdown if b['damage_type'] == 'Acid'), None)

        assert physical is not None
        assert physical['total_damage'] == 125  # 50 + 75
        assert acid is not None
        assert acid['total_damage'] == 25  # 10 + 15

        # 10. Target Summary
        summary = database.get_all_targets_summary(parser)
        goblin_summary = next((s for s in summary if s['target'] == 'Goblin Chief'), None)

        assert goblin_summary is not None
        assert goblin_summary['ab'] == '+12'
        assert goblin_summary['fortitude'] == '5'

    def test_multi_target_combat(self, temp_log_dir: Path) -> None:
        """Test combat session with multiple targets."""
        log_file = temp_log_dir / "combat.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Warrior attacks Goblin1: *hit*: (15 + 10 = 25)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Warrior damages Goblin1: 40 (40 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Rogue attacks Goblin2: *hit*: (16 + 8 = 24)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Rogue damages Goblin2: 50 (50 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:04] Warrior attacks Goblin2: *hit*: (14 + 10 = 24)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Warrior damages Goblin2: 35 (35 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:06] Rogue attacks Goblin1: *hit*: (18 + 8 = 26)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:07] Rogue damages Goblin1: 45 (45 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)

        # All targets
        dps_all = dps_service.get_dps_display_data(target_filter="All")
        assert len(dps_all) == 2  # Warrior and Rogue

        # Goblin1 only
        dps_g1 = dps_service.get_dps_display_data(target_filter="Goblin1")
        g1_chars = {d['character'] for d in dps_g1}
        assert 'Warrior' in g1_chars
        assert 'Rogue' in g1_chars

        warrior_g1 = next((d for d in dps_g1 if d['character'] == 'Warrior'), None)
        assert warrior_g1['total_damage'] == 40

        # Goblin2 only
        dps_g2 = dps_service.get_dps_display_data(target_filter="Goblin2")
        warrior_g2 = next((d for d in dps_g2 if d['character'] == 'Warrior'), None)
        assert warrior_g2['total_damage'] == 35

    def test_complex_immunity_scenario(self, temp_log_dir: Path) -> None:
        """Test complex scenario with multiple damage types and immunities."""
        log_file = temp_log_dir / "combat.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Mage damages Ancient Dragon: 200 (50 Fire 50 Cold 50 Acid 50 Electrical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Ancient Dragon : Damage Immunity absorbs 50 point(s) of Fire
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Ancient Dragon : Damage Immunity absorbs 25 points of Cold
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Ancient Dragon : Damage Immunity absorbs 10 point of Electrical
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Mage damages Ancient Dragon: 200 (50 Fire 50 Cold 50 Acid 50 Electrical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Ancient Dragon : Damage Immunity absorbs 50 point(s) of Fire
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Ancient Dragon : Damage Immunity absorbs 25 points of Cold
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Ancient Dragon : Damage Immunity absorbs 10 point of Electrical
"""
        log_file.write_text(content)

        parser = LogParser(parse_immunity=True)
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        # Check all immunities were tracked
        fire_immunity = database.get_immunity_for_target_and_type("Ancient Dragon", "Fire")
        assert fire_immunity['max_immunity'] == 50
        assert fire_immunity['sample_count'] == 2

        cold_immunity = database.get_immunity_for_target_and_type("Ancient Dragon", "Cold")
        assert cold_immunity['max_immunity'] == 25

        elec_immunity = database.get_immunity_for_target_and_type("Ancient Dragon", "Electrical")
        assert elec_immunity['max_immunity'] == 10

        # Acid should have no immunity
        acid_immunity = database.get_immunity_for_target_and_type("Ancient Dragon", "Acid")
        assert acid_immunity['max_immunity'] == 0

        # DPS should still calculate correctly
        dps_service = DPSCalculationService(database)
        dps_list = dps_service.get_dps_display_data()

        assert len(dps_list) == 1
        assert dps_list[0]['total_damage'] == 400

    def test_edge_case_natural_1_miss(self, temp_log_dir: Path) -> None:
        """Test that natural 1 misses don't affect AC estimation."""
        log_file = temp_log_dir / "combat.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Warrior attacks Dragon: *hit*: (15 + 10 = 25)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Warrior attacks Dragon: *miss*: (1 + 10 = 11)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Warrior attacks Dragon: *miss*: (10 + 10 = 20)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        # Natural 1 should be ignored for AC
        assert 'Dragon' in parser.target_ac
        assert parser.target_ac['Dragon'].min_hit == 25
        assert parser.target_ac['Dragon'].max_miss == 20  # Not 11 (natural 1)

    def test_time_tracking_modes_comparison(self, temp_log_dir: Path) -> None:
        """Test both time tracking modes produce consistent results."""
        log_file = temp_log_dir / "combat.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 100 (100 Physical)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:10] Woo damages Goblin: 50 (50 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        parse_and_import_file(str(log_file), parser, database)

        dps_service = DPSCalculationService(database)

        # By character mode
        dps_service.set_time_tracking_mode("per_character")
        dps_by_char = dps_service.get_dps_display_data()

        assert len(dps_by_char) == 1
        assert dps_by_char[0]['total_damage'] == 150

        # Global mode
        dps_service.set_time_tracking_mode("global")
        dps_global = dps_service.get_dps_display_data()

        assert len(dps_global) == 1
        assert dps_global[0]['total_damage'] == 150  # Same total damage

        # DPS might differ due to different time windows, but damage is consistent


class TestErrorRecovery:
    """Test suite for error recovery and edge cases."""

    def test_malformed_lines_dont_break_session(self, temp_log_dir: Path) -> None:
        """Test that malformed lines don't break the session."""
        log_file = temp_log_dir / "combat.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 100 (100 Physical)
This is a completely invalid line
[CHAT WINDOW TEXT] Invalid timestamp format
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo damages Goblin: 50 (50 Physical)
"""
        log_file.write_text(content)

        parser = LogParser()
        database = DataStore()
        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        # Should still process valid lines
        dps_service = DPSCalculationService(database)
        dps_list = dps_service.get_dps_display_data()

        assert len(dps_list) == 1
        assert dps_list[0]['total_damage'] == 150

    def test_empty_combat_session(self, temp_log_dir: Path) -> None:
        """Test handling of empty combat session."""
        log_file = temp_log_dir / "empty.txt"
        log_file.write_text("")

        parser = LogParser()
        database = DataStore()
        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True

        dps_service = DPSCalculationService(database)
        dps_list = dps_service.get_dps_display_data()

        assert len(dps_list) == 0

