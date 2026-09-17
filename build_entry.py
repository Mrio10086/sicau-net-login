"""PyInstaller 打包入口（开发时也能直接跑）。

打包成 exe 后 sys.frozen 为真，代码已经在包内，不能再往 sys.path 塞源码目录。
"""

import pathlib
import sys

if not getattr(sys, "frozen", False):
    _src = pathlib.Path(__file__).resolve().parent / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from sicau_net.app import main  # noqa: E402

if __name__ == "__main__":
    main()
