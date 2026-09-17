"""守护循环：探测 -> 必要时连校园 WiFi -> 认证 -> 失败退避重试。

线索来源有两个：NetworkChangeWatcher 的网络变化事件（即时），
以及 poll_interval 的定时轮询（兜底）。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

from . import portal, wifi
from .config import Config, backoff_delay
from .netwatch import NetworkChangeWatcher

log = logging.getLogger(__name__)


class State(str, Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    LOGGING_IN = "logging_in"
    CONNECTING_WIFI = "connecting_wifi"
    NO_CREDENTIALS = "no_credentials"
    SKIPPED = "skipped"
    PAUSED = "paused"


STATE_TEXT = {
    State.UNKNOWN: "启动中",
    State.ONLINE: "已认证",
    State.OFFLINE: "未认证",
    State.LOGGING_IN: "正在登录",
    State.CONNECTING_WIFI: "正在连接校园 WiFi",
    State.NO_CREDENTIALS: "未配置账号密码",
    State.SKIPPED: "非校园网，已跳过",
    State.PAUSED: "已手动离线（自动登录已暂停）",
}


@dataclass
class Status:
    state: State = State.UNKNOWN
    message: str = ""
    detail: str = ""
    failures: int = 0
    updated_at: float = field(default_factory=time.time)

    @property
    def text(self) -> str:
        base = STATE_TEXT.get(self.state, str(self.state))
        if self.message:
            return base + "：" + self.message
        return base


class LoginWorker:
    def __init__(self, config_provider, credentials_provider, on_change=None) -> None:
        self._config_provider = config_provider
        self._credentials_provider = credentials_provider
        self._on_change = on_change
        self._watch = NetworkChangeWatcher()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused = False
        self._failures = 0
        self._status = Status()
        self._lock = threading.Lock()

    # ---------- 对外 ----------

    @property
    def status(self) -> Status:
        with self._lock:
            return self._status

    @property
    def paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="login-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._watch.stop()

    def trigger(self, reason: str = "") -> None:
        if reason:
            log.debug("收到唤醒：%s", reason)
        self._wake.set()

    def login_now(self) -> portal.Result:
        """手动登录（同时恢复被暂停的自动重连）。"""
        cfg = self._config_provider()
        credentials = self._credentials_provider()
        if credentials is None:
            return portal.Result(False, "还没有配置学号和密码")
        self._paused = False
        self._publish(Status(State.LOGGING_IN, "学号 " + credentials.username))
        result = portal.login(cfg, credentials.username, credentials.password)
        self._settle(result)
        self.trigger("manual-login")
        return result

    def logout_now(self) -> portal.Result:
        """手动离线，并暂停自动重连（否则会被立刻登回来）。"""
        result = portal.logout(self._config_provider())
        if result.ok:
            self._paused = True
            self._failures = 0
            self._publish(Status(State.PAUSED, "已手动离线"))
        else:
            self._publish(Status(State.OFFLINE, result.message, result.detail))
        self.trigger("manual-logout")
        return result

    def resume(self) -> None:
        self._paused = False
        self._failures = 0
        self.trigger("resume")

    # ---------- 内部 ----------

    def _publish(self, status: Status) -> None:
        with self._lock:
            self._status = status
        if self._on_change is not None:
            try:
                self._on_change(status)
            except Exception:
                log.exception("状态回调异常")

    def _settle(self, result: portal.Result) -> None:
        if result.ok:
            self._failures = 0
            log.info("认证成功：%s", result.message)
            self._publish(Status(State.ONLINE))
            return
        self._failures += 1
        log.warning(
            "认证失败（第 %d 次，%d 秒后重试）：%s",
            self._failures,
            backoff_delay(self._failures),
            result.message,
        )
        self._publish(
            Status(State.OFFLINE, result.message, result.detail, failures=self._failures)
        )

    def _interval(self) -> float:
        if self._failures:
            return float(backoff_delay(self._failures))
        return float(self._config_provider().poll_interval)

    def _sleep(self, seconds: float) -> bool:
        """等待 seconds 秒；被唤醒或停止则提前返回 True。"""
        deadline = time.monotonic() + max(0.0, seconds)
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._wake.wait(min(remaining, 1.0)):
                self._wake.clear()
                return True
            if self._watch.wait(0):
                log.debug("网络发生变化，立即重新检测")
                return True
        return True

    def _run(self) -> None:
        self._watch.start()
        self._wake.set()  # 启动立即跑一轮
        while not self._stop.is_set():
            try:
                status = self._cycle()
            except Exception as exc:
                log.exception("守护循环异常")
                status = Status(State.OFFLINE, "内部错误：%s" % exc)
            self._publish(status)
            self._sleep(self._interval())
            self._wake.clear()
        self._watch.stop()

    def _cycle(self) -> Status:
        cfg = self._config_provider()

        if self._paused:
            return Status(State.PAUSED, "已手动离线")

        credentials = self._credentials_provider()
        if credentials is None or not credentials.username or not credentials.password:
            self._failures = 0
            return Status(State.NO_CREDENTIALS, "请在设置里填写学号和密码")

        result = portal.probe(cfg)
        if result.online:
            self._failures = 0
            return Status(State.ONLINE)

        log.info("检测到未认证：%s", result.detail)

        ssid = wifi.current_ssid()
        if ssid and ssid not in cfg.ssids:
            if cfg.auto_connect_wifi and self._try_connect_wifi(cfg, ssid):
                ssid = wifi.current_ssid()
            if ssid and ssid not in cfg.ssids:
                self._failures = 0
                return Status(State.SKIPPED, "当前网络 %s 不在校园网白名单里" % ssid)
        elif not ssid and cfg.auto_connect_wifi:
            if self._try_connect_wifi(cfg, None):
                ssid = wifi.current_ssid()

        return self._do_login(cfg, credentials, result.params)

    def _try_connect_wifi(self, cfg: Config, current_ssid: str | None) -> bool:
        profiles = wifi.wireless_profiles()
        target = next((item for item in cfg.ssids if item in profiles), None)
        if target is None or target == current_ssid:
            if target is None:
                log.debug("本机没有保存任何校园网无线配置：%s", cfg.ssids)
            return False
        self._publish(Status(State.CONNECTING_WIFI, target))
        log.info("尝试连接校园网无线：%s", target)
        if not wifi.connect(target, interface=wifi.interface_name()):
            return False
        address = wifi.wait_for_ipv4(timeout=15.0)
        if not address:
            log.warning("已发起连接但没拿到 IPv4 地址")
            return False
        time.sleep(1.5)  # 等 BRAS 侧会话就绪
        return True

    def _do_login(self, cfg: Config, credentials, params: dict) -> Status:
        self._publish(Status(State.LOGGING_IN, "学号 " + credentials.username))
        result = portal.login(
            cfg, credentials.username, credentials.password, params=params
        )
        self._settle(result)
        return self.status
