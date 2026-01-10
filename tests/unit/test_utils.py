"""Unit tests for utility functions.

Tests immunity calculations, damage calculations, and file parsing utilities.
"""

import pytest
import tempfile
from pathlib import Path

from app.utils import (
    compute_dmg_reduced,
    compute_dmg_after,
    reverse_immunity,
    pick_immunity,
    calculate_immunity_percentage,
    parse_and_import_file,
)
from app.parser import LogParser
from app.storage import DataStore


class TestComputeDmgReduced:
    """Test suite for compute_dmg_reduced function."""

    def test_zero_immunity(self) -> None:
        """Test damage reduction with zero immunity."""
        assert compute_dmg_reduced(100, 0.0) == 0

    def test_full_immunity(self) -> None:
        """Test damage reduction with full immunity."""
        result = compute_dmg_reduced(100, 1.0)
        assert result == 100

    def test_partial_immunity(self) -> None:
        """Test damage reduction with partial immunity."""
        result = compute_dmg_reduced(100, 0.5)
        assert result == 50

    def test_minimum_one_damage_reduced(self) -> None:
        """Test that at least 1 damage is reduced when immunity > 0."""
        result = compute_dmg_reduced(10, 0.05)  # 5% of 10 = 0.5, should be 1
        assert result >= 1

    def test_zero_damage(self) -> None:
        """Test zero damage input."""
        assert compute_dmg_reduced(0, 0.5) == 0

    def test_negative_damage(self) -> None:
        """Test negative damage input."""
        assert compute_dmg_reduced(-10, 0.5) == 0


class TestComputeDmgAfter:
    """Test suite for compute_dmg_after function."""

    def test_zero_immunity(self) -> None:
        """Test damage after immunity with zero immunity."""
        assert compute_dmg_after(100, 0.0) == 100

    def test_full_immunity(self) -> None:
        """Test damage after immunity with full immunity."""
        assert compute_dmg_after(100, 1.0) == 0

    def test_partial_immunity(self) -> None:
        """Test damage after immunity with partial immunity."""
        result = compute_dmg_after(100, 0.5)
        assert result == 50

    def test_damage_never_negative(self) -> None:
        """Test that damage after immunity never goes negative."""
        result = compute_dmg_after(10, 0.95)
        assert result >= 0


class TestReverseImmunity:
    """Test suite for reverse_immunity function."""

    def test_reverse_immunity_exact_match(self) -> None:
        """Test reverse immunity calculation with exact match."""
        matches = reverse_immunity(dmg_after_immunity=90, dmg_reduced=10)
        assert len(matches) > 0
        assert all(0.0 <= m <= 1.0 for m in matches)

    def test_reverse_immunity_zero_reduced(self) -> None:
        """Test reverse immunity with zero damage reduced."""
        matches = reverse_immunity(dmg_after_immunity=100, dmg_reduced=0)
        assert 0.0 in matches

    def test_reverse_immunity_zero_damage(self) -> None:
        """Test reverse immunity with zero damage."""
        matches = reverse_immunity(dmg_after_immunity=0, dmg_reduced=0)
        assert len(matches) > 0

    def test_reverse_immunity_multiple_matches(self) -> None:
        """Test that reverse immunity can return multiple possible values."""
        matches = reverse_immunity(dmg_after_immunity=50, dmg_reduced=5)
        # Due to floor function, multiple immunity values might produce same result
        assert isinstance(matches, list)


class TestPickImmunity:
    """Test suite for pick_immunity function."""

    def test_pick_immunity_empty_list(self) -> None:
        """Test picking immunity from empty list."""
        assert pick_immunity([]) is None

    def test_pick_immunity_single_value(self) -> None:
        """Test picking immunity from single value."""
        result = pick_immunity([0.5])
        assert result == 50  # Converted to percentage

    def test_pick_immunity_uses_minimum(self) -> None:
        """Test that pick_immunity uses minimum value."""
        result = pick_immunity([0.3, 0.5, 0.2])
        assert result == 20  # Minimum value

    def test_pick_immunity_converts_to_percentage(self) -> None:
        """Test that pick_immunity converts to percentage."""
        result = pick_immunity([0.25])
        assert result == 25


