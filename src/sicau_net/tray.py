"""系统托盘图标与右键菜单（pystray + Pillow）。"""

from __future__ import annotations

import logging
import threading

from PIL import Image, ImageDraw

from .worker import State

log = logging.getLogger(__name__)

COLORS = {
    State.ONLINE: (46, 160, 67, 255),
    State.LOGGING_IN: (219, 154, 4, 255),
    State.CONNECTING_WIFI: (219, 154, 4, 255),
    State.OFFLINE: (207, 34, 46, 255),
    State.NO_CREDENTIALS: (128, 128, 128, 255),
    State.SKIPPED: (128, 128, 128, 255),
    State.PAUSED: (128, 128, 128, 255),
    State.UNKNOWN: (128, 128, 128, 255),
}

TITLES = {
    State.ONLINE: "川农校园网：已认证",
    State.LOGGING_IN: "川农校园网：正在登录",
    State.CONNECTING_WIFI: "川农校园网：正在连接 WiFi",
    State.OFFLINE: "川农校园网：未认证",
    State.NO_CREDENTIALS: "川农校园网：未配置账号",
    State.SKIPPED: "川农校园网：非校园网",
    State.PAUSED: "川农校园网：已手动离线",
    State.UNKNOWN: "川农校园网自动登录",
}


def make_icon(state: State, size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(2, size // 8)
    box = [margin, margin, size - margin, size - margin]
    draw.ellipse(box, fill=COLORS.get(state, COLORS[State.UNKNOWN]))
    draw.ellipse(box, outline=(255, 255, 255, 220), width=max(1, size // 16))
    return image


class TrayIcon:
    def __init__(self, actions: dict, initial_state: State = State.UNKNOWN) -> None:
        import pystray

        self._pystray = pystray
        self._actions = actions
        self._state = initial_state
        self._status_text = "启动中"
        self._thread: threading.Thread | None = None
        self.icon = pystray.Icon(
            "sicau-net-login",
            make_icon(initial_state),
            TITLES.get(initial_state, TITLES[State.UNKNOWN]),
            menu=self._build_menu(),
        )

    # ---------- 菜单 ----------

    def _build_menu(self):
        pystray = self._pystray
        MenuItem = pystray.MenuItem
        return pystray.Menu(
            MenuItem(lambda item: self._status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            MenuItem("立即登录", self._wrap("login")),
            MenuItem("立即离线", self._wrap("logout")),
            pystray.Menu.SEPARATOR,
            MenuItem("查看日志", self._wrap("open_log")),
            MenuItem("设置…", self._wrap("settings")),
            MenuItem("清除已保存的密码", self._wrap("clear_credentials")),
            pystray.Menu.SEPARATOR,
            MenuItem("退出", self._wrap("quit")),
        )

    def _wrap(self, name: str):
        def handler(icon, item):
            action = self._actions.get(name)
            if action is None:
                return
            try:
                action()
            except Exception:
                log.exception("托盘菜单动作 %s 失败", name)

        return handler

    # ---------- 生命周期 ----------

    def run_detached(self) -> None:
        """托盘消息循环放在自己的线程里（tkinter 要用主线程）。

        线程里抛异常不会有人接，所以这里务必记日志，
        否则 pythonw / exe 下就是"悄悄没有图标"。
        """

        def runner() -> None:
            try:
                self.icon.run()
            except Exception:
                log.exception("托盘线程异常退出，图标可能不会显示")

        self._thread = threading.Thread(target=runner, name="tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass

    def update(self, state: State, text: str) -> None:
        self._state = state
        self._status_text = text
        try:
            self.icon.icon = make_icon(state)
            self.icon.title = TITLES.get(state, TITLES[State.UNKNOWN])
            self.icon.update_menu()
        except Exception:
            log.exception("刷新托盘图标失败")

    def notify(self, message: str, title: str = "川农校园网") -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            log.debug("托盘通知失败", exc_info=True)

