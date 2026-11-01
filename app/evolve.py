#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""关系会变：每天分析一次新增聊天，关系变更先提示、超时未确认再自动应用。

三条原则：
  1. 只看"上次分析之后"的新消息，不重复吃旧结论；
  2. 机器人代发的句子从证据里剔除（否则它自己的冷淡会被当成关系变淡）；
  3. 关系标签不直接改：先写进 pending_relation 等人确认，超过
     pending_hours 还没处理才自动应用，每次变更都进 relation_history。

用法：
    python app/evolve.py            # 把所有到期的人分析一遍
    python app/evolve.py --wxid X   # 只分析一个人（忽略"每天一次"的限制）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import paths   # noqa: E402
import wcdb  # noqa: E402

CONFIG = paths.BOT_CONFIG
PROFILES = paths.PROFILES
ENV = paths.ENV_FILE
LOG = paths.EVOLVE_LOG
CACHE_DIR = os.path.join(paths.CACHE_DIR, "plain-evolve")

# 与面板 RELATION_TIERS 的键保持一致（那边决定话术档位）
RELATIONS = [
    "女朋友", "男朋友", "妻子", "丈夫", "暧昧对象",
    "父母", "兄弟姐妹", "子女", "亲戚", "长辈",
    "发小", "好朋友", "同学", "室友", "普通朋友", "网友",
    "领导", "同事", "下属", "客户", "合作伙伴", "服务人员", "陌生人",
]

DEFAULTS = {
    "enabled": True,
    "daily_seconds": 24 * 3600,     # 每人每天最多分析一次
    "pending_hours": 48,            # 提示后多久没确认就自动应用
    "cooldown_days": 14,            # 被忽略的关系多久内不再提
    "min_new_messages": 15,         # 新增消息太少就先不分析
    "confidence_min": 0.6,          # 低于这个置信度不生成待确认项
    "window_days": 30,              # 单次最多回看多少天
    "history_keep": 20,
}

PROMPT = """你是关系分析器。下面是我和「{name}」最近一段聊天记录（机器人生成的回复已剔除）。

请判断：我们现在的关系更接近哪一类，以及我说话的整体风格有没有变化。

关系只能从这个列表里选一个：
{relations}

要求：
1. 判断关系只看对方说的话、称呼、互动方式和话题深浅，不要用「我」的回复去反推对方态度；
2. evidence 填对方的原话，2-3 条，照抄不改写；如果对方几乎没说话，就给空数组并把置信度写低；
3. relation_confidence 是 0-1 的小数，表示你对新关系的把握；
4. 关系没变也要给出置信度，方便判断稳定不稳定；
5. 只输出一个 JSON 对象，不要解释、不要代码块。

当前画像：关系={current}；语气={tone}；上次总结={summary}

聊天记录：
{transcript}

输出格式：
{{
  "relation": "从上面的列表里选一个",
  "relation_confidence": 0.0,
  "relation_reason": "一句话说明为什么是这个关系",
  "evidence": ["对方的原话1", "对方的原话2"],
  "summary": "一句话概括我和他的相处方式",
  "my_tone": "我对他说话的语气，几个词，用顿号隔开",
  "my_length": "我回复他的典型长度",
  "habits": ["我的说话习惯，最多4条"],
  "taboos": ["对这个人的禁忌，最多3条"],
  "change_note": "跟上次比有什么变化，没变化就写空串"
}}
"""

_SENT_RE = re.compile(
    r"\| (?:发送 chat=\S+ name=.+? 唯一性=\S+ reply="
    r"|已发送但回读未确认 name=.+? reply=)(.+)$")

_state: dict = {"sent_sig": None, "sent": set(), "self": None, "cache": None}
_LAST_SKIP: dict = {}


# ---------------------------------------------------------------- 基础设施
def log(msg: str) -> None:
    line = "%s | %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


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


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def options() -> dict:
    opts = dict(DEFAULTS)
    cfg = read_json(CONFIG, {}) or {}
    user = cfg.get("evolution") or {}
    if isinstance(user, dict):
        for k in DEFAULTS:
            if k in user:
                opts[k] = user[k]
    return opts


def _cache() -> wcdb.PlainCache:
    if _state["cache"] is None:
        _state["cache"] = wcdb.PlainCache(cache_dir=CACHE_DIR)
    return _state["cache"]


