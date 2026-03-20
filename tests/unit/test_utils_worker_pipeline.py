"""Additional tests for parse_file_to_ops/import_worker_process behavior."""

import io
import queue
import time
from datetime import datetime
from unittest.mock import Mock

import app.utils
from app.models import AttackMutation, DamageMutation, EpicDodgeMutation, ImmunityMutation, SaveMutation
from app.parser import LogParser
from app.parsed_events import (
    AttackHitEvent,
    DamageDealtEvent,
    DeathCharacterIdentifiedEvent,
    DeathSnippetEvent,
    ImmunityObservedEvent,
    SaveObservedEvent,
)
from app.services.event_ingestion import EventIngestionEngine
from app.services.queue_processor import QueueProcessor
from app.storage import DataStore
from app.utils import iter_file_ops_chunks, parse_file_to_ops, import_worker_process


class _CaptureQueue:
    def __init__(self) -> None:
        self.items = []

    def put(self, item, timeout=None) -> None:
        self.items.append(item)


class _AbortEvent:
    def __init__(self, is_set: bool = False) -> None:
        self._is_set = is_set

    def is_set(self) -> bool:
        return self._is_set

    def set(self) -> None:
        self._is_set = True


class _AbortAfterChecksEvent:
    def __init__(self, checks_before_abort: int) -> None:
        self._checks_before_abort = checks_before_abort
        self._checks = 0

    def is_set(self) -> bool:
        self._checks += 1
        return self._checks > self._checks_before_abort


class _AlwaysFullQueue:
    def __init__(self) -> None:
        self.put_calls = 0

    def put(self, item, timeout=None) -> None:
        self.put_calls += 1
        raise queue.Full


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
    mutations = ops["mutations"]
    assert sum(isinstance(item, DamageMutation) and item.count_for_dps for item in mutations) == 1
    assert sum(isinstance(item, DamageMutation) and not item.count_for_dps for item in mutations) == 2
    assert sum(isinstance(item, ImmunityMutation) for item in mutations) == 1
    assert sum(isinstance(item, AttackMutation) for item in mutations) == 1
    assert len(ops["death_snippets"]) == 1
    assert ops["death_snippets"][0]["target"] == "Goblin"


def test_parse_file_to_ops_matches_immunity_before_damage(monkeypatch) -> None:
    log_data = "\n".join([
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)",
        "",
    ])
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    result = parse_file_to_ops("ignored.txt", parse_immunity=True)

    assert result["success"] is True
    mutations = result["ops"]["mutations"]
    immunity_mutations = [item for item in mutations if isinstance(item, ImmunityMutation)]
    assert len(immunity_mutations) == 1
    assert immunity_mutations[0].target == "Goblin"
    assert immunity_mutations[0].damage_type == "Fire"
    assert immunity_mutations[0].damage_dealt == 20


def test_parse_file_to_ops_prefers_unique_nearest_immunity_match(monkeypatch) -> None:
    log_data = "\n".join([
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 20 (20 Fire)",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Goblin : Damage Immunity absorbs 10 point(s) of Fire",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (50 Fire)",
        "",
    ])
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    result = parse_file_to_ops("ignored.txt", parse_immunity=True)

    assert result["success"] is True
    mutations = result["ops"]["mutations"]
    immunity_mutations = [item for item in mutations if isinstance(item, ImmunityMutation)]
    assert len(immunity_mutations) == 1
    assert immunity_mutations[0].damage_dealt == 20


def test_parse_file_to_ops_collects_death_character_identified(monkeypatch) -> None:
    log_data = "\n".join([
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Woo Wildrock: [Whisper] wooparseme",
        "",
    ])
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    result = parse_file_to_ops("ignored.txt", parse_immunity=False)

    assert result["success"] is True
    assert result["aborted"] is False
    assert result["ops"]["death_snippets"] == []
    assert result["ops"]["death_character_identified"] == [
        {
            "type": "death_character_identified",
            "character_name": "Woo Wildrock",
        }
    ]


def test_parse_file_to_ops_respects_custom_fallback_line(monkeypatch) -> None:
    log_data = "\n".join([
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo killed Goblin",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Your God refuses to hear your prayers!",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:04] You have fallen.",
        "",
    ])
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    result = parse_file_to_ops(
        "ignored.txt",
        parse_immunity=False,
        death_fallback_line="You have fallen.",
    )

    assert result["success"] is True
    death_snippets = result["ops"]["death_snippets"]
    assert len(death_snippets) == 1
    assert death_snippets[0]["lines"][-1].endswith("You have fallen.")


def test_parse_file_to_ops_disables_fallback_when_character_name_known(monkeypatch) -> None:
    log_data = "\n".join([
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Woo killed Goblin",
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] Your God refuses to hear your prayers!",
        "",
    ])
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    result = parse_file_to_ops(
        "ignored.txt",
        parse_immunity=False,
        death_character_name="Nonexistent Character",
    )

    assert result["success"] is True
    assert result["ops"]["death_snippets"] == []


