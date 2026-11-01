#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""首次配置的核心逻辑：找微信、派生密钥、校验、写配置、只读自检。

设计要点：
  * 只支持微信 4.x（xwechat_files/<账号>/db_storage 这套结构）；
  * 密钥来源二选一：
      1) 导入 master key，本模块按 PBKDF2 派生每个库的 enc_key；（推荐）
      2) 导入别人已经生成好的 all_keys.json（换机迁移用）。
  * 派生参数不写死：4.x 各版本迭代次数有差异，这里对候选参数逐个试，
    用 wcdb.verify_key() 的 HMAC 校验来确认——对不上就报错，绝不瞎写文件；
  * 全流程只读，不发任何消息。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths  # noqa: E402
import wcdb   # noqa: E402

# PBKDF2 候选参数（(哈希, 迭代次数)），微信 4.x 各版本实测不同
KDF_CANDIDATES = [
    ("sha512", 256000),
    ("sha512", 64000),
    ("sha512", 4096),
    ("sha256", 256000),
    ("sha256", 64000),
]

ACCOUNT_FILE_HINT = "db_storage"


# ---------------------------------------------------------------- 找微信
def _reg_paths() -> list[str]:
    out: list[str] = []
    try:
        import winreg
        for key in (r"Software\Tencent\Weixin", r"Software\Tencent\WeChat"):
            for name in ("FileSavePath", "SavePath"):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                        v, _ = winreg.QueryValueEx(k, name)
                        if v and isinstance(v, str):
                            out.append(v)
                except OSError:
                    continue
    except Exception:
        pass
    return out


def candidate_roots() -> list[str]:
    """可能存放微信数据的目录（去重、只留存在的）。"""
    cands: list[str] = []
    cands += _reg_paths()
    home = os.path.expanduser("~")
    for base in (os.path.join(home, "Documents"), home, "D:\\", "E:\\", "C:\\"):
        for name in ("xwechat_files", "WeChat Files", "微信", "weixin"):
            cands.append(os.path.join(base, name))
    # 盘符下常见的中文目录里再找一层
    for drive in ("D:\\", "E:\\", "C:\\"):
        for name in ("微信", "聊天储存", "WeChat", "Tencent"):
            cands.append(os.path.join(drive, name, "xwechat_files"))
            cands.append(os.path.join(drive, name))
    seen, out = set(), []
    for c in cands:
        c = os.path.normpath(c)
        if c.lower() in seen:
            continue
        seen.add(c.lower())
        if os.path.isdir(c):
            out.append(c)
    return out


def find_accounts(root: str) -> list[dict]:
    """在 root 下找账号目录（含 db_storage 的那层）。"""
    out: list[dict] = []
    if not root or not os.path.isdir(root):
        return out
    def probe(path: str) -> None:
        db = os.path.join(path, ACCOUNT_FILE_HINT)
        if os.path.isdir(db):
            out.append({"root": root, "account_dir": path,
                        "db_dir": db, "account": os.path.basename(path)})
    probe(root)
    try:
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if os.path.isdir(full):
                probe(full)
                try:
                    for sub in sorted(os.listdir(full)):
                        probe(os.path.join(full, sub))
                except OSError:
                    pass
    except OSError:
        pass
    return out


SKIP_DIRS = {
    "windows", "$recycle.bin", "system volume information", "program files",
    "program files (x86)", "programdata", "appdata", "node_modules",
    ".git", "__pycache__", "temp", "tmp", "recovery", "perflogs",
}
DATA_DIR_NAMES = ("xwechat_files", "wechat files", "weixin files")


def _walk_for_data(root: str, depth: int = 3, deadline: float = 0.0) -> list[dict]:
    """在 root 下有限深度地找微信数据目录，避免全盘遍历。"""
    import time as _t
    hits: list[dict] = []
    if depth <= 0 or (deadline and _t.time() > deadline):
        return hits
    if os.path.isdir(os.path.join(root, ACCOUNT_FILE_HINT)):
        return [{"root": root, "account_dir": root, "db_dir": os.path.join(root, ACCOUNT_FILE_HINT),
                 "account": os.path.basename(root) or root}]
    try:
        entries = list(os.scandir(root))
    except OSError:
        return hits
    for entry in entries:
        if deadline and _t.time() > deadline:
            break
        try:
            if not entry.is_dir():
                continue
        except OSError:
            continue
        name = entry.name.lower()
        if name in SKIP_DIRS or name.startswith("."):
            continue
        if name in DATA_DIR_NAMES:
            hits += find_accounts(entry.path)
        else:
            hits += _walk_for_data(entry.path, depth - 1, deadline)
    return hits


