"""应用装配：tkinter 主线程 + 托盘线程 + 守护线程，用队列把动作送回主线程。

线程约定：
  * tkinter 只在主线程使用；
  * pystray 跑在自己的线程里，菜单回调只往队列里丢东西；
  * 网络操作（登录/离线/校验）跑在临时后台线程里，结果同样回队列。
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox

from . import config as config_module
from . import credentials, logging_setup, portal
from .settings_ui import SettingsWindow
from .tray import TrayIcon
from .worker import LoginWorker, State, Status

log = logging.getLogger(__name__)

DRAIN_INTERVAL_MS = 200
NOTIFY_STATES = (State.ONLINE, State.OFFLINE, State.NO_CREDENTIALS)


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("川农校园网自动登录")

        self._queue: queue.Queue = queue.Queue()
        self._last_state: State | None = None
        self._shutting_down = False

        self.config = config_module.load()
        if not self.config.username:
            saved = credentials.load_credentials()
            if saved:
                self.config.username = saved.username

        self.worker = LoginWorker(
            self._get_config, credentials.load_credentials, self._on_status
        )
        self.settings = SettingsWindow(self.root, self)
        self.tray = TrayIcon(self._menu_actions())

    # ---------- 生命周期 ----------

    def run(self) -> None:
        log.info("程序启动，数据目录：%s", config_module.app_dir())
        self.worker.start()
        self.tray.run_detached()
        self.root.after(DRAIN_INTERVAL_MS, self._drain)

        if not credentials.has_credentials():
            self.root.after(400, self.settings.open)
            self.tray.notify("还没有保存学号密码，请先在设置里填写", "川农校园网")

        try:
            self.root.mainloop()
        finally:
            self._shutdown()

    def quit(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        log.info("退出")
        self.worker.stop()
        self.tray.stop()
        self.root.after(0, self.root.destroy)

    def _shutdown(self) -> None:
        self.worker.stop()
        self.tray.stop()

    # ---------- 供设置窗口调用 ----------

    def apply_config(self, cfg) -> None:
        self.config = cfg
        try:
            config_module.save(cfg)
        except OSError as exc:
            log.warning("保存配置失败：%s", exc)
        self.worker.trigger("config-changed")

    def on_setting_login(self) -> None:
        self._async(self.worker.login_now, self._report_result)

    def on_setting_logout(self) -> None:
        self._async(self.worker.logout_now, self._report_result)

    def check_credentials(self, username: str, password: str, done) -> None:
        self._async(lambda: portal.check_credentials(self.config, username, password), done)

    def open_log(self) -> None:
        path = config_module.log_path()
        try:
            if path.exists():
                os.startfile(str(path))  # noqa: S606 - Windows 专用
            else:
                os.startfile(str(path.parent))
        except OSError as exc:
            log.warning("打开日志失败：%s", exc)
            messagebox.showwarning("川农校园网", "打开日志失败：%s" % exc, parent=self._parent())

    # ---------- 内部 ----------

    def _get_config(self):
        return self.config

    def _parent(self):
        return self.settings.window or None

    def _menu_actions(self) -> dict:
        return {
            "login": lambda: self._queue.put(("action", "login")),
            "logout": lambda: self._queue.put(("action", "logout")),
            "settings": lambda: self._queue.put(("action", "settings")),
            "open_log": lambda: self._queue.put(("action", "open_log")),
            "clear_credentials": lambda: self._queue.put(("action", "clear_credentials")),
            "quit": lambda: self._queue.put(("action", "quit")),
        }

    def _on_status(self, status: Status) -> None:
        """来自守护线程。"""
        self._queue.put(("status", status))

    def _drain(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if kind == "status":
                    self._apply_status(payload)
                elif kind == "action":
                    self._handle_action(payload)
                elif kind == "done":
                    callback, result = payload
                    callback(result)
            except Exception:
                log.exception("处理 %s 消息失败", kind)
        self.root.after(DRAIN_INTERVAL_MS, self._drain)

    def _apply_status(self, status: Status) -> None:
        self.tray.update(status.state, status.text)
        self.settings.set_status(status.text)

        if status.state != self._last_state:
            previous = self._last_state.value if self._last_state else "启动"
            log.info("状态变化：%s -> %s", previous, status.state.value)
            if (
                self._last_state is not None
                and self.config.notify_on_change
                and status.state in NOTIFY_STATES
            ):
                self.tray.notify(status.text, "川农校园网")
            self._last_state = status.state

    def _handle_action(self, name: str) -> None:
        if name == "login":
            self._async(self.worker.login_now, self._report_result)
        elif name == "logout":
            self._async(self.worker.logout_now, self._report_result)
        elif name == "settings":
            self.settings.open()
        elif name == "open_log":
            self.open_log()
        elif name == "clear_credentials":
            self._clear_credentials()
        elif name == "quit":
            self.quit()

    def _clear_credentials(self) -> None:
        if not messagebox.askyesno(
            "川农校园网", "确定要删除已保存的学号和密码吗？", parent=self._parent()
        ):
            return
        credentials.clear_credentials()
        self.config.username = ""
        self.apply_config(self.config)
        messagebox.showinfo("川农校园网", "已清除已保存的密码", parent=self._parent())

    def _async(self, func, done) -> None:
        def job() -> None:
            try:
                result = func()
            except Exception as exc:
                log.exception("后台任务失败")
                result = exc
            self._queue.put(("done", (done, result)))

        threading.Thread(target=job, daemon=True).start()

    def _report_result(self, result) -> None:
        parent = self._parent()
        if isinstance(result, Exception):
            messagebox.showerror("川农校园网", "操作失败：%s" % result, parent=parent)
        elif getattr(result, "ok", False):
            messagebox.showinfo("川农校园网", result.message, parent=parent)
        else:
            messagebox.showwarning(
                "川农校园网", getattr(result, "message", str(result)), parent=parent
            )


def main() -> None:
    logging_setup.setup()
    app = App()
    app.run()

