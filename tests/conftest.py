"""Pytest configuration and shared fixtures for Woo's NWN Parser tests."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from app.parser import LogParser
from app.storage import DataStore
from app.monitor import LogDirectoryMonitor
from app.services.dps_service import DPSCalculationService
from app.services.queue_processor import QueueProcessor


__all__ = ['LogMessageCapture']


def pytest_configure(config):
    """Make LogMessageCapture available for import in test files."""
    import sys
    sys.modules['conftest'] = sys.modules[__name__]


class LogMessageCapture:
    """Helper class to capture log messages from monitor callbacks.

    Provides compatibility with tests that expect messages in dict format.
    """
    def __init__(self):
        self.messages = []

    def __call__(self, message: str, msg_type: str):
        """Callback function to capture messages."""
        self.messages.append({'message': message, 'type': msg_type})

    def get_by_type(self, msg_type: str) -> list:
        """Get all messages of a specific type."""
        return [m for m in self.messages if m.get('type') == msg_type]

    def get_all(self) -> list:
        """Get all captured messages."""
        return self.messages

    def clear(self):
        """Clear all captured messages."""
        self.messages.clear()


@pytest.fixture
def log_capture():
    """Create a LogMessageCapture instance for tests."""
    return LogMessageCapture()


# Make LogMessageCapture available to all tests without fixture
import sys
sys.modules[__name__].LogMessageCapture = LogMessageCapture


@pytest.fixture
def parser() -> LogParser:
    """Create a LogParser instance for testing."""
    return LogParser(player_name=None, parse_immunity=False)


@pytest.fixture
def parser_with_immunity() -> LogParser:
    """Create a LogParser instance with immunity parsing enabled."""
    return LogParser(player_name=None, parse_immunity=True)


@pytest.fixture
def parser_with_player() -> LogParser:
    """Create a LogParser instance with player filtering."""
    return LogParser(player_name="TestPlayer", parse_immunity=False)


@pytest.fixture
def data_store() -> DataStore:
    """Create a DataStore instance for testing."""
    return DataStore()


@pytest.fixture
def dps_service(data_store: DataStore) -> DPSCalculationService:
    """Create a DPSCalculationService instance for testing."""
    return DPSCalculationService(data_store)


@pytest.fixture
def queue_processor(data_store: DataStore, parser: LogParser) -> QueueProcessor:
    """Create a QueueProcessor instance for testing."""
    return QueueProcessor(data_store, parser)


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for log file testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_log_lines() -> Dict[str, List[str]]:
    """Provide sample log lines for various scenarios."""
    return {
        'damage': [
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)',
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Rogue damages Orc: 100 (70 Physical 30 Cold)',
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Mage damages Dragon: 200 (100 Fire 50 Magical 50 Pure)',
        ],
        'immunity': [
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire',
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Orc : Damage Immunity absorbs 5 points of Cold',
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Dragon : Damage Immunity absorbs 50 point of Fire',
        ],
        'attack_hit': [
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (14 + 5 = 19)',
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Rogue attacks Orc: *hit*: (16 + 8 = 24)',
        ],
        'attack_miss': [
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *miss*: (8 + 5 = 13)',
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Rogue attacks Orc: *miss*: (1 + 8 = 9)',
        ],
        'attack_crit': [
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *critical hit*: (18 + 5 = 23)',
        ],
        'save': [
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] SAVE: Goblin: Fortitude Save: *success*: (12 + 3 = 15 vs. DC: 20)',
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Orc: Reflex Save: *failed*: (6 + 2 = 8 vs. DC: 15)',
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Dragon: Will Save: *success*: (16 + 10 = 26 vs. DC: 25)',
        ],
        'complex_damage': [
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Ancient Dragon: 250 (50 Physical 75 Fire 50 Cold 25 Acid 25 Electrical 25 Divine)',
        ],
        'multiword_damage': [
            '[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Lich: 100 (50 Positive Energy 30 Divine 20 Pure)',
        ],
    }


@pytest.fixture
def sample_combat_session(temp_log_dir: Path) -> Path:
    """Create a sample combat log file with a complete session."""
    log_file = temp_log_dir / "nwclientLog1.txt"

    content = """[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo attacks Goblin: *hit*: (14 + 5 = 19)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo damages Goblin: 25 (20 Physical 5 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Goblin : Damage Immunity absorbs 2 point(s) of Fire
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo attacks Goblin: *hit*: (16 + 5 = 21)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Woo damages Goblin: 30 (25 Physical 5 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Goblin : Damage Immunity absorbs 2 points of Fire
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:04] Woo attacks Goblin: *miss*: (8 + 5 = 13)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:05] Woo attacks Goblin: *critical hit*: (18 + 5 = 23)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:06] Woo damages Goblin: 50 (45 Physical 5 Fire)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:06] Goblin : Damage Immunity absorbs 2 point of Fire
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:07] SAVE: Goblin: Fortitude Save: *failed*: (8 + 2 = 10 vs. DC: 15)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:10] Rogue attacks Orc: *hit*: (15 + 8 = 23)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:11] Rogue damages Orc: 40 (30 Physical 10 Cold)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:11] Orc : Damage Immunity absorbs 5 points of Cold
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:12] Rogue attacks Orc: *hit*: (17 + 8 = 25)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:13] Rogue damages Orc: 45 (35 Physical 10 Cold)
[CHAT WINDOW TEXT] [Thu Jan 09 14:30:13] Orc : Damage Immunity absorbs 5 point(s) of Cold
"""

    log_file.write_text(content)
    return log_file


@pytest.fixture
def real_combat_log() -> Path:
    """Path to real NWN combat log file for integration/performance testing.

    This is a real 4145-line combat log file (405KB) that can be used for:
    - Integration testing with real-world data
    - Performance testing with larger files
    - Validation of parser against actual game output

    Returns:
        Path to fixtures/nwclientLog1_for_testing.txt
    """
    return Path(__file__).parent / "fixtures" / "nwclientLog1_for_testing.txt"

