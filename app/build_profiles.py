#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""为每个联系人单独生成「关系 + 说话方式」画像。

数据来源就是本机聊天记录：把我和某人的历史文本交给模型，让它归纳出
关系、称呼、我的语气、句长习惯、禁区，存进 config/profiles.json。

用法：
    python app/build_profiles.py            # 刷新白名单里的所有人
    python app/build_profiles.py --all      # 刷新所有有聊天记录的人
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths    # noqa: E402
import wcdb     # noqa: E402

BASE = paths.ROOT
CONFIG = paths.BOT_CONFIG
PROFILES = paths.PROFILES
ENV = paths.ENV_FILE

PROMPT = """下面是我和联系人「{name}」的聊天记录，按时间顺序，「我:」是我说的话，「对方:」是他说的话。

请据此分析并只输出一个 JSON 对象（不要解释、不要代码块），字段：
（其中 eq 是情商档位 1-5：1 说话最直、几乎不照顾情绪，3 正常，5 最能接住情绪；
  temperature 建议值 0.5-1.0，话题越开放、越需要变化就给得越高）
{{
  "relation": "我们是什么关系（如女朋友/好朋友/同事/家人/客户/普通朋友）",
  "address_them": "我怎么称呼他（没有就写空串）",
  "address_me": "他怎么称呼我（没有就写空串）",
  "my_tone": "我对他说话的语气（简短描述，如随意打趣/客气正式/温柔关心）",
  "my_length": "我回复他的典型长度（如：几个字、一两句、会展开说）",
  "habits": ["我的说话习惯，最多4条，如常用语气词、爱反问、少用标点"],
  "taboos": ["对这个人的禁忌，最多3条，如不聊工作、不承诺时间"],
  "gender": "对方的性别，只能填 男 / 女 / 未知",
  "gender_reason": "判断性别的一句话依据（如称呼、话题、语气），没有依据就写空串",
  "eq": 3,
  "temperature": 0.7,
  "summary": "一句话概括我和他的相处方式"
}}

聊天记录：
{history}
"""


def read_env() -> dict:
    out = {}
    try:
        with open(ENV, encoding="utf-8") as f:
            for raw in f:
                s = raw.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, v = s.split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def ask(api_key: str, model: str, name: str, history: list[dict], wxid: str) -> dict | None:
    lines = []
    for m in history[-200:]:
        who = "我" if m.get("sender_wxid") != wxid else "对方"
        lines.append("%s: %s" % (who, m.get("content", "")[:120]))
    text = PROMPT.format(name=name, history="\n".join(lines))
    payload = {
        "model": model,
        "thinking": {"type": "disabled"},
        "temperature": 0.3,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": text}],
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode("utf-8"))
        raw = (data["choices"][0]["message"].get("content") or "").strip()
    except Exception as exc:
        print("  调用失败: %s" % exc)
        return None
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="刷新所有有聊天记录的联系人")
    ap.add_argument("--wxid", default="", help="只重新生成这一个人")
    ap.add_argument("--name", default="", help="按名字指定这一个人")
    args = ap.parse_args()

    cfg = json.load(open(CONFIG, encoding="utf-8"))
    env = read_env()
    api_key = env.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("缺少 DEEPSEEK_API_KEY")
        return 1

    wl = cfg.get("whitelist") or {}
    db_dir, keys = wcdb.load_keys()
    cache = wcdb.PlainCache()

    try:
        profiles = json.load(open(PROFILES, encoding="utf-8"))
    except Exception:
        profiles = {}

    targets = dict(wl)
    if args.all:
        # 白名单之外，已经有画像的人也一起刷新
        for wxid, prof in profiles.items():
            targets.setdefault(wxid, (prof or {}).get("name") or wxid)

    # 只处理指定的人
    if args.wxid or args.name:
        wxid = args.wxid.strip()
        if not wxid and args.name:
            hits = wcdb.resolve_contacts(db_dir, keys, cache, args.name.strip())
            if len(hits) != 1:
                print("按名字找不到唯一联系人: %s" % args.name)
                return 1
            wxid = hits[0]["wxid"]
        name = (profiles.get(wxid, {}) or {}).get("name") \
            or wcdb.contact_name(db_dir, keys, cache, wxid) or wxid
        targets = {wxid: name}

    for wxid, name in targets.items():
        hist = wcdb.chat_history(db_dir, keys, cache, wxid, limit=200)
        if len(hist) < 4:
            print("%s 记录太少（%d 条），跳过" % (name, len(hist)))
            continue
        print("分析 %s（%d 条历史）..." % (name, len(hist)))
        prof = ask(api_key, cfg.get("model", "deepseek-v4-pro"), name, hist, wxid)
        if not prof:
            print("  解析失败，保留原画像")
            continue
        prof["name"] = name
        prof.setdefault("gender", "未知")
        try:
            prof["eq"] = max(1, min(5, int(prof.get("eq", 3))))
        except (TypeError, ValueError):
            prof["eq"] = 3
        try:
            prof["temperature"] = round(float(prof.get("temperature", 0.7)), 2)
        except (TypeError, ValueError):
            prof["temperature"] = 0.7
        prof["updated_at"] = int(time.time())
        prof["sample_size"] = len(hist)
        # 合并而不是整条替换：关系历史、待确认、分析进度这些账本字段要留着
        old = profiles.get(wxid) or {}
        merged = {**old, **prof}
        new_rel = str(prof.get("relation") or "")
        old_rel = str(old.get("relation") or "")
        if new_rel and old_rel and new_rel != old_rel:
            hist_rel = list(old.get("relation_history") or [])
            hist_rel.append({"at": int(time.time()), "from": old_rel,
                             "to": new_rel, "by": "user", "why": "重新生成画像"})
            merged["relation_history"] = hist_rel[-20:]
            merged["relation_since"] = int(time.time())
        merged.pop("pending_relation", None)
        merged.pop("relation_confidence", None)
        profiles[wxid] = merged
        print("  关系: %s | 性别: %s | 情商: %s | 温度: %s" % (
            prof.get("relation"), prof.get("gender"), prof.get("eq"), prof.get("temperature")))
        print("  语气: %s | 长度: %s" % (prof.get("my_tone"), prof.get("my_length")))

    tmp = PROFILES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROFILES)
    print("已写入 %s" % PROFILES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
