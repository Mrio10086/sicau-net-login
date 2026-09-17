# -*- coding: utf-8 -*-
"""托盘程序入口：用 pythonw.exe 运行，不弹黑框。"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from sicau_net.app import main  # noqa: E402

if __name__ == "__main__":
    main()