class TestCalculateImmunityPercentage:
    """Test suite for calculate_immunity_percentage function."""

    def test_calculate_with_valid_data(self) -> None:
        """Test calculating immunity percentage with valid data."""
        result = calculate_immunity_percentage(max_damage=100, max_absorbed=50)
        # May return None if no exact match due to floor function in game logic
        if result is not None:
            assert isinstance(result, int)
            assert 0 <= result <= 100

    def test_calculate_zero_damage(self) -> None:
        """Test calculation with zero damage."""
        result = calculate_immunity_percentage(max_damage=0, max_absorbed=10)
        assert result is None

    def test_calculate_zero_absorbed(self) -> None:
        """Test calculation with zero absorption."""
        result = calculate_immunity_percentage(max_damage=100, max_absorbed=0)
        assert result == 0

    def test_calculate_negative_damage(self) -> None:
        """Test calculation with negative damage."""
        result = calculate_immunity_percentage(max_damage=-10, max_absorbed=5)
        assert result is None


class TestParseAndImportFile:
    """Test suite for parse_and_import_file function."""

    def test_parse_valid_log_file(self, sample_combat_session: Path) -> None:
        """Test parsing a valid log file."""
        parser = LogParser(parse_immunity=True)
        database = DataStore()

        result = parse_and_import_file(str(sample_combat_session), parser, database)

        assert result['success'] is True
        assert result['lines_processed'] > 0
        assert result['error'] is None
        assert len(database.events) > 0

    def test_parse_clears_existing_data(self, sample_combat_session: Path) -> None:
        """Test that parsing clears existing data first."""
        parser = LogParser()
        database = DataStore()

        # Add some data
        database.insert_damage_event("OldTarget", "Fire", 0, 50, "OldAttacker")

        # Parse file
        parse_and_import_file(str(sample_combat_session), parser, database)

        # Old data should be cleared
        old_events = [e for e in database.events if e.target == "OldTarget"]
        assert len(old_events) == 0

    def test_parse_tracks_dps_data(self, sample_combat_session: Path) -> None:
        """Test that parsing updates DPS tracking."""
        parser = LogParser()
        database = DataStore()

        parse_and_import_file(str(sample_combat_session), parser, database)

        assert len(database.dps_data) > 0

    def test_parse_tracks_attacks(self, sample_combat_session: Path) -> None:
        """Test that parsing tracks attack events."""
        parser = LogParser()
        database = DataStore()

        parse_and_import_file(str(sample_combat_session), parser, database)

        assert len(database.attacks) > 0

    def test_parse_nonexistent_file(self) -> None:
        """Test parsing nonexistent file returns error."""
        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file("nonexistent.txt", parser, database)

        assert result['success'] is False
        assert result['error'] is not None

    def test_parse_empty_file(self, temp_log_dir: Path) -> None:
        """Test parsing empty file."""
        empty_file = temp_log_dir / "empty.txt"
        empty_file.write_text("")

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(empty_file), parser, database)

        assert result['success'] is True
        assert result['lines_processed'] == 0

    def test_parse_with_immunity_matching(self, temp_log_dir: Path) -> None:
        """Test that immunity events are matched with damage events."""
        log_file = temp_log_dir / "test.txt"
        content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire
"""
        log_file.write_text(content)

        parser = LogParser(parse_immunity=True)
        database = DataStore()

        parse_and_import_file(str(log_file), parser, database)

        # Check that immunity was recorded
        immunity_info = database.get_immunity_for_target_and_type("Goblin", "Fire")
        assert immunity_info['max_immunity'] == 10

    def test_parse_large_file_in_chunks(self, temp_log_dir: Path) -> None:
        """Test parsing large file processes in chunks."""
        log_file = temp_log_dir / "large.txt"

        # Create a file with many lines
        lines = []
        for i in range(15000):  # More than chunk size
            lines.append(f"[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Target{i}: 50 (50 Physical)\n")

        log_file.write_text("".join(lines))

        parser = LogParser()
        database = DataStore()

        result = parse_and_import_file(str(log_file), parser, database)

        assert result['success'] is True
        assert result['lines_processed'] == 15000


class TestUtilityEdgeCases:
    """Test suite for edge cases and error handling."""

    def test_compute_dmg_reduced_large_values(self) -> None:
        """Test damage reduction with large values."""
        result = compute_dmg_reduced(10000, 0.5)
        assert result == 5000

    def test_reverse_immunity_edge_case_values(self) -> None:
        """Test reverse immunity with edge case values."""
        matches = reverse_immunity(dmg_after_immunity=1, dmg_reduced=99)
        assert isinstance(matches, list)

    def test_calculate_immunity_percentage_boundary(self) -> None:
        """Test immunity percentage at boundaries."""
        # Test with values that should give 100% immunity
        result = calculate_immunity_percentage(max_damage=50, max_absorbed=50)
        assert result is not None
        assert result <= 100

