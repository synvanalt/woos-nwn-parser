"""Unit tests for load-and-parse workflow in main window."""

import threading
import queue
from collections import deque
from unittest.mock import Mock

import app.ui.main_window as main_window_module
from app.models import DamageMutation, SaveMutation
from app.ui.main_window import WoosNwnParserApp
from app.parser import LogParser


def _make_app_shell() -> WoosNwnParserApp:
    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    app.is_importing = False
    app.is_monitoring = False
    app.monitoring_was_active_before_import = False
    app.import_abort_event = threading.Event()
    app.import_thread = None
    app.import_process = None
    app.import_abort_flag = None
    app.import_result_queue = None
    app.import_poll_job = None
    app.import_modal = None
    app.import_status_text = None
    app.import_progress_text = None
    app.import_abort_button = None
    app._import_status_lock = threading.Lock()
    app._import_status = {}
    app._pending_file_payloads = deque()
    app._is_applying_payload = False
    app._last_modal_file = ""
    app._last_modal_files_completed = -1
    app.window_icon_path = None
    app.parser = LogParser(parse_immunity=True)
    app.pause_monitoring = Mock()
    app._set_import_ui_busy = Mock()
    app._show_import_modal = Mock()
    app._start_import_worker = Mock()
    app._poll_import_progress = Mock()
    return app


def _patch_perf_counter(monkeypatch, values: list[float]) -> None:
    """Patch main-window perf_counter to return deterministic values."""
    ticks = iter(values)
    monkeypatch.setattr(main_window_module, "perf_counter", lambda: next(ticks))


