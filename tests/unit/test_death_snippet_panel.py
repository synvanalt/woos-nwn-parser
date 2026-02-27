"""Unit tests for DeathSnippetPanel formatting behavior."""

from app.ui.widgets.death_snippet_panel import DeathSnippetPanel


class _FakeText:
    def __init__(self, content: str = "") -> None:
        self.content = content
        self.seen = False

    def delete(self, *_args) -> None:
        self.content = ""

    def insert(self, index, text: str) -> None:
        if index == "1.0":
            self.content = text
        else:
            self.content += text

    def get(self, *_args) -> str:
        return self.content

    def index(self, _idx: str) -> str:
        return "1.0" if self.content == "" else "2.0"

    def see(self, *_args) -> None:
        self.seen = True


class TestDeathSnippetPanel:
    """Test suite for DeathSnippetPanel helper behavior."""

    def test_sanitize_display_line_removes_chat_window_prefix(self) -> None:
        line = "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"
        sanitized = DeathSnippetPanel._sanitize_display_line(line)
        assert sanitized == "[Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"

    def test_sanitize_display_line_leaves_non_prefixed_line_unchanged(self) -> None:
        line = "[Tue Jan 13 19:59:36] HYDROXYS killed Woo Wildrock"
        sanitized = DeathSnippetPanel._sanitize_display_line(line)
        assert sanitized == line

    def test_append_snippet_replaces_placeholder(self) -> None:
        panel = DeathSnippetPanel.__new__(DeathSnippetPanel)
        panel.text = _FakeText(DeathSnippetPanel.EMPTY_PLACEHOLDER)

        panel.append_snippet(["[CHAT WINDOW TEXT] [t] HYDROXYS killed Woo Wildrock"])

        assert DeathSnippetPanel.EMPTY_PLACEHOLDER not in panel.text.content
        assert "HYDROXYS killed Woo Wildrock" in panel.text.content
        assert panel.text.seen is True

    def test_clear_restores_placeholder(self) -> None:
        panel = DeathSnippetPanel.__new__(DeathSnippetPanel)
        panel.text = _FakeText("some prior content")

        panel.clear()

        assert panel.text.content == DeathSnippetPanel.EMPTY_PLACEHOLDER
