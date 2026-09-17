"""配置读写。

非敏感配置放在 %LOCALAPPDATA%/sicau-net-login/config.json，
密码单独用 DPAPI 加密后放在同目录的 cred.dat。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_DIR_NAME = "sicau-net-login"
ENV_HOME = "SICAU_NET_HOME"

DEFAULT_SSIDS = ["i_sicau_wifi6", "i_sicau"]
DEFAULT_PROBE_URL = "http://connect.rom.miui.com/generate_204"
DEFAULT_PORTAL_HOST = "portal.sicau.edu.cn"
DEFAULT_PORTAL_IP = "10.255.248.9"
DEFAULT_AC_NAME = "YA-XX-Bras01-ME60-X8A"
DEFAULT_POLL_INTERVAL = 30

# 认证失败后的重试间隔（秒），最后一次会一直重复
BACKOFF_SECONDS = (5, 10, 30, 60)


def app_dir() -> Path:
    """数据目录。设置 SICAU_NET_HOME 可覆盖（测试用）。"""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / APP_DIR_NAME


def config_path() -> Path:
    return app_dir() / "config.json"


def credentials_path() -> Path:
    return app_dir() / "cred.dat"


def log_path() -> Path:
    return app_dir() / "logs" / "app.log"


@dataclass
class Config:
    username: str = ""
    ssids: list = field(default_factory=lambda: list(DEFAULT_SSIDS))
    poll_interval: int = DEFAULT_POLL_INTERVAL
    portal_host: str = DEFAULT_PORTAL_HOST
    portal_ip: str = DEFAULT_PORTAL_IP
    ac_name: str = DEFAULT_AC_NAME
    auto_connect_wifi: bool = True
    start_with_windows: bool = False
    notify_on_change: bool = True
    probe_url: str = DEFAULT_PROBE_URL

    @property
    def base_url(self) -> str:
        return "https://" + self.portal_host


def backoff_delay(failures: int) -> int:
    """第 failures 次连续失败后应等待的秒数。"""
    if failures <= 0:
        return 0
    index = min(failures - 1, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[index]


def _clean(cfg: Config) -> Config:
    if not isinstance(cfg.ssids, list):
        cfg.ssids = list(DEFAULT_SSIDS)
    cleaned = [str(item).strip() for item in cfg.ssids if str(item).strip()]
    cfg.ssids = cleaned or list(DEFAULT_SSIDS)
    try:
        cfg.poll_interval = max(5, min(3600, int(cfg.poll_interval)))
    except (TypeError, ValueError):
        cfg.poll_interval = DEFAULT_POLL_INTERVAL
    for name in ("username", "portal_host", "portal_ip", "ac_name", "probe_url"):
        value = getattr(cfg, name)
        setattr(cfg, name, str(value).strip() if value is not None else "")
    if not cfg.portal_host:
        cfg.portal_host = DEFAULT_PORTAL_HOST
    if not cfg.probe_url:
        cfg.probe_url = DEFAULT_PROBE_URL
    return cfg


def load(path: Path | None = None) -> Config:
    """读取配置，缺省/损坏时回落到内置默认值。"""
    target = Path(path) if path else config_path()
    data = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    known = {item.name for item in fields(Config)}
    kwargs = {key: value for key, value in data.items() if key in known}
    try:
        cfg = Config(**kwargs)
    except TypeError:
        cfg = Config()
    return _clean(cfg)


def save(cfg: Config, path: Path | None = None) -> Path:
    target = Path(path) if path else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(_clean(cfg)), ensure_ascii=False, indent=2)
    target.write_text(payload + "\n", encoding="utf-8")
    return target

