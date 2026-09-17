"""凭据存储：Windows DPAPI 加密，仅当前用户可解密。"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from . import config as config_module

log = logging.getLogger(__name__)

ENTROPY = b"sicau-net-login"
CRYPTPROTECT_UI_FORBIDDEN = 0x01
IS_WINDOWS = sys.platform == "win32"

_libs_cache = None


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _libs():
    """加载并缓存 crypt32/kernel32。"""
    global _libs_cache
    if _libs_cache is not None:
        return _libs_cache
    if not IS_WINDOWS:
        raise RuntimeError("凭据加密（DPAPI）仅在 Windows 上可用")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    blob_p = ctypes.POINTER(DataBlob)
    crypt32.CryptProtectData.argtypes = [
        blob_p, wintypes.LPCWSTR, blob_p, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, blob_p,
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        blob_p, ctypes.POINTER(wintypes.LPWSTR), blob_p, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, blob_p,
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    _libs_cache = (crypt32, kernel32)
    return _libs_cache


def _blob(data: bytes):
    """把 bytes 包成 DATA_BLOB，同时返回需要保活的缓冲区。"""
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def protect(data: bytes, entropy: bytes = ENTROPY) -> bytes:
    crypt32, kernel32 = _libs()
    blob_in, keep_in = _blob(data)
    blob_ent, keep_ent = _blob(entropy)
    blob_out = DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, ctypes.byref(blob_ent), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
        del keep_in, keep_ent


def unprotect(blob: bytes, entropy: bytes = ENTROPY) -> bytes:
    crypt32, kernel32 = _libs()
    blob_in, keep_in = _blob(blob)
    blob_ent, keep_ent = _blob(entropy)
    blob_out = DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, ctypes.byref(blob_ent), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
        del keep_in, keep_ent


@dataclass
class Credentials:
    username: str
    password: str


def save_credentials(username: str, password: str, path: Path | None = None) -> Path:
    target = Path(path) if path else config_module.credentials_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"username": username, "password": password}, ensure_ascii=False
    ).encode("utf-8")
    target.write_bytes(base64.b64encode(protect(payload)))
    return target


def load_credentials(path: Path | None = None) -> Credentials | None:
    target = Path(path) if path else config_module.credentials_path()
    if not target.exists():
        return None
    try:
        raw = base64.b64decode(target.read_bytes().strip(), validate=False)
        data = json.loads(unprotect(raw).decode("utf-8"))
    except Exception as exc:  # 文件损坏 / 换了电脑 / 别的用户
        log.warning("读取已保存的凭据失败：%s", exc)
        return None
    username = str(data.get("username") or "")
    password = str(data.get("password") or "")
    if not username or not password:
        return None
    return Credentials(username=username, password=password)


def clear_credentials(path: Path | None = None) -> bool:
    target = Path(path) if path else config_module.credentials_path()
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("删除凭据失败：%s", exc)
        return False


def has_credentials(path: Path | None = None) -> bool:
    target = Path(path) if path else config_module.credentials_path()
    return target.exists()
