"""开机自启：在启动文件夹放一个快捷方式，指向 pythonw.exe run_tray.pyw（无需管理员）。"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LNK_NAME = "川农校园网自动登录.lnk"


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_dir() / LNK_NAME


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def entry_script() -> Path:
    return project_root() / "run_tray.pyw"


def pythonw() -> Path:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return candidate if candidate.exists() else executable


def launcher() -> tuple:
    """开机自启要启动的东西：(TargetPath, Arguments, WorkingDirectory)。"""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        return str(executable), "", str(executable.parent)
    return str(pythonw()), '"%s"' % entry_script(), str(project_root())


def is_enabled() -> bool:
    return shortcut_path().exists()


def _run_powershell(script: str) -> bool:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("创建快捷方式失败：%s", exc)
        return False
    if proc.returncode != 0:
        log.warning(
            "PowerShell 返回 %d：%s",
            proc.returncode,
            proc.stderr.decode("utf-8", errors="replace")[:300],
        )
        return False
    return True


def enable() -> bool:
    target_path, arguments, working_dir = launcher()
    lines = [
        "$ws = New-Object -ComObject WScript.Shell",
        "$sc = $ws.CreateShortcut('%s')" % str(shortcut_path()).replace("'", "''"),
        "$sc.TargetPath = '%s'" % target_path.replace("'", "''"),
        "$sc.WorkingDirectory = '%s'" % working_dir.replace("'", "''"),
        "$sc.WindowStyle = 7",
        "$sc.Description = '川农校园网自动登录'",
    ]
    if arguments:
        lines.append("$sc.Arguments = '%s'" % arguments.replace("'", "''"))
    lines.append("$sc.Save()")
    return _run_powershell("\n".join(lines))


def disable() -> bool:
    try:
        shortcut_path().unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        log.warning("删除快捷方式失败：%s", exc)
        return False


def set_enabled(enabled: bool) -> bool:
    return enable() if enabled else disable()

