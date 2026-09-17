"""无线网卡操作，全部走 netsh，不引入额外依赖。"""

from __future__ import annotations

import logging
import re
import socket
import subprocess
import time

log = logging.getLogger(__name__)

NETSH_TIMEOUT = 15
_SSID_RE = re.compile(r"^\s*SSID\s*:\s*(.+?)\s*$", re.M)
_NAME_RE = re.compile(r"^\s*(?:Name|名称)\s*:\s*(.+?)\s*$", re.M)


def _decode(raw: bytes) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run(args, timeout: int = NETSH_TIMEOUT) -> str | None:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug("执行 %s 失败：%s", args, exc)
        return None
    return _decode(proc.stdout) + _decode(proc.stderr)


def interfaces_info() -> str | None:
    return _run(["netsh", "wlan", "show", "interfaces"])


def current_ssid() -> str | None:
    """当前连接的 SSID；未连接无线网络时返回 None。"""
    out = interfaces_info()
    if not out:
        return None
    match = _SSID_RE.search(out)
    return match.group(1).strip() if match else None


def interface_name() -> str | None:
    out = interfaces_info()
    if not out:
        return None
    match = _NAME_RE.search(out)
    return match.group(1).strip() if match else None


def wireless_profiles() -> list:
    """本机已保存的无线配置文件（通常是 SSID）。"""
    out = _run(["netsh", "wlan", "show", "profiles"])
    if not out:
        return []
    profiles = []
    for line in out.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.rpartition(":")
        if "Profile" in label or "配置文件" in label:
            value = value.strip()
            if value and value not in profiles:
                profiles.append(value)
    return profiles


def connect(ssid: str, interface: str | None = None, timeout: int = NETSH_TIMEOUT) -> bool:
    """发起 netsh wlan connect。"""
    args = ["netsh", "wlan", "connect", "name=" + ssid]
    if interface:
        args.append("interface=" + interface)
    out = _run(args, timeout=timeout)
    if out is None:
        return False
    log.info("尝试连接无线网 %s：%s", ssid, out.strip().splitlines()[-1] if out.strip() else "")
    return ("成功" in out) or ("success" in out.lower())


def local_ipv4(targets=("10.255.248.9", "1.1.1.1")) -> str | None:
    """取本机在校园网侧出口的 IPv4（UDP connect 不会真的发包）。"""
    for host in targets:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.5)
            sock.connect((host, 53))
            address = sock.getsockname()[0]
        except OSError:
            continue
        finally:
            sock.close()
        if address and address != "0.0.0.0" and not address.startswith("127."):
            return address
    return None


def wait_for_ipv4(timeout: float = 15.0, interval: float = 1.0) -> str | None:
    """等待 DHCP 拿到地址。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        address = local_ipv4()
        if address:
            return address
        time.sleep(interval)
    return None
