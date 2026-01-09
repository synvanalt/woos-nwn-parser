"""UI formatting utilities for Woo's NWN Parser.

This module contains reusable formatting functions that can be used
across all UI components.
"""

from datetime import timedelta
from pathlib import Path
from tkinter import ttk

from ..models import DAMAGE_TYPE_PALETTE


def damage_type_to_color(damage_type: str) -> str:
    """Map a damage type string to a hex color.

    Uses case-insensitive substring matching from DAMAGE_TYPE_PALETTE.

    Args:
        damage_type: Name of the damage type

    Returns:
        Hex color code string
    """
    if not damage_type:
        return '#D1D5DB'

    s = damage_type.lower()
    for key, col in DAMAGE_TYPE_PALETTE.items():
        if key in s:
            return col

    return '#D1D5DB'


def apply_tag_to_tree(tree: ttk.Treeview, tag: str, color: str) -> None:
    """Configure a tag on a Treeview with the given foreground color.

    Silently ignores configuration failures on some platforms.

    Args:
        tree: The Treeview widget
        tag: Tag name to configure
        color: Hex color code
    """
    try:
        tree.tag_configure(tag, foreground=color)
    except Exception:
        pass


def format_time(time_delta) -> str:
    """Format a timedelta object to H:MM:SS format.

    Args:
        time_delta: timedelta object or total seconds as float/int

    Returns:
        Formatted time string as H:MM:SS
    """
    # Handle both timedelta objects and float/int seconds
    if isinstance(time_delta, timedelta):
        total_seconds = int(time_delta.total_seconds())
    else:
        total_seconds = int(time_delta)

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    return f"{hours}:{minutes:02d}:{seconds:02d}"


def get_default_log_directory() -> str:
    """Get the default NWN log directory for the current user.

    Returns:
        Default log directory path or empty string if not found
    """
    default_path = Path.home() / "Documents" / "Neverwinter Nights" / "logs"
    if default_path.exists():
        return str(default_path)
    return ""

