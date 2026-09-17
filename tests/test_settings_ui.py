"""设置窗口的构建 / 取值测试（没有图形环境时自动跳过）。"""

import pytest

from sicau_net.config import Config
from sicau_net.settings_ui import SettingsWindow
from sicau_net.worker import State, Status


class FakeWorker:
    def __init__(self):
        self.status = Status(State.ONLINE)


class FakeApp:
    def __init__(self):
        self.config = Config(username="202600000")
        self.worker = FakeWorker()
        self.applied = None
        self.checked = None

    def apply_config(self, cfg):
        self.applied = cfg

    def on_setting_login(self):
        pass

    def on_setting_logout(self):
        pass

    def open_log(self):
        pass

    def check_credentials(self, username, password, done):
        self.checked = (username, password)


@pytest.fixture(scope="module")
def root():
    tk = pytest.importorskip("tkinter")
    try:
        widget = tk.Tk()
    except tk.TclError:
        pytest.skip("当前环境没有图形界面")
    widget.withdraw()
    yield widget
    widget.destroy()


@pytest.fixture(autouse=True)
def no_saved_credentials(monkeypatch):
    """别把真实保存的密码读进测试里。"""
    monkeypatch.setattr(
        "sicau_net.settings_ui.credentials.load_credentials", lambda *a, **k: None
    )


def make_window(root):
    app = FakeApp()
    window = SettingsWindow(root, app)
    window.open()
    return app, window


def test_window_builds_and_prefills(root):
    app, window = make_window(root)
    try:
        assert window.window is not None
        assert window._vars["username"].get() == "202600000"
        assert window._vars["ssids"].get() == "i_sicau_wifi6, i_sicau"
        assert window._vars["poll_interval"].get() == str(app.config.poll_interval)
        assert window._vars["auto_connect_wifi"].get() is True
    finally:
        window._on_close()


def test_open_second_time_reuses_window(root):
    _, window = make_window(root)
    try:
        first = window.window
        window.open()
        assert window.window is first
    finally:
        window._on_close()


def test_set_status_updates_label(root):
    _, window = make_window(root)
    try:
        window.set_status("已认证")
        assert "已认证" in window._status_var.get()
    finally:
        window._on_close()


def test_collect_normalises_input(root):
    _, window = make_window(root)
    try:
        window._vars["username"].set("  202600001  ")
        window._vars["ssids"].set(" i_sicau_wifi6，i_sicau , ")
        window._vars["poll_interval"].set("15")
        window._vars["auto_connect_wifi"].set(False)

        collected = window._collect()
        assert collected is not None
        cfg, _ = collected
        assert cfg.username == "202600001"
        assert cfg.ssids == ["i_sicau_wifi6", "i_sicau"]
        assert cfg.poll_interval == 15
        assert cfg.auto_connect_wifi is False
    finally:
        window._on_close()


def test_collect_rejects_non_numeric_interval(root, monkeypatch):
    _, window = make_window(root)
    warnings = []
    monkeypatch.setattr(
        "sicau_net.settings_ui.messagebox.showwarning", lambda *a, **k: warnings.append(a)
    )
    try:
        window._vars["poll_interval"].set("abc")
        assert window._collect() is None
        assert warnings
    finally:
        window._on_close()


def test_save_stores_credentials_and_applies_config(root, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        "sicau_net.settings_ui.credentials.save_credentials",
        lambda username, password: saved.update(user=username, pw=password),
    )
    monkeypatch.setattr("sicau_net.settings_ui.autostart.is_enabled", lambda: True)
    monkeypatch.setattr("sicau_net.settings_ui.messagebox.showinfo", lambda *a, **k: None)

    app, window = make_window(root)
    try:
        window._vars["password"].set("p@ssw0rd")
        window._on_save()
        assert saved == {"user": "202600000", "pw": "p@ssw0rd"}
        assert app.applied is not None
        assert app.applied.username == "202600000"
    finally:
        window._on_close()


def test_save_without_password_keeps_old_credentials(root, monkeypatch):
    saved = []
    monkeypatch.setattr(
        "sicau_net.settings_ui.credentials.save_credentials",
        lambda username, password: saved.append(username),
    )
    monkeypatch.setattr("sicau_net.settings_ui.autostart.is_enabled", lambda: True)
    monkeypatch.setattr("sicau_net.settings_ui.messagebox.showinfo", lambda *a, **k: None)

    app, window = make_window(root)
    try:
        window._vars["password"].set("")
        window._on_save()
        assert saved == []
        assert app.applied is not None
    finally:
        window._on_close()


def test_check_button_requires_credentials(root, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        "sicau_net.settings_ui.messagebox.showwarning", lambda *a, **k: warnings.append(a)
    )
    app, window = make_window(root)
    try:
        window._vars["password"].set("")
        window._on_check()
        assert warnings
        assert app.checked is None

        window._vars["password"].set("p@ssw0rd")
        window._on_check()
        assert app.checked == ("202600000", "p@ssw0rd")
    finally:
        window._on_close()

