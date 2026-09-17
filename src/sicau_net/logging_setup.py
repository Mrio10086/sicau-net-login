"""日志：滚动写入 %LOCALAPPDATA%/sicau-net-login/logs/app.log。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config as config_module

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5


def setup(verbose: bool = False, path: Path | None = None) -> Path:
    target = Path(path) if path else config_module.log_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    file_handler = RotatingFileHandler(
        target, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(file_handler)

    # pythonw.exe 下 sys.stderr 可能为 None
    if verbose and getattr(sys, "stderr", None) is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(stream_handler)

    return target