def self_wxid() -> str:
    if _state["self"] is None:
        db_dir, keys = wcdb.load_keys()
        try:
            _state["self"] = wcdb.detect_self_wxid(db_dir, keys, _cache())
        except Exception:
            _state["self"] = ""
    return _state["self"] or ""


def bot_sent_texts() -> set:
    """机器人代发过的句子（解析日志），用来把它们从"本人的话"里剔掉。"""
    folder = os.path.join(BASE, "logs")
    try:
        names = sorted(n for n in os.listdir(folder)
                       if n.startswith("bot") and
                       (n.endswith(".log") or re.search(r"\.log\.\d+$", n)))
    except OSError:
        return set()
    sig = []
    for n in names:
        try:
            st = os.stat(os.path.join(folder, n))
        except OSError:
            continue
        sig.append((n, st.st_mtime, st.st_size))
    sig = tuple(sig)
    if _state["sent_sig"] == sig:
        return _state["sent"]
    texts: set = set()
    for n, _, _ in sig:
        try:
            with open(os.path.join(folder, n), encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = _SENT_RE.search(line.rstrip("\n"))
                    if m:
                        t = m.group(1)
                        if t.endswith("（请人工核对）"):
                            t = t[: -len("（请人工核对）")]
                        texts.add("".join(t.split()))
        except OSError:
            continue
    _state["sent_sig"] = sig
    _state["sent"] = texts
    return texts


def transcript(chat_wxid: str, since_ts: int, window_days: int = 30) -> list[str]:
    """上次分析之后、剔除机器人句子的一段对话。"""
    db_dir, keys = wcdb.load_keys()
    me = self_wxid()
    sent = bot_sent_texts()
    floor = int(time.time()) - int(window_days) * 86400
    lines: list[str] = []
    for m in wcdb.chat_history(db_dir, keys, _cache(), chat_wxid, limit=400):
        ts = int(m.get("create_time") or 0)
        if ts <= since_ts or ts < floor:
            continue
        text = (m.get("content") or "").strip()
        if not text:
            continue
        who = "我" if m.get("sender_wxid") == me else "对方"
        if who == "我":
            flat = "".join(text.split())
            if any(b and (b in flat or flat in b) for b in sent):
                continue          # 机器人代发的，不算"我"说的话
        lines.append("%s: %s" % (who, text[:120]))
    return lines[-200:]


# ---------------------------------------------------------------- 关系读写
def set_relation(prof: dict, new: str, by: str, why: str = "",
                 confidence: float | None = None) -> bool:
    old = str(prof.get("relation") or "")
    if not new or new == old:
        if confidence is not None:
            prof["relation_confidence"] = round(float(confidence), 2)
        return False
    hist = list(prof.get("relation_history") or [])
    hist.append({"at": int(time.time()), "from": old, "to": new,
                 "by": by, "why": (why or "")[:120]})
    prof["relation_history"] = hist[-int(DEFAULTS["history_keep"]):]
    prof["relation"] = new
    prof["relation_since"] = int(time.time())
    if confidence is not None:
        prof["relation_confidence"] = round(float(confidence), 2)
    return True


def apply_pending(wxid: str, by: str = "user") -> dict:
    """把待确认的关系落库。"""
    profiles = read_json(PROFILES, {})
    prof = profiles.get(wxid) or {}
    pend = prof.get("pending_relation") or {}
    if not pend.get("to"):
        return {"ok": False, "note": "没有待确认的关系变更"}
    old = prof.get("relation") or ""
    set_relation(prof, pend["to"], by, pend.get("why") or "",
                 pend.get("confidence"))
    prof.pop("pending_relation", None)
    profiles[wxid] = prof
    write_json(PROFILES, profiles)
    log("应用关系变更 %s: %s -> %s（%s）" % (
        prof.get("name") or wxid, old or "—", pend["to"], by))
    return {"ok": True, "note": "%s → %s" % (old or "—", pend["to"])}


def reject_pending(wxid: str) -> dict:
    """忽略这次提示，冷却期内不再提同一关系。"""
    profiles = read_json(PROFILES, {})
    prof = profiles.get(wxid) or {}
    pend = prof.get("pending_relation") or {}
    if not pend.get("to"):
        return {"ok": False, "note": "没有待确认的关系变更"}
    cooldown = list(prof.get("relation_cooldown") or [])
    cooldown.append({"to": pend["to"], "at": int(time.time())})
    prof["relation_cooldown"] = cooldown[-5:]
    prof.pop("pending_relation", None)
    profiles[wxid] = prof
    write_json(PROFILES, profiles)
    log("忽略关系变更 %s -> %s" % (prof.get("name") or wxid, pend["to"]))
    return {"ok": True, "note": "已忽略 %s" % pend["to"]}


# ---------------------------------------------------------------- 调模型
def ask(api_key: str, model: str, name: str, lines: list[str], prof: dict) -> dict | None:
    text = PROMPT.format(
        name=name, relations="、".join(RELATIONS),
        current=prof.get("relation") or "未知",
        tone=prof.get("my_tone") or "未知",
        summary=prof.get("summary") or "无",
        transcript="\n".join(lines),
    )
    payload = {
        "model": model,
        "thinking": {"type": "disabled"},
        "temperature": 0.3,
        "max_tokens": 900,
        "messages": [{"role": "user", "content": text}],
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key,
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode("utf-8"))
        raw = (data["choices"][0]["message"].get("content") or "").strip()
    except Exception as exc:
        log("调用失败: %s" % exc)
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        log("解析失败：返回里没有 JSON")
        return None
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        log("JSON 解析失败: %s" % exc)
        return None


# ---------------------------------------------------------------- 主流程
def analyze_one(wxid: str, prof: dict, api_key: str, model: str,
                opts: dict, force: bool = False) -> dict:
    """分析一个人。返回 {"ok","note"}。"""
    name = prof.get("name") or wxid
    now = int(time.time())
    since = int(prof.get("analyzed_until") or 0) or (now - 7 * 86400)
    lines = transcript(wxid, since, int(opts["window_days"]))
    if not lines:
        # 空记录喂给模型只会让它瞎猜关系，直接跳过
        return {"ok": False, "note": "没有新消息可分析"}
    if not force and len(lines) < int(opts["min_new_messages"]):
        return {"ok": False, "note": "新增消息太少（%d 条）" % len(lines)}

    res = ask(api_key, model, name, lines, prof)
    if not res:
        return {"ok": False, "note": "模型没给出结果"}

    # 风格：只在没被手动锁定时更新
    changed = []
    if not prof.get("style_locked"):
        for key, limit in (("summary", 200), ("my_tone", 80),
                           ("my_length", 40), ("habits", 8), ("taboos", 8)):
            val = res.get(key)
            if key in ("habits", "taboos"):
                if isinstance(val, list) and val:
                    prof[key] = [str(x)[:40] for x in val[:limit]]
                    changed.append(key)
            elif isinstance(val, str) and val.strip():
                prof[key] = val.strip()[:limit]
                changed.append(key)

    # 关系：先挂起，等确认或超时
    new_rel = str(res.get("relation") or "").strip()
    try:
        conf = float(res.get("relation_confidence"))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = None          # 模型没给可用的置信度：不覆盖旧值、也不挂待确认
    cur = str(prof.get("relation") or "")
    note = str(res.get("change_note") or "").strip()
    evidence = [str(x)[:60] for x in (res.get("evidence") or []) if str(x).strip()][:3]
    reason = str(res.get("relation_reason") or "").strip()[:120]

    had_pending = bool((prof.get("pending_relation") or {}).get("to"))
    if new_rel in RELATIONS and new_rel == cur:
        if had_pending:
            log("撤回待确认 %s：本次分析与当前关系一致（%s）" % (name, cur))
        prof.pop("pending_relation", None)
        if conf:
            prof["relation_confidence"] = round(conf, 2)
    elif new_rel in RELATIONS and conf is not None and conf >= float(opts["confidence_min"]):
        # 被忽略过的关系只冷却一段时间，不能永久压制
        days = int(opts["cooldown_days"])
        cool = [c for c in (prof.get("relation_cooldown") or [])
                if now - int(c.get("at") or 0) < days * 86400]
        if cool != (prof.get("relation_cooldown") or []):
            prof["relation_cooldown"] = cool
        if any(c.get("to") == new_rel for c in cool[-5:]):
            log("冷却中，不再提 %s -> %s" % (name, new_rel))
        else:
            pend = prof.get("pending_relation") or {}
            if pend.get("to") != new_rel:
                prof["pending_relation"] = {
                    "to": new_rel, "from": cur, "confidence": round(conf, 2),
                    "why": reason, "evidence": evidence,
                    "created_ts": now, "change_note": note,
                }
                log("待确认关系 %s: %s -> %s（置信 %.2f）" % (
                    name, cur or "—", new_rel, conf))
            else:
                # 同一目标再次出现：保留原始计时，别让提示无限续期
                prof["pending_relation"]["confidence"] = round(conf, 2)
                if reason:
                    prof["pending_relation"]["why"] = reason

    # 超时自动应用放在 sweep_expired() 里做：对方不再发消息时也要能把提示落地
    pend = prof.get("pending_relation") or {}
    prof["analyzed_until"] = now
    prof["last_analysis_ts"] = now
    prof["analysis_count"] = int(prof.get("analysis_count") or 0) + 1
    return {"ok": True, "note": "%d 条消息 / 关系 %s / %s" % (
        len(lines), prof.get("relation") or "—",
        "待确认" if pend.get("to") else "无变化")}


def run(wxid: str = "", force: bool = False) -> dict:
    """分析所有到期的人（或指定一个人）。"""
    opts = options()
    if not opts.get("enabled"):
        return {"ok": False, "note": "关系分析已关闭"}
    env = read_env()
    api_key = env.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"ok": False, "note": "缺少 DEEPSEEK_API_KEY"}
    cfg = read_json(CONFIG, {}) or {}
    model = cfg.get("model", "deepseek-v4-pro")

    profiles = read_json(PROFILES, {}) or {}
    wl = cfg.get("whitelist") or {}
    targets = [wxid] if wxid else [k for k in wl if k in profiles]
    now = int(time.time())
    before = json.dumps(profiles, ensure_ascii=False, sort_keys=True)

    # 先落地超时的待确认（跟这次有没有新消息无关）
    sweep_expired(profiles, opts, now)

    done = []
    for target in targets:
        prof = profiles.get(target) or {}
        if not prof:
            continue
        if not force and now - int(prof.get("last_analysis_ts") or 0) \
                < int(opts["daily_seconds"]):
            continue
        res = analyze_one(target, prof, api_key, model, opts, force=force)
        if res.get("ok"):
            profiles[target] = prof
            done.append("%s（%s）" % (prof.get("name") or target, res["note"]))
        else:
            # 同一个人同一个原因别每 10 分钟刷一条
            key = (target, str(res.get("note")))
            if now - _LAST_SKIP.get(key, 0) > 6 * 3600:
                _LAST_SKIP[key] = now
                log("跳过 %s: %s" % (prof.get("name") or target, res.get("note")))

    # 没有真正的变化就别重写文件：既避免无谓的 mtime 抖动，也降低跟面板
    # 同时保存时互相覆盖的概率
    if json.dumps(profiles, ensure_ascii=False, sort_keys=True) != before:
        write_json(PROFILES, profiles)
    if done:
        log("本轮分析完成: " + "；".join(done))
    return {"ok": True, "note": "分析 %d 人" % len(done)}


