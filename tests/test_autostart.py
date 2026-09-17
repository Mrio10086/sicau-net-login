from sicau_net import autostart


def test_launcher_uses_pythonw_and_script(monkeypatch):
    monkeypatch.delattr(autostart.sys, "frozen", raising=False)
    target, arguments, working_dir = autostart.launcher()
    assert target.lower().endswith("python.exe") or target.lower().endswith("pythonw.exe")
    assert arguments.endswith('run_tray.pyw"')
    assert arguments.startswith('"')
    assert working_dir


def test_launcher_uses_exe_when_frozen(monkeypatch):
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\apps\sicau-net-login.exe")
    target, arguments, working_dir = autostart.launcher()
    assert target == r"C:\apps\sicau-net-login.exe"
    assert arguments == ""
    assert working_dir == r"C:\apps"


def test_shortcut_path_is_in_startup_folder():
    path = autostart.shortcut_path()
    assert path.name == autostart.LNK_NAME
    assert "Startup" in str(path)


def test_enable_script_quotes_arguments(monkeypatch):
    captured = {}

    def fake_run(script):
        captured["script"] = script
        return True

    monkeypatch.setattr(autostart, "_run_powershell", fake_run)
    monkeypatch.delattr(autostart.sys, "frozen", raising=False)
    assert autostart.enable() is True
    assert "$sc.Arguments = '\"" in captured["script"]
    assert "$sc.Save()" in captured["script"]


def test_enable_script_omits_arguments_when_frozen(monkeypatch):
    captured = {}

    def fake_run(script):
        captured["script"] = script
        return True

    monkeypatch.setattr(autostart, "_run_powershell", fake_run)
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\apps\sicau-net-login.exe")
    assert autostart.enable() is True
    assert "Arguments" not in captured["script"]
    assert r"C:\apps\sicau-net-login.exe" in captured["script"]
