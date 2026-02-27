"""Unit tests for load-and-parse workflow in main window."""

import threading
from unittest.mock import Mock

import app.ui.main_window as main_window_module
from app.ui.main_window import WoosNwnParserApp


def _make_app_shell() -> WoosNwnParserApp:
    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    app.is_importing = False
    app.is_monitoring = False
    app.monitoring_was_active_before_import = False
    app.import_abort_event = threading.Event()
    app.import_thread = None
    app.import_poll_job = None
    app.import_modal = None
    app.import_status_text = None
    app.import_progress_text = None
    app.import_abort_button = None
    app._import_status_lock = threading.Lock()
    app._import_status = {}
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
            "lines_processed": 42,
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