def autodetect_accounts() -> list[dict]:
    """把常见的几个起点各扫一遍（限深度、限时），去重。"""
    import time as _t
    out, seen = [], set()
    deadline = _t.time() + 10.0
    roots: list[str] = [os.path.expanduser("~")]
    roots += [os.path.join(os.path.expanduser("~"), "Documents")]
    for drive in "CDEFGH":
        if os.path.isdir(drive + ":\\"):
            roots.append(drive + ":\\")
    for root in roots:
        for acc in _walk_for_data(root, depth=3, deadline=deadline):
            if acc["db_dir"] in seen:
                continue
            seen.add(acc["db_dir"])
            out.append(acc)
        if _t.time() > deadline:
            break
    return out


# ---------------------------------------------------------------- 扫描数据库
def scan_databases(db_dir: str) -> list[dict]:
    """db_storage 下所有 .db（相对路径、大小、salt）。"""
    out: list[dict] = []
    if not os.path.isdir(db_dir):
        return out
    for folder, _dirs, files in os.walk(db_dir):
        for name in files:
            if not name.lower().endswith(".db"):
                continue
            full = os.path.join(folder, name)
            rel = os.path.relpath(full, db_dir)
            try:
                size = os.path.getsize(full)
                with open(full, "rb") as f:
                    salt = f.read(wcdb.SALT_SZ)
            except OSError:
                continue
            if len(salt) < wcdb.SALT_SZ:
                continue
            out.append({"rel": rel, "path": full, "size": size, "salt": salt})
    return sorted(out, key=lambda x: x["rel"].lower())


# ---------------------------------------------------------------- 派生密钥
def derive(master: bytes, salt: bytes, algo: str, iters: int) -> bytes:
    return hashlib.pbkdf2_hmac(algo, master, salt, iters, dklen=wcdb.KEY_SZ)


def derive_for_db(db: dict, master: bytes) -> bytes | None:
    """对单个库试各种参数，返回第一个能通过 HMAC 校验的密钥。"""
    for algo, iters in KDF_CANDIDATES:
        key = derive(master, db["salt"], algo, iters)
        try:
            if wcdb.verify_key(db["path"], key):
                return key
        except Exception:
            continue
    return None


def parse_master_key(text: str) -> bytes:
    """接受 64 位 hex（32 字节）。也容忍 '0x' 前缀和空白。"""
    s = (text or "").strip().replace(" ", "").replace("\n", "")
    if s.lower().startswith("0x"):
        s = s[2:]
    if len(s) != 64:
        raise ValueError("master key 应该是 64 位十六进制（32 字节），现在 %d 位" % len(s))
    try:
        return bytes.fromhex(s)
    except ValueError:
        raise ValueError("master key 里有非十六进制字符")


def build_keys(db_dir: str, master: bytes) -> dict:
    """派生整个 db_storage，返回可写进 all_keys.json 的结构。"""
    dbs = scan_databases(db_dir)
    if not dbs:
        return {"ok": False, "note": "这个目录下没找到 .db 文件：%s" % db_dir}
    keys: dict[str, dict] = {}
    failed: list[str] = []
    # 先用 contact/message 这类关键库确定参数，再套用到全部
    for db in dbs:
        key = derive_for_db(db, master)
        if not key:
            failed.append(db["rel"])
            continue
        keys[db["rel"]] = {
            "enc_key": key.hex(),
            "salt": db["salt"].hex(),
            "size_mb": round(db["size"] / 1048576.0, 1),
        }
    if not keys:
        return {"ok": False, "note": "所有库都校验失败：master key 可能不对，或者微信版本还不支持"}
    return {"ok": True, "keys": keys, "failed": failed, "db_dir": db_dir}


def write_all_keys(db_dir: str, keys: dict) -> str:
    data = {"_db_dir": db_dir}
    data.update(keys)
    paths.ensure_dirs()
    tmp = paths.ALL_KEYS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, paths.ALL_KEYS)
    return paths.ALL_KEYS


