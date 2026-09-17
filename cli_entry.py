"""PyInstaller 打包入口（命令行版）。

打包后即可在没有 Python 的机器上跑 `sicau-net-cli.exe status` 之类。
"""

import pathlib
import sys

if not getattr(sys, "frozen", False):
    _src = pathlib.Path(__file__).resolve().parent / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from sicau_net.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