def sweep_expired(profiles: dict, opts: dict, now: int) -> list[str]:
    """把超过 pending_hours 还没人处理的待确认关系自动落地。"""
    hours = int(opts["pending_hours"])
    applied = []
    for wxid, prof in list(profiles.items()):
        pend = prof.get("pending_relation") or {}
        if not pend.get("to"):
            continue
        if now - int(pend.get("created_ts") or now) < hours * 3600:
            continue
        set_relation(prof, pend["to"], "auto",
                     (pend.get("why") or "") + "（提示 %d 小时未确认，自动应用）" % hours,
                     pend.get("confidence"))
        prof.pop("pending_relation", None)
        applied.append("%s: %s -> %s" % (prof.get("name") or wxid,
                                         pend.get("from") or "—", pend["to"]))
        log("超时自动应用关系 %s: %s -> %s" % (
            prof.get("name") or wxid, pend.get("from") or "—", pend["to"]))
    return applied


def daily_tick() -> dict:
    """机器人里每 10 分钟调一次，真正干活是每人每天一次。"""
    try:
        return run()
    except Exception as exc:
        log("daily_tick 异常: %s" % exc)
        return {"ok": False, "note": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wxid", default="")
    ap.add_argument("--force", action="store_true", help="忽略每天一次的限制")
    args = ap.parse_args()
    res = run(args.wxid.strip(), force=args.force or bool(args.wxid))
    print(res.get("note"))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
