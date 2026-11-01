#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""首次配置向导（命令行版，也可以是全自动脚本）。

交互模式：
    双击「首次配置.bat」，或者 python app/setup.py

全自动（无人值守，适合批量铺开 / 打包成 exe 前的脚本调用）：
    python app/setup.py --data-dir "D:\\微信\\聊天储存\\xwechat_files" \
        --master-key 32字节hex --api-key sk-xxx \
        --contacts "张三,李四" --yes

换机迁移（另一台机器已经生成过 all_keys.json）：
    python app/setup.py --import-keys old_all_keys.json --api-key sk-xxx --yes

只检查不写配置：
    python app/setup.py --check-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths          # noqa: E402
import setup_core as sc   # noqa: E402

BANNER = """\
============================================
 微信回复机器人 · 首次配置
============================================"""


def ask(prompt: str, default: str = "") -> str:
    s = input(prompt + ("（直接回车 = %s）" % default if default else "") + ": ").strip()
    return s or default


def choose_account() -> dict | None:
    found = sc.autodetect_accounts()
    if not found:
        print("\n没自动找到微信数据。请手动输入 xwechat_files 的路径（或账号目录）。")
        print("常见位置：文档\\xwechat_files、D:\\微信\\聊天储存\\xwechat_files")
        manual = ask("路径")
        if not manual:
            return None
        accs = sc.find_accounts(manual)
        if not accs:
            print("这个目录下没找到 db_storage，确认一下路径。")
            return None
        found = accs
    print("\n找到 %d 个微信账号目录：" % len(found))
    for i, a in enumerate(found, 1):
        print("  %d) %s  (%s)" % (i, a["account"], a["db_dir"]))
    if len(found) == 1:
        print("只有一个，直接用。")
        return found[0]
    raw = ask("\n选哪个（序号）", "1")
    try:
        return found[int(raw) - 1]
    except (ValueError, IndexError):
        print("序号不对")
        return None


def do_keys(acc: dict, master_hex: str) -> dict:
    try:
        master = sc.parse_master_key(master_hex) if master_hex else None
    except ValueError as exc:
        print("  ✗ %s" % exc)
        return {"ok": False}
    if not master:
        return {"ok": False}
    print("正在派生并校验各库密钥（第一次会慢一点，要算 PBKDF2）…")
    res = sc.build_keys(acc["db_dir"], master)
    if not res.get("ok"):
        print("  ✗ %s" % res.get("note"))
        return res
    path = sc.write_all_keys(acc["db_dir"], res["keys"])
    print("  ✓ 成功派生 %d 个库的密钥" % len(res["keys"]))
    if res.get("failed"):
        print("  ! 有 %d 个库没通过校验，已跳过：%s"
              % (len(res["failed"]), ", ".join(res["failed"][:5])))
    print("  ✓ 已写入 %s" % path)
    return res


def resolve_contacts(names: list[str]) -> dict:
    """名字 → wxid。找不到或有歧义会提示。"""
    import wcdb
    db_dir, keys = wcdb.load_keys()
    cache = wcdb.PlainCache(cache_dir=os.path.join(paths.CACHE_DIR, "plain-setup"))
    out: dict[str, str] = {}
    for name in [n.strip() for n in names if n.strip()]:
        if name.startswith("wxid_") or name.endswith("@chatroom"):
            out[name] = name
            continue
        hits = wcdb.resolve_contacts(db_dir, keys, cache, name)
        if len(hits) == 1:
            out[hits[0]["wxid"]] = name
            print("  ✓ %s → %s" % (name, hits[0]["wxid"]))
        elif not hits:
            print("  ✗ 没找到「%s」，可以先不管，之后在面板里加" % name)
        else:
            print("  ! 「%s」对应多个联系人，跳过：%s"
                  % (name, ", ".join(h["wxid"] for h in hits[:5])))
    return out


