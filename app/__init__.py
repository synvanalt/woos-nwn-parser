"""Woo's NWN Parser - A Neverwinter Nights combat log analyzer.

This package contains the modularized components of the Woo's NWN Parser application,
which parses game logs to track damage, DPS, AB, AC, Saves and Damage Immunities.

Main modules:
    - models: Data model classes (EnemySaves, EnemyAC, DamageEvent, AttackEvent)
    - parser: LogParser for regex-based log line parsing
    - storage: DataStore for in-memory data management
    - monitor: LogDirectoryMonitor for log file monitoring and polling
    - ui: User interface components
    - utils: Utility functions for file processing
"""

__version__ = "1.0.0"
__author__ = "Woo"

from .models import (
    DAMAGE_TYPE_PALETTE,
    EnemySaves,
    EnemyAC,
    DamageEvent,
    AttackEvent,
)
from .parser import LogParser
from .storage import DataStore
from .monitor import LogDirectoryMonitor
from .utils import parse_and_import_file

__all__ = [
    'DAMAGE_TYPE_PALETTE',
    'EnemySaves',
    'EnemyAC',
    'DamageEvent',
    'AttackEvent',
    'LogParser',
    'DataStore',
    'LogDirectoryMonitor',
    'parse_and_import_file',
]

