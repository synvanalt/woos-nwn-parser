"""Additional tests for parse_file_to_ops/import_worker_process behavior."""

import io
from unittest.mock import Mock

from app.utils import parse_file_to_ops, import_worker_process


class _CaptureQueue:
    def __init__(self) -> None:
        self.items = []

    def put(self, item) -> None:
        self.items.append(item)


class _AbortEvent:
    def __init__(self, is_set: bool = False) -> None:
        self._is_set = is_set

    def is_set(self) -> bool:
        return self._is_set


def test_parse_file_to_ops_collects_damage_immunity_attacks_and_death_snippet(monkeypatch) -> None:
    log_data = "\n".join([
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo attacks Goblin: *hit*: (14 + 5 = 19)",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo killed Goblin",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Your God refuses to hear your prayers!",
        "",
    ])
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    result = parse_file_to_ops("ignored.txt", parse_immunity=True)

    assert result["success"] is True
    assert result["aborted"] is False
    ops = result["ops"]
    assert len(ops["dps_updates"]) == 1
    assert len(ops["damage_events"]) == 2
    assert len(ops["immunity_records"]) == 1
    assert len(ops["attack_events"]) == 1
    assert len(ops["death_snippets"]) == 1
    assert ops["death_snippets"][0]["target"] == "Goblin"


def test_parse_file_to_ops_can_abort_mid_file(monkeypatch) -> None:
    log_data = "\n".join([
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (50 Physical)",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo damages Goblin: 60 (60 Physical)",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo damages Goblin: 70 (70 Physical)",
        "",
    ])
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    checks = {"count": 0}

    def should_abort() -> bool:
        checks["count"] += 1
        return checks["count"] > 4

    result = parse_file_to_ops("ignored.txt", parse_immunity=False, should_abort=should_abort)

    assert result["success"] is True
    assert result["aborted"] is True
    assert 0 < result["lines_processed"] <= 3


def test_import_worker_process_emits_file_error_and_continues(monkeypatch) -> None:
    parse_mock = Mock(side_effect=[
        {"success": False, "aborted": False, "error": "bad file", "lines_processed": 0},
        {
            "success": True,
            "aborted": False,
            "error": None,
            "lines_processed": 10,
            "ops": {
                "dps_updates": [],
                "damage_events": [],
                "immunity_records": [],
                "attack_events": [],
                "death_snippets": [],
            },
            "parser_state": {"target_ac": {}, "target_saves": {}, "target_attack_bonus": {}},
        },
    ])
    monkeypatch.setattr("app.utils.parse_file_to_ops", parse_mock)

    result_queue = _CaptureQueue()
    import_worker_process(
        file_paths=["a.txt", "b.txt"],
        parse_immunity=False,
        abort_event=_AbortEvent(False),
        result_queue=result_queue,
    )

    events = [item["event"] for item in result_queue.items]
    assert events == [
        "file_started",
        "file_error",
        "file_started",
        "file_completed",
        "done",
    ]


def test_import_worker_process_stops_when_parser_reports_aborted(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.utils.parse_file_to_ops",
        Mock(return_value={"success": True, "aborted": True, "error": None, "lines_processed": 2}),
    )

    result_queue = _CaptureQueue()
    import_worker_process(
        file_paths=["a.txt", "b.txt"],
        parse_immunity=False,
        abort_event=_AbortEvent(False),
        result_queue=result_queue,
    )

    events = [item["event"] for item in result_queue.items]
    assert events == ["file_started", "aborted"]