def import_all_keys(src: str) -> dict:
    """迁移用：直接吃一份已有的 all_keys.json，逐个库验一遍再落盘。"""
    try:
        with open(src, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return {"ok": False, "note": "读不了这个文件: %s" % exc}
    db_dir = str(data.get("_db_dir") or "")
    if not db_dir or not os.path.isdir(db_dir):
        return {"ok": False, "note": "文件里的 _db_dir 在本机不存在: %s" % (db_dir or "空")}
    good, bad = {}, []
    for rel, info in data.items():
        if rel == "_db_dir" or not isinstance(info, dict):
            continue
        try:
            key = bytes.fromhex(str(info.get("enc_key") or ""))
        except ValueError:
            bad.append(rel)
            continue
        full = os.path.join(db_dir, rel.replace("/", os.sep))
        if len(key) != wcdb.KEY_SZ or not os.path.isfile(full):
            bad.append(rel)
            continue
        if not wcdb.verify_key(full, key):
            bad.append(rel)
            continue
        good[rel] = info
    if not good:
        return {"ok": False, "note": "没有一把钥匙能打开这台机器上的库（多半是别的机器导出的）"}
    return {"ok": True, "keys": good, "failed": bad, "db_dir": db_dir}


# ---------------------------------------------------------------- 写配置
def write_env(data_dir: str, api_key: str) -> str:
    lines = [
        "DEEPSEEK_API_KEY=%s" % (api_key or ""),
        "",
        "# 微信 4.x 数据根目录（xwechat_files 那一层或账号目录都可以）",
        "WEIX_WECHAT_DATA_DIR=%s" % data_dir,
        "",
        "# 每个 .db 的密钥由 setup.py 生成到 config/all_keys.json，"
        "本文件不再重复保存",
    ]
    paths.ensure_dirs()
    with open(paths.ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return paths.ENV_FILE


def write_bot_config(names: dict, persona: str = "") -> str:
    """names: {wxid: 显示名}。从 config.example 复制一份再填白名单。

    persona 留空时保留模板里的填空版人设，等用户自己在面板里写。
    """
    template = os.path.join(paths.ROOT, "config.example", "bot.json")
    cfg = {}
    if os.path.isfile(template):
        with open(template, encoding="utf-8") as f:
            cfg = json.load(f)
    if os.path.isfile(paths.BOT_CONFIG):
        try:
            with open(paths.BOT_CONFIG, encoding="utf-8") as f:
                cfg = json.load(f)          # 已有配置就别覆盖用户改过的
        except Exception:
            pass
    cfg["whitelist"] = dict(sorted(names.items()))
    if (persona or "").strip():
        cfg["persona"] = persona.strip()
    paths.ensure_dirs()
    tmp = paths.BOT_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, paths.BOT_CONFIG)
    return paths.BOT_CONFIG


def ensure_profiles_file() -> str:
    paths.ensure_dirs()
    if not os.path.isfile(paths.PROFILES):
        with open(paths.PROFILES, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
    return paths.PROFILES


# ---------------------------------------------------------------- 只读自检
def self_check() -> dict:
    """验证：能解库、能读联系人、能读最近消息、能识别微信窗口。不发消息。"""
    out = {"ok": True, "steps": [], "warn": []}

    def step(name: str, ok: bool, note: str = "") -> None:
        out["steps"].append((name, ok, note))
        if not ok:
            out["ok"] = False

    try:
        db_dir, keys = wcdb.load_keys()
    except Exception as exc:
        step("读取密钥文件", False, str(exc))
        return out
    step("读取密钥文件", True, "%d 个库" % len(keys))

    cache = wcdb.PlainCache(cache_dir=os.path.join(paths.CACHE_DIR, "plain-setup"))
    contact = os.path.join(db_dir, "contact", "contact.db")
    plain = cache.get(contact, keys.get(os.path.join("contact", "contact.db"), b"")) \
        if os.path.isfile(contact) else None
    if not plain:
        step("解密联系人库", False, "联系人库打不开")
        return out
    try:
        import sqlite3
        con = sqlite3.connect("file:%s?mode=ro" % plain.replace("\\", "/"), uri=True)
        try:
            n = con.execute("select count(*) from contact").fetchone()[0]
        finally:
            con.close()
        step("解密联系人库", True, "%d 个联系人" % n)
    except Exception as exc:
        step("解密联系人库", False, str(exc))

    try:
        msgs = wcdb.collect_new_messages(db_dir, keys, cache, 0)
        step("读取消息库", True, "共 %d 条历史消息" % len(msgs))
    except Exception as exc:
        step("读取消息库", False, str(exc))

    try:
        import wxsend
        hwnd = wxsend.wechat_hwnd()
        step("找到微信窗口", bool(hwnd), "窗口句柄 %s" % hwnd if hwnd else "微信没开")
    except Exception as exc:
        step("找到微信窗口", False, str(exc))
    return out


def create_shortcut() -> str:
    """在桌面建一个「微信回复机器人」快捷方式。"""
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            v, _ = winreg.QueryValueEx(k, "Desktop")
            desk = os.path.expandvars(v)
    except Exception:
        pass
    target = os.path.join(paths.ROOT, "打开控制面板.bat")
    lnk = os.path.join(desk, "微信回复机器人.lnk")
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.Save()"
        % (lnk, target, paths.ROOT, os.path.join(paths.ASSETS_DIR, "weix.ico"))
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return lnk if os.path.isfile(lnk) else ""
