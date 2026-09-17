"""生成 exe 用的多尺寸图标 packaging/app.ico（和托盘图标同一套画法）。"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sicau_net.tray import make_icon  # noqa: E402
from sicau_net.worker import State  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUTPUT = ROOT / "packaging" / "app.ico"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = make_icon(State.ONLINE, size=256)
    image.save(OUTPUT, format="ICO", sizes=[(size, size) for size in SIZES])
    print("已生成 %s（%d 字节）" % (OUTPUT, OUTPUT.stat().st_size))


if __name__ == "__main__":
    main()
