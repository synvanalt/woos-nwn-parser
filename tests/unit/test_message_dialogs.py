"""Unit tests for dark modal message dialogs."""

from unittest.mock import Mock

import app.ui.message_dialogs as message_dialogs_module


class FakeToplevel:
    """Minimal stand-in for Tk Toplevel used by dialog tests."""

    def __init__(self, parent) -> None:
        self.parent = parent
        self.configure_calls = []
        self.title_value = None
        self.resizable_args = None
        self.transient_parent = None
        self.protocol_calls = {}
        self.bindings = {}
        self.geometry_value = None
        self.iconbitmap_calls = []
        self.attributes_calls = []
        self.after_idle_callbacks = []
        self.deiconified = False
        self.lifted = False
        self.grabbed = False
        self.released = False
        self.destroyed = False
        self.update_calls = 0

    def withdraw(self) -> None:
        return None

    def configure(self, **kwargs) -> None:
        self.configure_calls.append(kwargs)

    def title(self, value: str) -> None:
        self.title_value = value

    def resizable(self, width: bool, height: bool) -> None:
        self.resizable_args = (width, height)

    def transient(self, parent) -> None:
        self.transient_parent = parent

    def geometry(self, value: str) -> None:
        self.geometry_value = value

    def iconbitmap(self, value=None):
        if value is None:
            return ""
        self.iconbitmap_calls.append(value)
        return None

    def protocol(self, name: str, callback) -> None:
        self.protocol_calls[name] = callback

    def bind(self, sequence: str, callback) -> None:
        self.bindings[sequence] = callback

    def attributes(self, *args) -> None:
        self.attributes_calls.append(args)

    def update_idletasks(self) -> None:
        self.update_calls += 1

    def deiconify(self) -> None:
        self.deiconified = True

    def lift(self) -> None:
        self.lifted = True

    def grab_set(self) -> None:
        self.grabbed = True

    def grab_release(self) -> None:
        self.released = True

    def destroy(self) -> None:
        self.destroyed = True

    def after_idle(self, callback) -> None:
        self.after_idle_callbacks.append(callback)
        callback()


class FakeWidget:
    """Minimal widget shim that records pack/focus behavior."""

    instances = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.pack_calls = []
        self.focused = False
        self.command = kwargs.get("command")
        self.__class__.instances.append(self)

    def pack(self, *args, **kwargs) -> None:
        self.pack_calls.append((args, kwargs))

    def focus_set(self) -> None:
        self.focused = True


class FakeParent:
    """Minimal parent window for centering and modality tests."""

    def __init__(self) -> None:
        self.wait_window = Mock()
        self.iconbitmap = Mock(return_value="root.ico")

    def update_idletasks(self) -> None:
        return None

    def winfo_rootx(self) -> int:
        return 100

    def winfo_rooty(self) -> int:
        return 50

    def winfo_width(self) -> int:
        return 800

    def winfo_height(self) -> int:
        return 600


def test_show_warning_dialog_builds_dark_modal(monkeypatch) -> None:
    dialog_instances = []
    frame_instances = []
    label_instances = []
    button_instances = []

    def make_dialog(parent):
        dialog = FakeToplevel(parent)
        dialog_instances.append(dialog)
        return dialog

    class FakeFrame(FakeWidget):
        instances = frame_instances

    class FakeLabel(FakeWidget):
        instances = label_instances

    class FakeButton(FakeWidget):
        instances = button_instances

    apply_dark_title_bar = Mock()
    monkeypatch.setattr(message_dialogs_module.tk, "Toplevel", make_dialog)
    monkeypatch.setattr(message_dialogs_module.ttk, "Frame", FakeFrame)
    monkeypatch.setattr(message_dialogs_module.ttk, "Label", FakeLabel)
    monkeypatch.setattr(message_dialogs_module.ttk, "Button", FakeButton)
    monkeypatch.setattr(message_dialogs_module, "apply_dark_title_bar", apply_dark_title_bar)

    parent = FakeParent()
    message_dialogs_module.show_warning_dialog(
        parent,
        "No Log Files",
        "Monitoring will wait.",
        icon_path="app.ico",
    )

    dialog = dialog_instances[0]
    button = button_instances[0]

    assert dialog.configure_calls == [{"bg": "#1c1c1c"}]
    assert dialog.title_value == "No Log Files"
    assert dialog.resizable_args == (False, False)
    assert dialog.transient_parent is parent
    assert dialog.geometry_value.startswith("460x")
    assert dialog.geometry_value.endswith("+270+280")
    assert dialog.iconbitmap_calls == ["app.ico"]
    assert dialog.deiconified is True
    assert dialog.lifted is True
    assert dialog.grabbed is True
    assert button.focused is True
    assert "<Return>" in dialog.bindings
    assert "<Escape>" in dialog.bindings
    assert dialog.protocol_calls["WM_DELETE_WINDOW"] is not None
    assert parent.wait_window.call_args.args == (dialog,)
    apply_dark_title_bar.assert_called_once_with(dialog)
    assert label_instances[0].kwargs["text"] == "Monitoring will wait."
    assert label_instances[0].kwargs["wraplength"] == 420
    assert frame_instances[1].pack_calls == [((), {"side": "bottom", "fill": "x"})]
    assert button.pack_calls == [((), {"anchor": "e"})]


def test_show_warning_dialog_close_binding_releases_modal(monkeypatch) -> None:
    dialog_instances = []

    def make_dialog(parent):
        dialog = FakeToplevel(parent)
        dialog_instances.append(dialog)
        return dialog

    monkeypatch.setattr(message_dialogs_module.tk, "Toplevel", make_dialog)
    monkeypatch.setattr(message_dialogs_module.ttk, "Frame", FakeWidget)
    monkeypatch.setattr(message_dialogs_module.ttk, "Label", FakeWidget)
    monkeypatch.setattr(message_dialogs_module.ttk, "Button", FakeWidget)
    monkeypatch.setattr(message_dialogs_module, "apply_dark_title_bar", Mock())

    parent = FakeParent()
    message_dialogs_module.show_warning_dialog(parent, "Title", "Body")

    dialog = dialog_instances[0]
    dialog.bindings["<Escape>"]()

    assert dialog.released is True
    assert dialog.destroyed is True


def test_show_warning_dialog_uses_parent_icon_when_custom_icon_missing(monkeypatch) -> None:
    dialog_instances = []

    def make_dialog(parent):
        dialog = FakeToplevel(parent)
        dialog_instances.append(dialog)
        return dialog

    monkeypatch.setattr(message_dialogs_module.tk, "Toplevel", make_dialog)
    monkeypatch.setattr(message_dialogs_module.ttk, "Frame", FakeWidget)
    monkeypatch.setattr(message_dialogs_module.ttk, "Label", FakeWidget)
    monkeypatch.setattr(message_dialogs_module.ttk, "Button", FakeWidget)
    monkeypatch.setattr(message_dialogs_module, "apply_dark_title_bar", Mock())

    parent = FakeParent()
    message_dialogs_module.show_warning_dialog(parent, "Title", "Body", icon_path=None)

    assert dialog_instances[0].iconbitmap_calls == ["root.ico"]
