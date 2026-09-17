"""命令行入口：python -m sicau_net.cli status|login|logout|check

退出码：0 成功 / 1 失败 / 2 无需操作（已在线或已离线）。
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import config as config_module
from . import credentials, logging_setup, portal

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NOOP = 2


def _load_config():
    return config_module.load()


def cmd_status(args) -> int:
    cfg = _load_config()
    result = portal.probe(cfg)
    if result.online:
        print("已认证（在线）")
        return EXIT_OK
    print("未认证（离线）：%s" % result.detail)
    if args.verbose and result.params:
        print("认证参数：" + " ".join("%s=%s" % item for item in result.params.items()))
    return EXIT_NOOP


def cmd_login(args) -> int:
    cfg = _load_config()
    saved = credentials.load_credentials()
    if saved is None:
        print("还没有保存学号密码，请先运行托盘程序在设置里填写")
        return EXIT_FAIL

    if portal.probe(cfg).online:
        print("当前已在线，无需登录")
        return EXIT_NOOP

    result = portal.login(cfg, saved.username, saved.password)
    print(result.message)
    if not result.ok and result.detail:
        print("响应摘要：" + result.detail)
    return EXIT_OK if result.ok else EXIT_FAIL


def cmd_logout(args) -> int:
    cfg = _load_config()
    if not portal.probe(cfg).online:
        print("当前已离线，无需操作")
        return EXIT_NOOP
    result = portal.logout(cfg)
    print(result.message)
    if not result.ok and result.detail:
        print("响应摘要：" + result.detail)
    return EXIT_OK if result.ok else EXIT_FAIL


def cmd_check(args) -> int:
    cfg = _load_config()
    saved = credentials.load_credentials()
    if saved is None:
        print("还没有保存学号密码")
        return EXIT_FAIL
    result = portal.check_credentials(cfg, saved.username, saved.password)
    print("%s（%s）" % (result.message, saved.username))
    return EXIT_OK if result.ok else EXIT_FAIL


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sicau-net", description="川农校园网自动登录")
    parser.add_argument(
        "command",
        choices=["status", "login", "logout", "check"],
        help="status 查看状态 / login 立即登录 / logout 立即离线 / check 校验账号密码",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试信息")
    args = parser.parse_args(argv)

    # 老终端的代码页可能编不出中文，别让打印把程序搞崩
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    logging_setup.setup(verbose=args.verbose)
    handlers = {
        "status": cmd_status,
        "login": cmd_login,
        "logout": cmd_logout,
        "check": cmd_check,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

