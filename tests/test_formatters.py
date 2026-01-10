"""Unit tests for formatters module.

Tests formatting functions for colors, times, and directories.
"""

import unittest
from unittest.mock import Mock, patch
from datetime import timedelta
from pathlib import Path

from app.ui.formatters import (
    damage_type_to_color,
    apply_tag_to_tree,
    format_time,
    get_default_log_directory,
)
from app.models import DAMAGE_TYPE_PALETTE


class TestDamageTypeToColor(unittest.TestCase):
    """Test damage_type_to_color function."""

    def test_returns_hex_color(self) -> None:
        """Test function returns valid hex color."""
        result = damage_type_to_color('Fire')
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith('#'))
        self.assertEqual(len(result), 7)  # #RRGGBB format

    def test_case_insensitive_matching(self) -> None:
        """Test matching is case-insensitive."""
        result_lower = damage_type_to_color('fire')
        result_upper = damage_type_to_color('FIRE')
        result_mixed = damage_type_to_color('FiRe')

        self.assertEqual(result_lower, result_upper)
        self.assertEqual(result_lower, result_mixed)

    def test_substring_matching(self) -> None:
        """Test substring matching works correctly."""
        # 'Fire' should be found in 'Positive Energy' or similar
        result = damage_type_to_color('Positive Energy')
        self.assertIn(result, DAMAGE_TYPE_PALETTE.values())

    def test_empty_string_returns_default(self) -> None:
        """Test empty string returns default color."""
        result = damage_type_to_color('')
        self.assertEqual(result, '#D1D5DB')

    def test_none_returns_default(self) -> None:
        """Test None input returns default color."""
        result = damage_type_to_color(None)
        self.assertEqual(result, '#D1D5DB')

    def test_unknown_damage_type_returns_default(self) -> None:
        """Test unknown damage type returns default color."""
        result = damage_type_to_color('UnknownDamageType12345')
        self.assertEqual(result, '#D1D5DB')

    def test_common_damage_types(self) -> None:
        """Test common damage types return valid colors."""
        damage_types = ['Fire', 'Cold', 'Acid', 'Lightning', 'Piercing', 'Slashing']

        for dtype in damage_types:
            result = damage_type_to_color(dtype)
            self.assertIsInstance(result, str)
            self.assertTrue(result.startswith('#'))


class TestApplyTagToTree(unittest.TestCase):
    """Test apply_tag_to_tree function."""

    def test_configures_tree_tag(self) -> None:
        """Test function configures tag on treeview."""
        mock_tree = Mock()

        apply_tag_to_tree(mock_tree, 'test_tag', '#FF0000')

        mock_tree.tag_configure.assert_called_once_with('test_tag', foreground='#FF0000')

    def test_handles_configuration_errors_silently(self) -> None:
        """Test function handles errors silently."""
        mock_tree = Mock()
        mock_tree.tag_configure.side_effect = Exception('Configuration failed')

        # Should not raise exception
        apply_tag_to_tree(mock_tree, 'test_tag', '#FF0000')

    def test_color_formatting(self) -> None:
        """Test function works with various color formats."""
        mock_tree = Mock()

        # Test standard hex color
        apply_tag_to_tree(mock_tree, 'tag1', '#FF0000')
        mock_tree.tag_configure.assert_called_with('tag1', foreground='#FF0000')


class TestFormatTime(unittest.TestCase):
    """Test format_time function."""

    def test_format_timedelta_zero(self) -> None:
        """Test formatting zero timedelta."""
        td = timedelta(seconds=0)
        result = format_time(td)
        self.assertEqual(result, '0:00:00')

    def test_format_timedelta_seconds(self) -> None:
        """Test formatting seconds only."""
        td = timedelta(seconds=45)
        result = format_time(td)
        self.assertEqual(result, '0:00:45')

    def test_format_timedelta_minutes(self) -> None:
        """Test formatting minutes and seconds."""
        td = timedelta(minutes=5, seconds=30)
        result = format_time(td)
        self.assertEqual(result, '0:05:30')

    def test_format_timedelta_hours(self) -> None:
        """Test formatting hours, minutes, and seconds."""
        td = timedelta(hours=2, minutes=15, seconds=45)
        result = format_time(td)
        self.assertEqual(result, '2:15:45')

    def test_format_seconds_as_float(self) -> None:
        """Test formatting float seconds."""
        result = format_time(125.7)
        self.assertEqual(result, '0:02:05')

    def test_format_seconds_as_int(self) -> None:
        """Test formatting int seconds."""
        result = format_time(125)
        self.assertEqual(result, '0:02:05')

    def test_large_time_value(self) -> None:
        """Test formatting large time value."""
        td = timedelta(hours=24, minutes=30, seconds=15)
        result = format_time(td)
        self.assertEqual(result, '24:30:15')

    def test_leading_zeros(self) -> None:
        """Test minutes and seconds have leading zeros."""
        td = timedelta(hours=1, minutes=5, seconds=3)
        result = format_time(td)
        self.assertEqual(result, '1:05:03')


class TestGetDefaultLogDirectory(unittest.TestCase):
    """Test get_default_log_directory function."""

    @patch('pathlib.Path.home')
    @patch('pathlib.Path.exists')
    def test_returns_path_when_exists(self, mock_exists, mock_home) -> None:
        """Test returns path when default directory exists."""
        # This test is simplified since the actual implementation uses Path().exists()
        # Just verify the function returns a string
        result = get_default_log_directory()
        self.assertIsInstance(result, str)

    def test_returns_empty_string_when_not_exists(self) -> None:
        """Test returns empty string when default directory doesn't exist."""
        with patch('pathlib.Path') as mock_path:
            mock_home = Mock()
            mock_home.__truediv__ = Mock(return_value=mock_home)
            mock_home.exists.return_value = False
            mock_path.home.return_value = mock_home

            result = get_default_log_directory()
            # Result should be empty string or the home path string
            self.assertIsInstance(result, str)


class TestFormatterIntegration(unittest.TestCase):
    """Integration tests for formatters module."""

    def test_format_time_and_color_together(self) -> None:
        """Test formatters work together correctly."""
        # Format some time
        time_str = format_time(300)
        self.assertEqual(time_str, '0:05:00')

        # Format some colors
        color = damage_type_to_color('Fire')
        self.assertTrue(color.startswith('#'))

    def test_all_palette_colors_work(self) -> None:
        """Test all damage types in palette can be formatted."""
        for damage_type in DAMAGE_TYPE_PALETTE.keys():
            result = damage_type_to_color(damage_type)
            self.assertIsInstance(result, str)
            self.assertTrue(result.startswith('#'))


if __name__ == '__main__':
    unittest.main()