def print_check(res: dict) -> None:
    print("\n---- 只读自检 ----")
    for name, ok, note in res.get("steps", []):
        print("  %s %s%s" % ("✓" if ok else "✗", name, ("：" + note) if note else ""))
    if res.get("ok"):
        print("\n自检通过。接下来双击「启动机器人.bat」即可（默认只生成不发送，"
              "确认没问题后再在面板里打开发送）。")
    else:
        print("\n自检有问题，先按上面的 ✗ 修，再启动。")


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--data-dir", default="", help="微信数据目录（含 db_storage 的账号目录或其上一层）")
    ap.add_argument("--master-key", default="", help="32 字节 master key（64 位 hex）")
    ap.add_argument("--api-key", default="", help="DeepSeek API key")
    ap.add_argument("--contacts", default="", help="白名单，逗号分隔（名字或 wxid）")
    ap.add_argument("--persona", default="", help="直接给一段人设文本")
    ap.add_argument("--persona-file", default="", help="从文本文件读人设（UTF-8）")
    ap.add_argument("--import-keys", default="", help="导入已有的 all_keys.json（换机迁移）")
    ap.add_argument("--check-only", action="store_true", help="只跑自检")
    ap.add_argument("--shortcut", action="store_true", help="在桌面建快捷方式")
    ap.add_argument("--yes", action="store_true", help="不交互，缺参数就报错")
    args = ap.parse_args()

    print(BANNER)

    if args.check_only:
        print_check(sc.self_check())
        return 0

    # 1) 密钥
    if args.import_keys:
        print("\n[1/4] 导入已有密钥")
        res = sc.import_all_keys(args.import_keys)
        if not res.get("ok"):
            print("  ✗ %s" % res.get("note"))
            return 1
        sc.write_all_keys(res["db_dir"], res["keys"])
        db_dir = res["db_dir"]
        print("  ✓ 校验通过 %d 个库" % len(res["keys"]))
    else:
        print("\n[1/4] 选择微信数据目录")
        acc = None
        if args.data_dir:
            accs = sc.find_accounts(args.data_dir)
            if not accs:
                print("  ✗ 这个目录里没找到 db_storage：%s" % args.data_dir)
                return 1
            acc = accs[0]
            print("  ✓ %s" % acc["db_dir"])
        else:
            if args.yes:
                print("  ✗ --yes 模式下必须给 --data-dir")
                return 1
            acc = choose_account()
        if not acc:
            return 1

        print("\n[2/4] 输入 master key")
        master_hex = args.master_key
        while not master_hex:
            if args.yes:
                print("  ✗ --yes 模式下必须给 --master-key")
                return 1
            print("  取法见 docs/取密钥说明.md（第三方工具读内存拿到 32 字节 key 的 hex）")
            master_hex = ask("master key")
            if not master_hex:
                return 1
        res = do_keys(acc, master_hex)
        if not res.get("ok"):
            return 1
        db_dir = acc["db_dir"]

    # 2) API key
    print("\n[3/4] DeepSeek API key")
    api_key = args.api_key
    if not api_key:
        if args.yes:
            print("  ! 没给 --api-key，先留空，之后在面板里填")
        else:
            api_key = ask("sk-…（回车先跳过）")
    sc.write_env(db_dir, api_key)
    print("  ✓ 已写入 %s%s" % (paths.ENV_FILE, "" if api_key else "（API key 为空，记得补）"))

    # 3) 白名单
    print("\n[4/4] 白名单（只对这几个人自动回复）")
    names = [n for n in args.contacts.replace("、", ",").split(",") if n.strip()]
    if not names:
        if not args.yes:
            raw = ask("输入要自动回复的人，逗号分隔（可先留空，之后在面板加）")
            names = [n for n in raw.replace("、", ",").split(",") if n.strip()]
        else:
            print("  ! 没给 --contacts，白名单先留空")
    wl = resolve_contacts(names) if names else {}
    persona = ""
    if args.persona_file:
        try:
            with open(args.persona_file, encoding="utf-8") as f:
                persona = f.read()
            print("  ✓ 人设从 %s 读入（%d 字）" % (args.persona_file, len(persona)))
        except OSError as exc:
            print("  ! 人设文件读不了：%s" % exc)
    elif args.persona:
        persona = args.persona
        print("  ✓ 人设用命令行给的（%d 字）" % len(persona))
    sc.write_bot_config(wl, persona)
    sc.ensure_profiles_file()
    print("  ✓ 白名单 %d 人，已写入 %s" % (len(wl), paths.BOT_CONFIG))

    # 5) 人设提醒
    if not persona.strip():
        print("\n[人设] 还没写。打开控制面板 →「参数 → 全局人设」，"
              "照着你自己的说话方式把模板里括号中的例子替换掉。\n"
              "        （人设不写也能跑，但回复会很空、很像客服）")

    # 6) 自检
    print_check(sc.self_check())

    if args.shortcut:
        lnk = sc.create_shortcut()
        print(("已创建快捷方式：%s" % lnk) if lnk else "快捷方式没建成（可能被拦了）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
