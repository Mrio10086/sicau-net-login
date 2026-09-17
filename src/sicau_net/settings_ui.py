"""tkinter 设置窗口（在 tkinter 主线程里创建）。"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from . import autostart, credentials

log = logging.getLogger(__name__)


class SettingsWindow:
    def __init__(self, root: tk.Tk, app) -> None:
        self._root = root
        self._app = app
        self._win: tk.Toplevel | None = None
        self._status_var: tk.StringVar | None = None
        self._vars: dict = {}

    # ---------- 生命周期 ----------

    @property
    def window(self) -> tk.Toplevel | None:
        if self._win is not None and self._win.winfo_exists():
            return self._win
        return None

    def open(self) -> None:
        existing = self.window
        if existing is not None:
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
        self._build()

    def set_status(self, text: str) -> None:
        if self._status_var is not None and self.window is not None:
            self._status_var.set("当前状态：" + text)

    # ---------- 构建界面 ----------

    def _build(self) -> None:
        cfg = self._app.config
        saved = credentials.load_credentials()

        win = tk.Toplevel(self._root)
        self._win = win
        win.title("川农校园网自动登录 · 设置")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._vars = {}

        def add_entry(parent, row, label, key, value, width=34, show=None):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            var = tk.StringVar(value=str(value))
            entry = ttk.Entry(parent, textvariable=var, width=width, show=show)
            entry.grid(row=row, column=1, columnspan=2, sticky="we", padx=8, pady=4)
            self._vars[key] = var
            return entry

        def add_check(parent, row, label, key, value):
            var = tk.BooleanVar(value=bool(value))
            ttk.Checkbutton(parent, text=label, variable=var).grid(
                row=row, column=0, columnspan=3, sticky="w", padx=8, pady=2
            )
            self._vars[key] = var
            return var

        body = ttk.Frame(win, padding=10)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(body, text="账号", font=("", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 2)
        )
        row += 1
        add_entry(body, row, "学号", "username", cfg.username or (saved.username if saved else ""))
        row += 1
        add_entry(
            body, row, "密码", "password", saved.password if saved else "", show="*"
        )
        row += 1
        ttk.Button(body, text="校验学号密码", command=self._on_check).grid(
            row=row, column=1, sticky="w", padx=8, pady=(0, 6)
        )
        row += 1

        ttk.Separator(body).grid(row=row, column=0, columnspan=3, sticky="we", pady=6)
        row += 1
        ttk.Label(body, text="网络", font=("", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 2)
        )
        row += 1
        add_entry(body, row, "校园网 SSID（逗号分隔）", "ssids", ", ".join(cfg.ssids), width=36)
        row += 1
        add_entry(body, row, "检测间隔（秒）", "poll_interval", cfg.poll_interval, width=10)
        row += 1
        add_entry(body, row, "门户域名", "portal_host", cfg.portal_host)
        row += 1
        add_entry(body, row, "门户 IP（DNS 失败时兜底）", "portal_ip", cfg.portal_ip)
        row += 1
        add_entry(body, row, "BRAS 名称（兜底用）", "ac_name", cfg.ac_name)
        row += 1
        add_check(body, row, "断网时自动连接校园 WiFi", "auto_connect_wifi", cfg.auto_connect_wifi)
        row += 1
        add_check(body, row, "状态变化时弹出通知", "notify_on_change", cfg.notify_on_change)
        row += 1
        add_check(body, row, "开机自动启动", "start_with_windows", autostart.is_enabled())
        row += 1

        ttk.Separator(body).grid(row=row, column=0, columnspan=3, sticky="we", pady=6)
        row += 1
        buttons = ttk.Frame(body)
        buttons.grid(row=row, column=0, columnspan=3, sticky="we", padx=8, pady=4)
        ttk.Button(buttons, text="保存", command=self._on_save).pack(side="left", padx=3)
        ttk.Button(buttons, text="立即登录", command=self._app.on_setting_login).pack(side="left", padx=3)
        ttk.Button(buttons, text="立即离线", command=self._app.on_setting_logout).pack(side="left", padx=3)
        ttk.Button(buttons, text="打开日志", command=self._app.open_log).pack(side="left", padx=3)
        row += 1

        self._status_var = tk.StringVar(value="当前状态：" + self._app.worker.status.text)
        ttk.Label(body, textvariable=self._status_var, foreground="#555").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 6)
        )

        win.update_idletasks()
        win.lift()
        win.focus_force()

    # ---------- 事件 ----------

    def _on_close(self) -> None:
        if self.window is not None:
            self.window.destroy()
        self._win = None
        self._status_var = None

    def _collect(self):
        from .config import Config

        cfg = self._app.config
        values = {key: var.get() for key, var in self._vars.items()}

        ssids = [item.strip() for item in str(values["ssids"]).replace("，", ",").split(",")]
        cfg.ssids = [item for item in ssids if item]
        try:
            cfg.poll_interval = int(str(values["poll_interval"]).strip())
        except ValueError:
            messagebox.showwarning("川农校园网", "检测间隔必须是数字", parent=self.window)
            return None

        cfg.username = str(values["username"]).strip()
        cfg.portal_host = str(values["portal_host"]).strip()
        cfg.portal_ip = str(values["portal_ip"]).strip()
        cfg.ac_name = str(values["ac_name"]).strip()
        cfg.auto_connect_wifi = bool(values["auto_connect_wifi"])
        cfg.notify_on_change = bool(values["notify_on_change"])
        cfg.start_with_windows = bool(values["start_with_windows"])
        return cfg, str(values["password"])

    def _on_save(self) -> None:
        collected = self._collect()
        if collected is None:
            return
        cfg, password = collected

        want_autostart = cfg.start_with_windows
        if want_autostart != autostart.is_enabled():
            if autostart.set_enabled(want_autostart):
                cfg.start_with_windows = want_autostart
            else:
                cfg.start_with_windows = autostart.is_enabled()
                messagebox.showwarning(
                    "川农校园网", "设置开机自启失败，请查看日志", parent=self.window
                )

        if cfg.username and password:
            try:
                credentials.save_credentials(cfg.username, password)
            except Exception as exc:
                log.exception("保存凭据失败")
                messagebox.showerror("川农校园网", "保存密码失败：%s" % exc, parent=self.window)
                return

        self._app.apply_config(cfg)
        messagebox.showinfo("川农校园网", "已保存", parent=self.window)

    def _on_check(self) -> None:
        collected = self._collect()
        if collected is None:
            return
        cfg, password = collected
        if not cfg.username or not password:
            messagebox.showwarning("川农校园网", "请先填写学号和密码", parent=self.window)
            return
        self._app.check_credentials(cfg.username, password, self._show_result)

    def _show_result(self, result) -> None:
        parent = self.window
        if isinstance(result, Exception):
            messagebox.showerror("川农校园网", "校验失败：%s" % result, parent=parent)
        elif getattr(result, "ok", False):
            messagebox.showinfo("川农校园网", result.message, parent=parent)
        else:
            messagebox.showwarning("川农校园网", getattr(result, "message", str(result)), parent=parent)
