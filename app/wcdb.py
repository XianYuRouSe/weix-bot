#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""WeChat 4.x 数据库读取（独立于任何第三方程序）。

要点：
  * SQLCipher4 参数：AES-256-CBC、page 4096、reserve 80、HMAC-SHA512
  * 只解密"文件发生变化"的库，按 (mtime, size) 缓存明文件，避免反复解密
  * 读消息时只取 create_time 之后的新行，支持增量轮询

密钥来自 .env 的 WEIX_WECHAT_DB_KEY / WEIX_WECHAT_CONTACT_DB_KEY。
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac as hmac_mod
import os
import sqlite3
import struct
import tempfile
import time
from ctypes import wintypes as wt

PAGE_SZ = 4096
SALT_SZ = 16
IV_SZ = 16
HMAC_SZ = 64
KEY_SZ = 32
RESERVE_SZ = 80
SQLITE_HDR = b"SQLite format 3\x00"

_bcrypt = ctypes.WinDLL("bcrypt.dll", use_last_error=True)


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-256-CBC 解密（无 padding），走系统 bcrypt。"""
    h_alg = wt.HANDLE()
    st = _bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(h_alg), "AES", None, 0)
    if st != 0:
        raise RuntimeError("BCryptOpenAlgorithmProvider failed: %#x" % st)
    try:
        mode = "ChainingModeCBC\x00".encode("utf-16-le")
        st = _bcrypt.BCryptSetProperty(h_alg, "ChainingMode", mode, len(mode), 0)
        if st != 0:
            raise RuntimeError("BCryptSetProperty failed: %#x" % st)
        h_key = wt.HANDLE()
        st = _bcrypt.BCryptGenerateSymmetricKey(h_alg, ctypes.byref(h_key), None, 0, key, len(key), 0)
        if st != 0:
            raise RuntimeError("BCryptGenerateSymmetricKey failed: %#x" % st)
        try:
            iv_buf = ctypes.create_string_buffer(iv, len(iv))
            out_buf = ctypes.create_string_buffer(len(data))
            out_len = ctypes.c_ulong(0)
            st = _bcrypt.BCryptDecrypt(h_key, data, len(data), None, iv_buf, len(iv),
                                       out_buf, len(out_buf), ctypes.byref(out_len), 0)
            if st != 0:
                raise RuntimeError("BCryptDecrypt failed: %#x" % st)
            return out_buf.raw[: out_len.value]
        finally:
            _bcrypt.BCryptDestroyKey(h_key)
    finally:
        _bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)


def _decrypt_page(enc_key: bytes, page: bytes, pgno: int) -> bytes:
    iv = page[PAGE_SZ - RESERVE_SZ: PAGE_SZ - RESERVE_SZ + IV_SZ]
    if pgno == 1:
        enc = page[SALT_SZ: PAGE_SZ - RESERVE_SZ]
        return SQLITE_HDR + aes_cbc_decrypt(enc_key, iv, enc) + b"\x00" * RESERVE_SZ
    enc = page[: PAGE_SZ - RESERVE_SZ]
    return aes_cbc_decrypt(enc_key, iv, enc) + b"\x00" * RESERVE_SZ


def verify_key(db_path: str, enc_key: bytes) -> bool:
    """用 page1 的 HMAC 校验 32 字节 key 是否正确。"""
    if not os.path.isfile(db_path) or os.path.getsize(db_path) < PAGE_SZ:
        return False
    with open(db_path, "rb") as f:
        page1 = f.read(PAGE_SZ)
    salt = page1[:SALT_SZ]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
    data = page1[SALT_SZ: PAGE_SZ - RESERVE_SZ + IV_SZ]
    mac = hmac_mod.new(mac_key, data, hashlib.sha512)
    mac.update(struct.pack("<I", 1))
    return mac.digest() == page1[PAGE_SZ - HMAC_SZ: PAGE_SZ]


def decrypt_database(db_path: str, out_path: str, enc_key: bytes) -> bool:
    if not verify_key(db_path, enc_key):
        return False
    size = os.path.getsize(db_path)
    pages = size // PAGE_SZ + (1 if size % PAGE_SZ else 0)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(db_path, "rb") as fin, open(out_path, "wb") as fout:
        for pgno in range(1, pages + 1):
            page = fin.read(PAGE_SZ)
            if len(page) < PAGE_SZ:
                if not page:
                    break
                page += b"\x00" * (PAGE_SZ - len(page))
            fout.write(_decrypt_page(enc_key, page, pgno))
    return True


class PlainCache:
    """把解密后的库缓存到临时目录，文件没变就复用。"""

    def __init__(self, cache_dir: str | None = None):
        # 解密结果落在安装目录的 cache 下，不写系统临时目录
        self.dir = cache_dir or paths.PLAIN_CACHE
        os.makedirs(self.dir, exist_ok=True)
        self._index: dict[str, tuple[float, int, str]] = {}

    def get(self, db_path: str, enc_key: bytes) -> str | None:
        try:
            st = os.stat(db_path)
        except OSError:
            return None
        sig = (st.st_mtime, st.st_size)
        hit = self._index.get(db_path)
        if hit and (hit[0], hit[1]) == sig and os.path.isfile(hit[2]):
            return hit[2]
        name = hashlib.md5(db_path.encode("utf-8")).hexdigest() + ".db"
        out = os.path.join(self.dir, name)
        if not decrypt_database(db_path, out, enc_key):
            return None
        # 解密期间文件可能又被写了；若变了就不缓存签名，下次重新解密，
        # 避免"缓存住了一个旧签名 + 半新内容"而永远看不到新消息。
        try:
            st2 = os.stat(db_path)
            if (st2.st_mtime, st2.st_size) != sig:
                return out
        except OSError:
            return out
        self._index[db_path] = (sig[0], sig[1], out)
        return out

    def prune(self, keep_files: int = 40) -> int:
        files = sorted(
            (os.path.join(self.dir, f) for f in os.listdir(self.dir)),
            key=lambda p: os.path.getmtime(p) if os.path.isfile(p) else 0,
        )
        removed = 0
        for p in files[:-keep_files] if len(files) > keep_files else []:
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
        return removed


def msg_tables(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' and name like 'Msg\\_%' escape '\\'")]


def resolve_sender(con: sqlite3.Connection, sender_id: int) -> str:
    """real_sender_id → wxid。4.x 用 Name2Id 表（列名随版本略有差异）。"""
    for sql in ("select user_name from Name2Id where rowid=?",
                "select username from Name2Id where rowid=?",
                "select user_name from Name2Id where id=?"):
        try:
            row = con.execute(sql, (sender_id,)).fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            continue
    return ""


def read_new_messages(plain_db: str, since_ts: int, limit: int = 200) -> list[dict]:
    """读某分片库里 create_time > since_ts 的文本消息。"""
    out: list[dict] = []
    con = sqlite3.connect("file:%s?mode=ro" % plain_db.replace("\\", "/"), uri=True)
    try:
        for table in msg_tables(con):
            try:
                rows = con.execute(
                    'select local_id, create_time, real_sender_id, local_type, '
                    'message_content, compress_content from "%s" '
                    'where create_time > ? order by create_time asc limit ?' % table,
                    (since_ts, limit),
                ).fetchall()
            except sqlite3.Error:
                continue
            for local_id, ctime, sender_id, ltype, content, comp in rows:
                text = ""
                if content is not None:
                    text = str(content)
                if comp:
                    try:
                        import zlib
                        text = zlib.decompress(comp).decode("utf-8", "replace")
                    except Exception:
                        pass
                out.append({
                    "table": table,
                    "local_id": local_id,
                    "create_time": int(ctime or 0),
                    "sender_id": int(sender_id or 0),
                    "local_type": int(ltype or 0),
                    "content": text,
                })
    finally:
        con.close()
    return out

# ---------------------------------------------------------------- 上位接口
import json

import paths

CONFIG_KEYS = paths.ALL_KEYS


def load_keys() -> tuple[str, dict[str, bytes]]:
    """返回 (db_storage 路径, {相对路径: 32字节密钥})。"""
    data = json.load(open(CONFIG_KEYS, encoding="utf-8"))
    db_dir = str(data.get("_db_dir", "")).replace("/", os.sep)
    keys: dict[str, bytes] = {}
    for rel, info in data.items():
        if rel == "_db_dir" or not isinstance(info, dict):
            continue
        ek = str(info.get("enc_key", ""))
        if len(ek) == 64:
            keys[rel.replace("/", os.sep)] = bytes.fromhex(ek)
    return db_dir, keys


def message_db_files(db_dir: str, keys: dict[str, bytes]) -> list[tuple[str, bytes]]:
    """所有 message/*.db 及其密钥。"""
    out = []
    for rel, key in keys.items():
        if not rel.lower().startswith("message" + os.sep):
            continue
        if not rel.lower().endswith(".db"):
            continue
        path = os.path.join(db_dir, rel)
        if os.path.isfile(path):
            out.append((path, key))
    return sorted(out)


def detect_self_wxid(db_dir: str, keys: dict[str, bytes], cache: "PlainCache") -> str:
    """推断本机账号自己的 wxid。

    WeChat 4.x 的账号目录名是 "<wxid>_<4位十六进制>"（例如
    wxid_abc123_56ba），并不等于 wxid 本身。直接拿目录名当 wxid，会让
    "我发出的消息"永远匹配不上：回读确认失败、自己的消息被当成对方发来的
    内容再回一遍、上下文里的角色颠倒。

    这里以消息库里真实出现过的 wxid 为准校验：目录名、去掉后缀的目录名，
    哪个能在 Name2Id 里找到就用哪个；都找不到返回空串，由调用方决定退回。
    """
    import re
    base = os.path.basename(os.path.dirname(os.path.abspath(db_dir.rstrip("\\/"))))
    if not base:
        return ""
    candidates = [base]
    m = re.match(r"^(.*)_[0-9a-fA-F]{4}$", base)
    if m and m.group(1):
        candidates.append(m.group(1))
    names: set[str] = set()
    for path, key in message_db_files(db_dir, keys):
        plain = cache.get(path, key)
        if not plain:
            continue
        names.update(v for v in build_name_map(plain).values() if v)
    for cand in candidates:
        if cand in names:
            return cand
    return ""


def build_name_map(plain_db: str) -> dict[int, str]:
    con = sqlite3.connect("file:%s?mode=ro" % plain_db.replace("\\", "/"), uri=True)
    try:
        return {int(r[0]): str(r[1]) for r in con.execute("select rowid, user_name from Name2Id")}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def collect_new_messages(db_dir: str, keys: dict[str, bytes], cache: "PlainCache",
                         since_ts: int) -> list[dict]:
    """跨所有消息分片收集新消息，并标注会话。

    注意：每个分片的 Name2Id 是**独立编号**的，不能按 rowid 合并——那样会
    互相覆盖。正确做法是每个分片用自己的名字表解析发送者，会话名则用全部
    名字的并集做 md5 反查。
    """
    import hashlib

    raw: list[dict] = []
    all_names: set[str] = set()
    for path, key in message_db_files(db_dir, keys):
        plain = cache.get(path, key)
        if not plain:
            continue
        local_map = build_name_map(plain)
        all_names.update(v for v in local_map.values() if v)
        for m in read_new_messages(plain, since_ts):
            m["sender_wxid"] = local_map.get(m["sender_id"], "")
            raw.append(m)

    rev = {hashlib.md5(u.encode("utf-8")).hexdigest(): u for u in all_names}
    for m in raw:
        m["chat_wxid"] = rev.get(m["table"][4:], "")
    raw.sort(key=lambda x: x["create_time"])
    return raw

def chat_history(db_dir: str, keys: dict, cache: "PlainCache", chat_wxid: str,
                 limit: int = 60) -> list[dict]:
    """读某个会话最近的历史消息（只取文本），用于推断说话方式和给上下文。"""
    import hashlib
    if not chat_wxid:
        return []
    table = "Msg_" + hashlib.md5(chat_wxid.encode("utf-8")).hexdigest()
    for path, key in message_db_files(db_dir, keys):
        plain = cache.get(path, key)
        if not plain:
            continue
        con = sqlite3.connect("file:%s?mode=ro" % plain.replace("\\", "/"), uri=True)
        try:
            exists = con.execute(
                "select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone()
            if not exists:
                continue
            name_map = build_name_map(plain)
            rows = con.execute(
                'select create_time, real_sender_id, local_type, message_content '
                'from "%s" where local_type=1 order by create_time desc limit ?' % table,
                (limit,)).fetchall()
        except sqlite3.Error:
            continue
        finally:
            con.close()
        out = []
        for ctime, sender_id, ltype, content in reversed(rows):
            text = str(content or "").strip()
            if not text:
                continue
            out.append({
                "create_time": int(ctime or 0),
                "sender_wxid": name_map.get(int(sender_id or 0), ""),
                "content": text,
            })
        return out
    return []

def resolve_contacts(db_dir: str, keys: dict, cache: "PlainCache", name: str) -> list[dict]:
    """按名字（备注/昵称/微信号）在联系人库里查 wxid。

    返回 [{wxid, name, field}]；多个结果表示重名，调用方应拒绝使用。
    """
    if not name:
        return []
    plain = cache.get(os.path.join(db_dir, "contact", "contact.db"),
                      keys.get(os.path.join("contact", "contact.db"), b""))
    if not plain:
        return []
    con = sqlite3.connect("file:%s?mode=ro" % plain.replace("\\", "/"), uri=True)
    try:
        rows = con.execute(
            "select username, remark, nick_name, alias from contact "
            "where remark=? or nick_name=? or alias=?", (name, name, name)
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    out = []
    for username, remark, nick, alias in rows:
        if not username:
            continue
        field = "备注" if remark == name else ("昵称" if nick == name else "微信号")
        out.append({"wxid": str(username),
                    "name": str(remark or nick or alias or username),
                    "field": field})
    return out

def search_contacts(db_dir: str, keys: dict, cache: "PlainCache", term: str,
                    limit: int = 30) -> list[dict]:
    """按片段模糊搜索联系人（备注/昵称/微信号/拼音不了，只做子串匹配）。"""
    term = (term or "").strip()
    if not term:
        return []
    plain = cache.get(os.path.join(db_dir, "contact", "contact.db"),
                      keys.get(os.path.join("contact", "contact.db"), b""))
    if not plain:
        return []
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = "%" + esc + "%"
    con = sqlite3.connect("file:%s?mode=ro" % plain.replace("\\", "/"), uri=True)
    try:
        rows = con.execute(
            "select username, remark, nick_name, alias from contact "
            "where (remark like ? escape '\\' or nick_name like ? escape '\\' "
            "       or alias like ? escape '\\' or username like ? escape '\\') "
            "and username is not null and username <> '' "
            "order by case when remark like ? escape '\\' then 0 "
            "              when nick_name like ? escape '\\' then 1 else 2 end, "
            "length(remark) limit ?",
            (like, like, like, like, like, like, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    out = []
    for username, remark, nick, alias in rows:
        out.append({
            "wxid": str(username),
            "remark": str(remark or ""),
            "nick": str(nick or ""),
            "alias": str(alias or ""),
            "display": str(remark or nick or alias or username),
        })
    return out

def contact_name(db_dir: str, keys: dict, cache: "PlainCache", wxid: str) -> str:
    """由 wxid 反查显示名（备注优先）。"""
    if not wxid:
        return ""
    plain = cache.get(os.path.join(db_dir, "contact", "contact.db"),
                      keys.get(os.path.join("contact", "contact.db"), b""))
    if not plain:
        return ""
    con = sqlite3.connect("file:%s?mode=ro" % plain.replace("\\", "/"), uri=True)
    try:
        row = con.execute(
            "select remark, nick_name, alias from contact where username=?", (wxid,)
        ).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        con.close()
    if not row:
        return ""
    return str(row[0] or row[1] or row[2] or "")