def test_parse_file_to_ops_does_not_build_matcher_when_immunity_disabled(monkeypatch) -> None:
    log_data = "\n".join([
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (30 Physical 20 Fire)",
        "",
    ])
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    class _UnexpectedMatcher:
        def __init__(self) -> None:
            raise AssertionError("ImmunityMatcher should not be constructed when disabled")

    monkeypatch.setattr(app.utils, "ImmunityMatcher", _UnexpectedMatcher)

    result = parse_file_to_ops("ignored.txt", parse_immunity=False)

    assert result["success"] is True
    mutations = result["ops"]["mutations"]
    assert sum(isinstance(item, DamageMutation) and item.count_for_dps for item in mutations) == 1
    assert sum(isinstance(item, DamageMutation) and not item.count_for_dps for item in mutations) == 2
    assert not any(isinstance(item, ImmunityMutation) for item in mutations)


def test_parse_file_to_ops_can_abort_mid_file(monkeypatch) -> None:
    log_data = "".join(
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (50 Physical)\n"
        for _ in range(3000)
    )
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    checks = {"count": 0}

    def should_abort() -> bool:
        checks["count"] += 1
        return checks["count"] > 1

    result = parse_file_to_ops("ignored.txt", parse_immunity=False, should_abort=should_abort)

    assert result["success"] is True
    assert result["aborted"] is True
    assert 0 < result["lines_processed"] < 3000


def test_import_worker_process_emits_file_error_and_continues(monkeypatch) -> None:
    def chunk_stream(*args, **kwargs):
        file_path = args[0]
        if file_path == "a.txt":
            raise RuntimeError("bad file")
        yield {
            "mutations": [],
            "death_snippets": [],
            "death_character_identified": [],
        }

    monkeypatch.setattr("app.utils.iter_file_ops_chunks", chunk_stream)

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
        "ops_chunk",
        "file_completed",
        "done",
    ]


def test_import_worker_process_stops_when_abort_is_set_mid_stream(monkeypatch) -> None:
    abort_event = _AbortEvent(False)

    def chunk_stream(*args, **kwargs):
        abort_event.set()
        if False:
            yield {}

    monkeypatch.setattr("app.utils.iter_file_ops_chunks", chunk_stream)

    result_queue = _CaptureQueue()
    import_worker_process(
        file_paths=["a.txt", "b.txt"],
        parse_immunity=False,
        abort_event=abort_event,
        result_queue=result_queue,
    )

    events = [item["event"] for item in result_queue.items]
    assert events == ["file_started", "aborted"]


def test_import_worker_process_forwards_death_settings(monkeypatch) -> None:
    chunk_mock = Mock(return_value=iter([{
            "mutations": [],
            "death_snippets": [],
            "death_character_identified": [],
        }]))
    monkeypatch.setattr("app.utils.iter_file_ops_chunks", chunk_mock)

    result_queue = _CaptureQueue()
    import_worker_process(
        file_paths=["a.txt"],
        parse_immunity=False,
        abort_event=_AbortEvent(False),
        result_queue=result_queue,
        death_character_name="Foo Bar",
        death_fallback_line="Custom fallback",
    )

    _args, kwargs = chunk_mock.call_args
    assert kwargs["death_character_name"] == "Foo Bar"
    assert kwargs["death_fallback_line"] == "Custom fallback"


def test_import_worker_process_streams_chunk_order_and_payload_integrity(monkeypatch) -> None:
    ops = {
        "mutations": (
            [DamageMutation(target="Goblin", total_damage=i, attacker="Woo", timestamp=float(i), count_for_dps=True, damage_types={"Physical": i}) for i in range(2501)]
            + [DamageMutation(target="Goblin", damage_type="Physical", total_damage=i, attacker="Woo", timestamp=float(i)) for i in range(5)]
            + [ImmunityMutation(target="Goblin", damage_type="Fire", immunity_points=i, damage_dealt=100 + i) for i in range(3)]
            + [AttackMutation(attacker="Woo", target="Goblin", outcome="hit", roll=10, bonus=20, total=30) for _ in range(2100)]
            + [SaveMutation(target="Goblin", save_key="fort", bonus=3), SaveMutation(target="Goblin", save_key="ref", bonus=2)]
            + [EpicDodgeMutation(target="Goblin"), EpicDodgeMutation(target="Dragon")]
        ),
        "death_snippets": [{"type": "death_snippet", "target": "Goblin", "killer": "Woo", "lines": ["a"]}],
        "death_character_identified": [
            {"type": "death_character_identified", "character_name": "Woo Wildrock"}
        ],
    }
    monkeypatch.setattr(
        "app.utils.iter_file_ops_chunks",
        lambda *args, **kwargs: iter([
            {
                "mutations": ops["mutations"][:4000],
                "death_snippets": ops["death_snippets"],
                "death_character_identified": ops["death_character_identified"],
            },
            {
                "mutations": ops["mutations"][4000:],
                "death_snippets": [],
                "death_character_identified": [],
            },
        ]),
    )

    result_queue = _CaptureQueue()
    import_worker_process(
        file_paths=["a.txt"],
        parse_immunity=False,
        abort_event=_AbortEvent(False),
        result_queue=result_queue,
    )

    events = [item["event"] for item in result_queue.items]
    assert events[0] == "file_started"
    assert events[-2] == "file_completed"
    assert events[-1] == "done"

    chunk_events = [item for item in result_queue.items if item["event"] == "ops_chunk"]
    assert len(chunk_events) == 2

    reconstructed = {"mutations": [], "death_snippets": [], "death_character_identified": []}
    for chunk in chunk_events:
        for key in reconstructed:
            reconstructed[key].extend(chunk["ops"].get(key, []))

    assert reconstructed == ops


