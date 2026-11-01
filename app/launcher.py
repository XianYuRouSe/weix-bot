#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""打包成 exe 之后的统一入口。

    weix.exe            打开控制面板（默认）
    weix.exe panel      打开控制面板
    weix.exe bot        启动机器人（命令行窗口）
    weix.exe setup      首次配置向导
    weix.exe selftest   只读自检
    weix.exe version    显示版本
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 控制台统一用 UTF-8，避免中文在 cmd 里变乱码（配合 .bat 里的 chcp 65001）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

USAGE = __doc__


def _version() -> str:
    import paths
    p = os.path.join(paths.ROOT, "VERSION")
    try:
        with open(p, encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return "dev"


def main() -> int:
    argv = sys.argv[1:]
    cmd = (argv[0] if argv else "panel").lower()
    # 把子命令从 argv 里摘掉，后面的模块自己解析参数
    sys.argv = [sys.argv[0]] + argv[1:]

    if cmd in ("-v", "--version", "version"):
        print("weix-bot %s" % _version())
        return 0
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd == "bot":
        import bot
        return bot.main()
    if cmd == "setup":
        import setup
        return setup.main()
    if cmd == "selftest":
        import setup_core
        res = setup_core.self_check()
        print("---- 只读自检 ----")
        for name, ok, note in res.get("steps", []):
            print("  %s %s%s" % ("✓" if ok else "✗", name, ("：" + note) if note else ""))
        return 0 if res.get("ok") else 1
    if cmd == "panel":
        import panel
        return panel.main()
    print("不认识的命令：%s\n" % cmd)
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
