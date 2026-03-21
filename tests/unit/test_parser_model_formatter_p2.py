"""P2 low-complexity branch tests for parser, models, and formatters."""

from app.models import EnemyAC, EnemySaves
from app.parser import ParserSession
from app.parsed_events import AttackMissEvent
from app.ui.formatters import get_default_log_directory
import app.ui.formatters as formatters_module


def test_enemy_saves_ignores_unknown_save_type() -> None:
    saves = EnemySaves(name="Goblin")
    saves.update_save("unknown", 99)

    assert saves.fortitude is None
    assert saves.reflex is None
    assert saves.will is None


def test_enemy_ac_warning_estimate_branch_for_conflicting_state() -> None:
    ac = EnemyAC(name="Orc")
    ac.max_miss = 25
    ac._min_hit = 20

    estimate = ac.get_ac_estimate()
    assert "20" in estimate
    assert estimate != "20"


def test_parser_attacker_miss_chance_emits_miss_without_ac_tracking() -> None:
    parser = ParserSession()
    line = (
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] "
        "Woo attacks Goblin: *attacker miss chance: 50%*: (12 + 5 = 17)"
    )

    event = parser.parse_line(line)

    assert event is not None
    assert isinstance(event, AttackMissEvent)
    assert event.type == "attack_miss"
    assert event.is_concealment is True


def test_get_default_log_directory_returns_existing_nwn_logs_path(monkeypatch) -> None:
    fake_home = formatters_module.Path("C:/fake_home")
    expected_logs = fake_home / "Documents" / "Neverwinter Nights" / "logs"

    monkeypatch.setattr(formatters_module.Path, "home", lambda: fake_home)
    monkeypatch.setattr(formatters_module.Path, "exists", lambda p: p == expected_logs)
    result = get_default_log_directory()

    assert result == str(expected_logs)


def test_get_default_log_directory_returns_empty_when_missing(monkeypatch) -> None:
    fake_home = formatters_module.Path("C:/fake_home")

    monkeypatch.setattr(formatters_module.Path, "home", lambda: fake_home)
    monkeypatch.setattr(formatters_module.Path, "exists", lambda _p: False)
    result = get_default_log_directory()

    assert result == ""