def test_import_worker_process_exits_promptly_when_queue_full_and_abort_set(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.utils.iter_file_ops_chunks",
        lambda *args, **kwargs: iter([{
            "mutations": [],
            "death_snippets": [],
            "death_character_identified": [],
        }]),
    )
    monkeypatch.setattr(app.utils, "IMPORT_QUEUE_PUT_TIMEOUT_SEC", 0.001)
    monkeypatch.setattr(app.utils, "IMPORT_QUEUE_ABORT_PUT_GRACE_SEC", 0.01)

    abort_event = _AbortAfterChecksEvent(checks_before_abort=3)
    full_queue = _AlwaysFullQueue()

    start = time.monotonic()
    import_worker_process(
        file_paths=["a.txt"],
        parse_immunity=False,
        abort_event=abort_event,
        result_queue=full_queue,
    )
    elapsed = time.monotonic() - start

    assert elapsed < 0.25
    assert full_queue.put_calls > 0


def test_iter_file_ops_chunks_streams_large_parse_without_materializing(monkeypatch) -> None:
    log_data = "".join(
        "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (50 Physical)\n"
        for _ in range(2500)
    )
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(log_data))

    chunks = list(iter_file_ops_chunks("ignored.txt", parse_immunity=False, chunk_size=2000))

    assert len(chunks) == 3
    assert len(chunks[0]["mutations"]) == 2000
    assert len(chunks[1]["mutations"]) == 2000
    assert len(chunks[2]["mutations"]) == 1000


def test_shared_ingestion_engine_matches_queue_processor_and_import_payloads(monkeypatch) -> None:
    now = datetime(2026, 1, 9, 14, 30, 0)
    parsed_events = [
        ImmunityObservedEvent(
            target="Goblin",
            damage_type="Fire",
            immunity_points=10,
            dmg_reduced=10,
            timestamp=now,
            line_number=1,
        ),
        DamageDealtEvent(
            attacker="Woo",
            target="Goblin",
            total_damage=50,
            damage_types={"Physical": 30, "Fire": 20},
            timestamp=now,
            line_number=2,
        ),
        AttackHitEvent(
            attacker="Woo",
            target="Goblin",
            roll=14,
            bonus=5,
            total=19,
            timestamp=now,
            line_number=3,
        ),
        SaveObservedEvent(
            target="Goblin",
            save_type="fort",
            bonus=12,
            timestamp=now,
            line_number=4,
        ),
        DeathSnippetEvent(
            target="Goblin",
            killer="Woo",
            lines=["a", "b"],
            timestamp=now,
            line_number=5,
        ),
        DeathCharacterIdentifiedEvent(
            character_name="Woo Wildrock",
            timestamp=now,
            line_number=6,
        ),
    ]

    engine = EventIngestionEngine(parse_immunity=True)
    engine_mutations = []
    engine_deaths = []
    engine_identity = []
    for parsed_event in parsed_events:
        result = engine.consume(parsed_event)
        engine_mutations.extend(result.mutations)
        if result.death_event:
            engine_deaths.append(result.death_event)
        if result.character_identified:
            engine_identity.append(result.character_identified)

    processor = QueueProcessor(DataStore(), LogParser(parse_immunity=True))
    live_queue: queue.Queue = queue.Queue()
    for parsed_event in parsed_events:
        live_queue.put(parsed_event)
    live_result = processor.process_queue(live_queue, Mock())

    parse_results = iter(parsed_events)
    monkeypatch.setattr(
        "app.parser.LogParser.parse_line",
        lambda self, line: next(parse_results, None),
    )
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: io.StringIO("\n".join("line" for _ in parsed_events)),
    )
    import_result = parse_file_to_ops("ignored.txt", parse_immunity=True)

    def _normalize_death_events(items):
        return [
            {
                "type": item.type,
                "target": item.target,
                "killer": item.killer,
                "lines": item.lines or [],
                "timestamp": item.timestamp,
            }
            for item in items
        ]

    def _normalize_identity_events(items):
        return [
            {
                "type": item.type,
                "character_name": item.character_name,
            }
            for item in items
        ]

    assert live_result.dps_updated is True
    assert live_result.damage_targets == {"Goblin"}
    assert live_result.targets_to_refresh == {"Goblin"}
    assert live_result.immunity_targets == {"Goblin"}
    assert live_result.death_events == engine_deaths
    assert live_result.character_identity_events == engine_identity
    assert engine_mutations == import_result["ops"]["mutations"]
    assert _normalize_death_events(live_result.death_events) == import_result["ops"]["death_snippets"]
    assert _normalize_identity_events(live_result.character_identity_events) == import_result["ops"]["death_character_identified"]