class TestLoadAndParseWorkflow:
    """Test suite for selected-file load and parse controls."""

    def test_cancelled_file_selection_noops(self, monkeypatch) -> None:
        app = _make_app_shell()
        monkeypatch.setattr(main_window_module.filedialog, "askopenfilenames", lambda **kwargs: ())

        app.load_and_parse_selected_files()

        assert app.is_importing is False
        app.pause_monitoring.assert_not_called()
        app._set_import_ui_busy.assert_not_called()
        app._start_import_worker.assert_not_called()

    def test_import_pauses_monitoring_and_sorts_files(self, monkeypatch) -> None:
        app = _make_app_shell()
        app.is_monitoring = True
        monkeypatch.setattr(
            main_window_module.filedialog,
            "askopenfilenames",
            lambda **kwargs: ("/tmp/zeta.txt", "/tmp/alpha.txt"),
        )

        app.load_and_parse_selected_files()

        assert app.is_importing is True
        assert app.monitoring_was_active_before_import is True
        app.pause_monitoring.assert_called_once()
        app._set_import_ui_busy.assert_called_once_with(True)
        app._show_import_modal.assert_called_once()
        app._poll_import_progress.assert_called_once()
        args, _ = app._start_import_worker.call_args
        assert [p.name for p in args[0]] == ["alpha.txt", "zeta.txt"]

    def test_abort_sets_event_and_disables_button(self) -> None:
        app = _make_app_shell()
        app.is_importing = True
        app.import_abort_button = Mock()
        app.import_status_text = Mock()

        app.abort_load_parse()

        assert app.import_abort_event.is_set() is True
        app.import_abort_button.config.assert_called_once()
        app.import_status_text.set.assert_called_once_with("Aborting...")

    def test_finalize_import_resets_ui_and_refreshes(self) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.import_poll_job = "poll-id"
        app.is_importing = True
        app.refresh_targets = Mock()
        app.dps_panel = Mock()
        app.log_debug = Mock()
        progress = Mock()
        modal = Mock()
        modal._progressbar = progress
        app.import_modal = modal
        app._import_status = {
            "total_files": 2,
            "errors": [],
            "aborted": False,
        }

        app._finalize_import()

        app.root.after_cancel.assert_called_once_with("poll-id")
        app._set_import_ui_busy.assert_called_once_with(False)
        progress.stop.assert_called_once()
        modal.grab_release.assert_called_once()
        modal.destroy.assert_called_once()
        app.refresh_targets.assert_called_once()
        app.dps_panel.refresh.assert_called_once()
        assert app.is_importing is False

    def test_clear_data_clears_target_stats_cache(self) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.data_store = Mock()
        app.immunity_panel = Mock()
        app.immunity_panel.tree.get_children.return_value = ("iid1",)
        app.dps_panel = Mock()
        app.dps_panel.tree.get_children.return_value = ("iid2",)
        app.stats_panel = Mock()
        app.stats_panel.tree.get_children.return_value = ("iid3",)
        app.death_snippet_panel = Mock()
        app.dps_service = Mock()
        app.refresh_targets = Mock()
        app.dps_refresh_job = None
        app._refresh_job = None
        app._dps_dirty = False
        app._targets_dirty = False
        app._immunity_dirty_targets = set()

        app.clear_data()

        app.stats_panel.clear_cache.assert_called_once()
        app.refresh_targets.assert_called_once()

    def test_file_counter_updates_immediately_on_file_completed_event(self) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.root.after = Mock()
        app.import_result_queue = queue.Queue()
        app._import_status = {
            "files_completed": 0,
            "total_files": 2,
            "current_file": "alpha.txt",
            "errors": [],
            "aborted": False,
            "success": False,
            "worker_done": False,
        }
        app.import_result_queue.put({
            "event": "file_completed",
            "index": 1,
            "file_name": "alpha.txt",
        })

        app._drain_import_events()

        assert app._import_status["files_completed"] == 1
        assert len(app._pending_file_payloads) == 0
        app.root.after.assert_not_called()

    def test_on_death_snippet_forwards_event_to_panel(self) -> None:
        app = _make_app_shell()
        app.death_snippet_panel = Mock()
        event = {
            "type": "death_snippet",
            "target": "Woo Wildrock",
            "killer": "HYDROXIS",
            "lines": ["line-1", "line-2"],
        }

        app._on_death_snippet(event)

        app.death_snippet_panel.add_death_event.assert_called_once_with(event)

    def test_apply_pending_payloads_uses_event_api_for_death_snippets(self) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.death_snippet_panel = Mock()
        app._is_applying_payload = True
        app._pending_file_payloads.append({
            "mutations": [],
            "death_snippets": [
                {
                    "type": "death_snippet",
                    "timestamp": None,
                    "killer": "HYDROXIS",
                    "target": "Woo Wildrock",
                    "lines": ["line-1", "line-2"],
                }
            ],
            "death_character_identified": [],
            "index": 1,
            "mutation_idx": 0,
        })

        app._apply_pending_payloads_incremental()

        app.death_snippet_panel.add_death_events.assert_called_once()

    def test_apply_pending_payloads_forwards_death_character_identified_events(self) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app._on_death_character_identified = Mock()
        app._is_applying_payload = True
        app._pending_file_payloads.append({
            "mutations": [],
            "death_snippets": [],
            "death_character_identified": [
                {
                    "type": "death_character_identified",
                    "character_name": "Woo Wildrock",
                }
            ],
            "index": 1,
            "mutation_idx": 0,
        })

        app._apply_pending_payloads_incremental()

        app._on_death_character_identified.assert_called_once_with(
            {
                "type": "death_character_identified",
                "character_name": "Woo Wildrock",
            }
        )

    def test_apply_pending_payloads_incremental_spans_ticks_and_drains(self, monkeypatch) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.root.after = Mock()
        app.data_store = Mock()
        app.death_snippet_panel = Mock()
        app._on_death_character_identified = Mock()
        app.IMPORT_APPLY_MUTATION_BATCH_SIZE = 1
        app._is_applying_payload = True
        app._pending_file_payloads.append({
            "mutations": [DamageMutation(target="Goblin", total_damage=10, attacker="Orc", timestamp=1.0, count_for_dps=True, damage_types={"slashing": 10})],
            "death_snippets": [],
            "death_character_identified": [],
            "index": 1,
            "mutation_idx": 0,
        })

        # Tick 1: process one operation then run out of time.
        _patch_perf_counter(monkeypatch, [0.0, 0.0, 0.007])
        app._apply_pending_payloads_incremental()

        assert len(app._pending_file_payloads) == 1
        assert app._pending_file_payloads[0]["mutation_idx"] == 1
        assert app._is_applying_payload is True
        app.root.after.assert_called_once_with(1, app._apply_pending_payloads_incremental)
        app.data_store.apply_mutations.assert_called_once()

        # Tick 2: finish all remaining stages and drain queue.
        _patch_perf_counter(monkeypatch, [1.0] * 20)
        app._apply_pending_payloads_incremental()

        assert len(app._pending_file_payloads) == 0
        assert app._is_applying_payload is False
        assert app.root.after.call_count == 1

    def test_is_applying_payload_lifecycle_tracks_queue_drain(self, monkeypatch) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.root.after = Mock()
        app.data_store = Mock()
        app.death_snippet_panel = Mock()
        app._on_death_character_identified = Mock()
        app.IMPORT_APPLY_MUTATION_BATCH_SIZE = 1
        app._is_applying_payload = True
        app._pending_file_payloads.append({
            "mutations": [SaveMutation(target="Goblin", save_key="fort", bonus=4)],
            "death_snippets": [],
            "death_character_identified": [],
            "index": 1,
            "mutation_idx": 0,
        })

        _patch_perf_counter(monkeypatch, [0.0, 0.0, 0.01])
        app._apply_pending_payloads_incremental()
        assert app._is_applying_payload is True
        assert len(app._pending_file_payloads) == 1

        _patch_perf_counter(monkeypatch, [1.0, 1.0, 1.001, 1.002, 1.003, 1.004])
        app._apply_pending_payloads_incremental()
        assert app._is_applying_payload is False
        assert len(app._pending_file_payloads) == 0

    def test_apply_pending_payloads_batches_multiple_mutations_per_apply_call(self, monkeypatch) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.root.after = Mock()
        app.data_store = Mock()
        app.death_snippet_panel = Mock()
        app.IMPORT_APPLY_MUTATION_BATCH_SIZE = 2
        app._is_applying_payload = True
        mutations = [
            SaveMutation(target="Goblin", save_key="fort", bonus=4),
            SaveMutation(target="Goblin", save_key="reflex", bonus=5),
            SaveMutation(target="Goblin", save_key="will", bonus=6),
        ]
        app._pending_file_payloads.append({
            "mutations": mutations,
            "death_snippets": [],
            "death_character_identified": [],
            "index": 1,
            "mutation_idx": 0,
        })

        _patch_perf_counter(monkeypatch, [0.0] * 20)
        app._apply_pending_payloads_incremental()

        assert app.data_store.apply_mutations.call_count == 2
        first_call = app.data_store.apply_mutations.call_args_list[0].args[0]
        second_call = app.data_store.apply_mutations.call_args_list[1].args[0]
        assert first_call == mutations[:2]
        assert second_call == mutations[2:]
        assert len(app._pending_file_payloads) == 0
        assert app._is_applying_payload is False

    def test_poll_import_progress_waits_for_streaming_apply_before_finalize(self, monkeypatch) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.root.after = Mock(return_value="poll-next")
        app._poll_import_progress = WoosNwnParserApp._poll_import_progress.__get__(app, WoosNwnParserApp)
        app.is_importing = True
        app.import_result_queue = queue.Queue()
        app._finalize_import = Mock()
        app.data_store = Mock()
        app.death_snippet_panel = Mock()
        app._import_status = {
            "files_completed": 0,
            "total_files": 1,
            "current_file": "alpha.txt",
            "errors": [],
            "aborted": False,
            "success": False,
            "worker_done": False,
        }
        app.import_result_queue.put({
            "event": "ops_chunk",
            "index": 1,
            "ops": {
                "mutations": [DamageMutation(target="Goblin", total_damage=10, attacker="Orc", timestamp=1.0, count_for_dps=True, damage_types={"slashing": 10})],
            },
        })
        app.import_result_queue.put({"event": "file_completed", "index": 1, "file_name": "alpha.txt"})
        app.import_result_queue.put({"event": "done"})

        app._poll_import_progress()

        assert app._is_applying_payload is True
        app.root.after.assert_called()
        app._finalize_import.assert_not_called()

        _patch_perf_counter(monkeypatch, [0.0] * 30)
        app._apply_pending_payloads_incremental()

        app._poll_import_progress()
        app._finalize_import.assert_called_once()

    def test_on_death_character_identified_sets_panel_character(self) -> None:
        app = _make_app_shell()
        app.death_snippet_panel = Mock()
        app.death_snippet_panel.get_character_name.return_value = ""

        app._on_death_character_identified(
            {"type": "death_character_identified", "character_name": "Woo Wildrock"}
        )

        app.death_snippet_panel.set_character_name.assert_called_once_with("Woo Wildrock")

    def test_on_death_character_identified_does_not_overwrite_existing_name(self) -> None:
        app = _make_app_shell()
        app.death_snippet_panel = Mock()
        app.death_snippet_panel.get_character_name.return_value = "Existing Name"

        app._on_death_character_identified(
            {"type": "death_character_identified", "character_name": "Woo Wildrock"}
        )

        app.death_snippet_panel.set_character_name.assert_not_called()

    def test_on_death_character_identified_ignores_empty_name(self) -> None:
        app = _make_app_shell()
        app.death_snippet_panel = Mock()

        app._on_death_character_identified(
            {"type": "death_character_identified", "character_name": "   "}
        )

        app.death_snippet_panel.get_character_name.assert_not_called()
        app.death_snippet_panel.set_character_name.assert_not_called()

    def test_identity_and_fallback_callbacks_update_parser(self) -> None:
        app = _make_app_shell()
        app.parser = Mock()
        app._schedule_session_settings_save = Mock()

        app._on_death_character_name_changed("Woo Wildrock")
        app._on_death_fallback_line_changed("Your God refuses to hear your prayers!")

        app.parser.set_death_character_name.assert_called_once_with("Woo Wildrock")
        app.parser.set_death_fallback_line.assert_called_once_with("Your God refuses to hear your prayers!")
        app._schedule_session_settings_save.assert_called_once()

    def test_parse_immunity_callback_updates_parser_and_schedules_save(self) -> None:
        app = _make_app_shell()
        app.parser = Mock()
        app._schedule_session_settings_save = Mock()

        app._on_parse_immunity_changed(False)

        assert app.parser.parse_immunity is False
        app._schedule_session_settings_save.assert_called_once()

    def test_build_session_settings_includes_parse_immunity(self) -> None:
        app = _make_app_shell()
        app.log_directory = r"C:\logs"
        app.death_snippet_panel = Mock()
        app.death_snippet_panel.get_fallback_death_line.return_value = "Custom fallback"
        app.parser.parse_immunity = False

        settings = app._build_session_settings()

        assert settings.log_directory == r"C:\logs"
        assert settings.death_fallback_line == "Custom fallback"
        assert settings.parse_immunity is False

    def test_schedule_session_settings_save_debounces_jobs(self) -> None:
        app = _make_app_shell()
        app.root = Mock()
        app.root.after = Mock(return_value="new-job")
        app.root.after_cancel = Mock()
        app._settings_save_delay_ms = 400
        app._settings_save_job = "old-job"
        app._flush_pending_session_settings_save = Mock()

        app._schedule_session_settings_save()

        app.root.after_cancel.assert_called_once_with("old-job")
        app.root.after.assert_called_once_with(400, app._flush_pending_session_settings_save)
        assert app._settings_save_job == "new-job"

    def test_flush_pending_session_settings_save_persists_now(self) -> None:
        app = _make_app_shell()
        app._settings_save_job = "job-id"
        app._persist_session_settings = Mock()

        app._flush_pending_session_settings_save()

        assert app._settings_save_job is None
        app._persist_session_settings.assert_called_once()

    def test_start_import_worker_passes_death_settings_to_worker(self, monkeypatch) -> None:
        app = _make_app_shell()
        app._start_import_worker = WoosNwnParserApp._start_import_worker.__get__(app, WoosNwnParserApp)
        app.parser = Mock()
        app.parser.parse_immunity = True
        app.parser.death_character_name = "Woo Wildrock"
        app.parser.death_fallback_line = "Custom fallback"

        class _FakeProcess:
            def __init__(self, target, args, daemon) -> None:
                self.target = target
                self.args = args
                self.daemon = daemon
                self.started = False

            def start(self) -> None:
                self.started = True

        class _FakeContext:
            def __init__(self) -> None:
                self.process = None
                self.event = object()
                self.queue = object()

            def Event(self):
                return self.event

            def Queue(self, maxsize=0):
                self.queue_maxsize = maxsize
                return self.queue

            def Process(self, target, args, daemon):
                self.process = _FakeProcess(target=target, args=args, daemon=daemon)
                return self.process

        fake_ctx = _FakeContext()
        monkeypatch.setattr(main_window_module.mp, "get_context", lambda _name: fake_ctx)

        app._start_import_worker([main_window_module.Path("alpha.txt")])

        assert app.import_abort_flag is fake_ctx.event
        assert app.import_result_queue is fake_ctx.queue
        assert app.import_process is fake_ctx.process
        assert fake_ctx.process is not None
        assert fake_ctx.process.started is True
        assert fake_ctx.queue_maxsize == main_window_module.IMPORT_RESULT_QUEUE_MAXSIZE
        assert fake_ctx.process.args[4] == "Woo Wildrock"
        assert fake_ctx.process.args[5] == "Custom fallback"
