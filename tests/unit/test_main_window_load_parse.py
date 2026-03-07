"""Unit tests for load-and-parse workflow in main window."""

import threading
import queue
from collections import deque
from unittest.mock import Mock

import app.ui.main_window as main_window_module
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
            "ops": {
                "dps_updates": [],
                "damage_events": [],
                "immunity_records": [],
                "attack_events": [],
            },
            "parser_state": {
                "target_ac": {},
                "target_saves": {},
                "target_attack_bonus": {},
            },
        })

        app._drain_import_events()

        assert app._import_status["files_completed"] == 1
        assert len(app._pending_file_payloads) == 1
        app.root.after.assert_called_once()

    def test_merge_parser_state_preserves_and_combines_values(self) -> None:
        app = _make_app_shell()
        app.parser = LogParser(parse_immunity=True)

        # Existing state in main parser
        app.parser.parse_line("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Orc attacks Goblin: *hit*: (14 + 5 = 19)")
        app.parser.parse_line("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] SAVE: Goblin: Fortitude Save: *success*: (12 + 2 = 14 vs. DC: 20)")

        worker_parser = LogParser(parse_immunity=True)
        worker_parser.parse_line("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] Orc attacks Goblin: *miss*: (15 + 5 = 20)")
        worker_parser.parse_line("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:02] Goblin : Epic Dodge : Attack evaded")
        worker_parser.parse_line("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:03] SAVE: Goblin: Fortitude Save: *success*: (13 + 4 = 17 vs. DC: 20)")
        worker_parser.parse_line("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:04] SAVE: Goblin: Reflex Save: *failed*: (8 + 1 = 9 vs. DC: 20)")

        app._merge_parser_state({
            "target_ac": worker_parser.target_ac,
            "target_saves": worker_parser.target_saves,
            "target_attack_bonus": worker_parser.target_attack_bonus,
        })

        assert "Goblin" in app.parser.target_ac
        assert app.parser.target_ac["Goblin"].has_epic_dodge is True
        assert "Goblin" in app.parser.target_saves
        assert app.parser.target_saves["Goblin"].fortitude == 4
        assert app.parser.target_saves["Goblin"].reflex == 1
        assert "Orc" in app.parser.target_attack_bonus

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
            "ops": {
                "death_snippets": [
                    {
                        "type": "death_snippet",
                        "timestamp": None,
                        "killer": "HYDROXIS",
                        "target": "Woo Wildrock",
                        "lines": ["line-1", "line-2"],
                    }
                ],
            },
            "parser_state": {
                "target_ac": {},
                "target_saves": {},
                "target_attack_bonus": {},
            },
            "index": 1,
            "progress": {"stage": "death_snippet", "idx": 0},
            "state_merged": False,
        })

        app._apply_pending_payloads_incremental()

        app.death_snippet_panel.add_death_event.assert_called_once()

    def test_on_death_character_identified_sets_panel_character(self) -> None:
        app = _make_app_shell()
        app.death_snippet_panel = Mock()

        app._on_death_character_identified(
            {"type": "death_character_identified", "character_name": "Woo Wildrock"}
        )

        app.death_snippet_panel.set_character_name.assert_called_once_with("Woo Wildrock")

    def test_identity_and_fallback_callbacks_update_parser(self) -> None:
        app = _make_app_shell()
        app.parser = Mock()

        app._on_death_character_name_changed("Woo Wildrock")
        app._on_death_fallback_line_changed("Your God refuses to hear your prayers!")

        app.parser.set_death_character_name.assert_called_once_with("Woo Wildrock")
        app.parser.set_death_fallback_line.assert_called_once_with("Your God refuses to hear your prayers!")

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

            def Queue(self):
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
        assert fake_ctx.process.args[4] == "Woo Wildrock"
        assert fake_ctx.process.args[5] == "Custom fallback"
