# -*- coding: utf-8 -*-
"""命令行入口（等价于 python -m sicau_net.cli）。"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from sicau_net.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
