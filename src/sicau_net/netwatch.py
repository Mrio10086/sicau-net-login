"""网络变化事件：IP 地址表一变就立刻唤醒守护循环。"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
NO_ERROR = 0


class NetworkChangeWatcher:
    """后台线程阻塞在 NotifyAddrChange 上，变化时置位事件。"""

    def __init__(
        self,
        rapid_threshold: float = 1.0,
        rapid_limit: int = 5,
        cooldown: float = 5.0,
    ) -> None:
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rapid_threshold = rapid_threshold
        self._rapid_limit = rapid_limit
        self._cooldown = cooldown

    def start(self) -> None:
        if self._thread is not None or not IS_WINDOWS:
            return
        self._thread = threading.Thread(
            target=self._loop, name="netwatch", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._event.set()

    def wait(self, timeout: float) -> bool:
        """等待网络变化或超时；返回 True 表示是被事件唤醒的。"""
        triggered = self._event.wait(timeout)
        if triggered:
            self._event.clear()
        return triggered

    def _loop(self) -> None:
        try:
            iphlpapi = ctypes.WinDLL("iphlpapi")
        except OSError as exc:
            log.debug("无法加载 iphlpapi，退化为纯轮询：%s", exc)
            return
        iphlpapi.NotifyAddrChange.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        iphlpapi.NotifyAddrChange.restype = ctypes.c_ulong

        rapid = 0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                result = iphlpapi.NotifyAddrChange(None, None)
            except OSError as exc:
                log.debug("NotifyAddrChange 异常，退化为纯轮询：%s", exc)
                return
            elapsed = time.monotonic() - started
            if self._stop.is_set():
                break
            if result == NO_ERROR and elapsed < self._rapid_threshold:
                # 某些驱动会一直立即返回，避免变成忙等
                rapid += 1
                if rapid > self._rapid_limit:
                    rapid = 0
                    self._stop.wait(self._cooldown)
                    continue
            else:
                rapid = 0
            self._event.set()
