#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Weix 替代实现 —— 微信自动回复（独立、无第三方程序）。

设计原则（按需求排序）：
  1. 绝不发错人：发送前必须通过 OCR 标题校验；任何一步不确定就放弃
  2. 全部文件落在安装目录内
  3. 只用标准库（ctypes + 系统 bcrypt + Windows OCR）

流程：
  轮询数据库 → 过滤（白名单/文本/非自己）→ 按会话合并 8 秒 → 生成回复
  → OCR 校验会话 → 发送 → 回读数据库确认
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths         # noqa: E402
import wcdb          # noqa: E402
import evolve        # noqa: E402
import schedule as sched   # noqa: E402
import vision        # noqa: E402
import wxsend        # noqa: E402

BASE = paths.ROOT
CONFIG = paths.BOT_CONFIG
ENV = paths.ENV_FILE
LOG = paths.BOT_LOG
PROFILES = paths.PROFILES
STATE = paths.STATE
LOCK = paths.BOT_LOCK
paths.ensure_dirs()

POLL_SECONDS = 3

TEMP_MAX = 1.2          # 硬上限：超过这个值模型会开始乱接词（1.5 会飘到跟话题无关）
TEMP_MIN = 0.0

# 客服腔/AI 腔的典型说法：命中就重来一次，人不会这么说话
AI_TELLS = [
    "我理解", "我明白你的", "有什么可以", "需要我", "我可以帮", "希望能帮",
    "首先", "其次", "总之", "总的来说", "作为", "建议你", "听起来",
    "我不插嘴", "那你说", "你说吧", "随时可以", "不用客气", "别客气",
]

# 风格样例只从"本人"说过的话里取，机器人自己发过的句子用日志剔掉
# （实现放在 evolve.bot_sent_texts，面板/分析器共用同一份）



def persona_is_placeholder(text: str) -> bool:
    """判断人设是不是还停在模板上（用户没动过）。"""
    s = text or ""
    if not s.strip():
        return True
    return ("改成你自己的" in s) or ("（例：" in s and "Layer 1" in s)


def clamp_temp(value, fallback: float = 0.7) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(TEMP_MIN, min(TEMP_MAX, v))


# WeChat 4.x 的 local_type：低 32 位是基础类型，高 32 位是应用消息的子类型
# 情商档位：1 最直，5 最会照顾情绪
EQ_LEVELS = {
    1: "只就事论事，不接情绪、不安慰、不追问对方感受",
    2: "能听出情绪但一带而过，只给结论不给人情味",
    3: "正常水准，简短关心一句，不深挖也不敷衍",
    4: "先回应情绪再说事，会用一句具体的关心（问一句怎么了、让他慢点）",
    5: "先接住情绪，鼓励对方再多说一点，再给回应；关心要具体，不空泛不敷衍",
}

# 性别差异：只影响措辞分寸，不改变事实判断
GENDER_HINTS = {
    "男": "对方是男生，说话可以更直接干脆，少用软的语气词，不撒娇、不过度关心",
    "女": "对方是女生，语气柔和一点，注意分寸和边界，不油腻、不越界",
}

# 关系够近的人，睡前会顺口说一句困了；其他人不打扰
CLOSE_RELATIONS = {
    "女朋友", "男朋友", "妻子", "丈夫", "暧昧对象",
    "发小", "好朋友", "室友",
    "父母", "兄弟姐妹", "子女", "亲戚", "长辈",
}

# ---- 见面邀约：不能答应，只能委婉推 ----
MEET_WORDS = ["见面", "见个面", "见一面", "见一下", "出来", "约", "来找你", "去你那",
              "过来玩", "一起吃饭", "一起喝", "碰个头", "聚一下", "见你"]

AGREE_WORDS = ["好", "行", "可以", "没问题", "当然", "随时", "来吧", "能", "成",
               "我等你", "马上到", "几点", "哪里见", "在哪见", "地址"]

REFUSE_WORDS = ["不", "没", "忙", "改天", "下次", "再说", "缓缓", "算了", "不方便",
                "过阵子", "这阵子", "最近事多", "抽不出"]

SAFE_REFUSALS = [
    "最近有点忙，过阵子再说吧",
    "这阵子不太方便，缓缓吧",
    "最近事多，改天吧",
    "等我忙完这阵子吧",
]


def wants_meeting(text: str) -> bool:
    """对方是不是在约见面。"""
    t = (text or "").strip()
    if not t:
        return False
    return any(w in t for w in MEET_WORDS)


def agrees_meeting(reply: str) -> bool:
    """回复里是不是答应了见面。"""
    r = (reply or "").strip()
    if not r:
        return False
    if any(w in r for w in REFUSE_WORDS):
        return False
    return any(w in r for w in AGREE_WORDS)


TYPE_HINT = (
    "对话里的 [图片] [语音] [视频] [表情] [位置] [链接或文件] 是对方消息的类型标记。"
    "看到 [图片] 就表示对方发了图片，不要编造图片内容，简短回应即可；"
    "看到 [语音] 可以回「语音不方便听，打字说吧」这类；"
    "表情可以轻松接一下就过去。回复仍然遵守 25 字上限、不用句号。"
)

TYPE_LABELS = {
    3: "[图片]",
    34: "[语音]",
    42: "[名片]",
    43: "[视频]",
    47: "[表情]",
    48: "[位置]",
    49: "[链接或文件]",
    50: "[通话]",
}
REPLIABLE = {1} | set(TYPE_LABELS.keys())


def base_type(local_type: int) -> int:
    return int(local_type) & 0xFFFFFFFF



LOG_MAX_BYTES = 50 * 1024 * 1024     # 安全上限，防死循环把盘写满
_LOGROT_DAY = -1


def _log_monthly_maintenance() -> None:
    """按月归档日志，并删掉超过 35 天的旧归档。每天最多跑一次。"""
    global _LOGROT_DAY
    today = int(time.time() // 86400)
    if today == _LOGROT_DAY:
        return
    _LOGROT_DAY = today
    folder = os.path.dirname(LOG) or "."
    try:
        mt = time.localtime(os.path.getmtime(LOG))
        now = time.localtime()
        if (mt.tm_year, mt.tm_mon) != (now.tm_year, now.tm_mon):
            arch = os.path.join(folder, "bot-%04d-%02d.log" % (mt.tm_year, mt.tm_mon))
            os.replace(LOG, arch)
            try:
                os.utime(arch, None)      # 归档时间记为"现在"，避免被旧文件规则立刻删掉
            except OSError:
                pass
    except OSError:
        pass
    cutoff = time.time() - 35 * 86400
    try:
        for name in os.listdir(folder):
            if name.startswith("bot-") and name.endswith(".log"):
                path = os.path.join(folder, name)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


def log(msg: str) -> None:
    line = "%s | %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    _log_monthly_maintenance()
    try:
        if os.path.getsize(LOG) > LOG_MAX_BYTES:
            bak = LOG + ".1"
            try:
                os.replace(bak, LOG + ".2")
            except OSError:
                pass
            os.replace(LOG, bak)
            line = "%s | （日志超过 50MB，已切分）\n%s" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), line)
    except OSError:
        pass
    try:
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


class Bot:
    def __init__(self) -> None:
        self.cfg = json.load(open(CONFIG, encoding="utf-8"))
        self.env = read_env()
        self.whitelist = {k: v for k, v in (self.cfg.get("whitelist") or {}).items()}
        self.db_dir, self.keys = wcdb.load_keys()
        self.cache = wcdb.PlainCache()
        self.api_key = self.env.get("DEEPSEEK_API_KEY", "")
        self.self_wxid = self._detect_self_wxid()
        self.refresh_whitelist()
        self.pending: dict[str, dict] = {}
        self.last_sent: dict[str, float] = {}
        self.sent_texts: dict[str, float] = {}   # key = "wxid|内容"
        self.recent_sent: dict[str, list] = {}   # 刚发出、可能还没入库的回复
        self.deferred: dict[str, list] = {}      # 睡眠期间收到、醒来后再回的消息

    def _detect_self_wxid(self) -> str:
        """自己的 wxid。

        账号目录名带 _xxxx 后缀（如 wxid_xxx_56ba），不能直接当 wxid 用，
        否则自己发出的消息会被当成对方发来的。以消息库里的真实 wxid 为准。
        """
        try:
            wxid = wcdb.detect_self_wxid(self.db_dir, self.keys, self.cache)
        except Exception as exc:
            log("推断自己的 wxid 失败: %s" % exc)
            wxid = ""
        if wxid:
            return wxid
        fallback = os.path.basename(os.path.dirname(self.db_dir.rstrip("\\/")))
        log("警告：无法确认自己的 wxid，退回目录名 %s（可能认不出自己发的消息）" % fallback)
        return fallback

    def _bot_sent_texts(self) -> set[str]:
        """机器人自己发过的句子（从日志里扒），用来把"我"和"机器人"区分开。"""
        return evolve.bot_sent_texts()

    def voice_samples(self, chat_wxid: str, cut_ts: int = 0, n: int = 6) -> list[str]:
        """本人以前对这个人的原话，给模型当语气参照。

        只用"我"发过、且不是机器人代发的句子（拿日志里的发送记录剔除），
        不然会把机器人自己的 AI 腔当成本人风格学回去。
        """
        sent = self._bot_sent_texts()
        out: list[str] = []
        for m in wcdb.chat_history(self.db_dir, self.keys, self.cache, chat_wxid, limit=200):
            if m.get("sender_wxid") != self.self_wxid:
                continue
            if cut_ts and int(m.get("create_time", 0)) >= cut_ts:
                continue
            t = (m.get("content") or "").strip()
            if not (2 <= len(t) <= 20):
                continue
            if not any("\u4e00" <= ch <= "\u9fff" for ch in t):
                continue
            flat = "".join(t.split())
            if any(b and (b in flat or flat in b) for b in sent):
                continue
            if t in out:
                continue
            out.append(t)
        return out[-n:]

    @staticmethod
    def _voice_directive(samples: list[str]) -> str:
        return ("你以前跟这个人说话是这样的（都是你本人发的原话）：\n"
                + "\n".join("· " + s for s in samples)
                + "\n照着这个口气和长度回：短、随口、口语词随便用；"
                  "别照抄原句，别写成客服或助手。")

    @staticmethod
    def looks_ai(reply: str) -> str:
        """像客服/AI 就返回命中的词，正常返回空串。"""
        r = reply or ""
        for w in AI_TELLS:
            if w in r:
                return w
        return ""

    def _post(self, payload: dict) -> str:
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.api_key,
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data["choices"][0]["message"].get("content") or "").strip()

    def _deai(self, reply: str, payload: dict) -> str:
        """回复带上客服腔就重写一次；重写还是不行就用原来的。"""
        tell = self.looks_ai(reply)
        if not tell:
            return reply
        log("回复太像客服（命中「%s」），换一种说法" % tell)
        retry = dict(payload)
        retry["messages"] = list(payload.get("messages") or [])
        retry["temperature"] = 0.9
        retry["messages"].insert(
            max(0, len(retry["messages"]) - 1),
            {"role": "system", "content":
             "刚才那句太像客服/AI 了。重来：像随手打字，两三个字也行，"
             "能用语气词就用；别解释、别总结、别说「那你说」「我不插嘴」这类话。"})
        try:
            again = self._post(retry)
        except Exception as exc:
            log("重写失败: %s" % exc)
            return reply
        return again if again and not self.looks_ai(again) else reply

    def profile_for(self, wxid: str) -> dict:
        """取这个人的画像；文件变了就重新加载。"""
        try:
            mt = os.path.getmtime(PROFILES)
        except OSError:
            return {}
        if getattr(self, "_prof_mtime", None) != mt:
            try:
                self._profiles = json.load(open(PROFILES, encoding="utf-8"))
            except Exception:
                self._profiles = {}
            self._prof_mtime = mt
        return (getattr(self, "_profiles", {}) or {}).get(wxid, {})

    def ensure_profile(self, wxid: str, name: str) -> None:
        """没有画像就现建一个：读历史 → 归纳关系与说话方式 → 存盘。"""
        if self.profile_for(wxid):
            return
        try:
            import build_profiles as bp
        except Exception:
            return
        hist = wcdb.chat_history(self.db_dir, self.keys, self.cache, wxid, limit=200)
        if len(hist) < 10:
            return
        prof = bp.ask(self.api_key, self.cfg.get("model", "deepseek-v4-pro"), name, hist, wxid)
        if not prof:
            return
        prof["name"] = name
        prof["updated_at"] = int(time.time())
        prof["sample_size"] = len(hist)
        try:
            data = json.load(open(PROFILES, encoding="utf-8"))
        except Exception:
            data = {}
        data[wxid] = prof
        tmp = PROFILES + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROFILES)
        self._prof_mtime = None
        log("新建画像 %s：%s | %s" % (name, prof.get("relation"), prof.get("my_tone")))

    # ------------------------------------------------------------ 名字
    def display_name(self, wxid: str) -> str:
        if wxid in self.whitelist:
            return self.whitelist[wxid]
        plain = self.cache.get(os.path.join(self.db_dir, "contact", "contact.db"),
                               self.keys.get(os.path.join("contact", "contact.db"), b""))
        if not plain:
            return ""
        import sqlite3
        con = sqlite3.connect("file:%s?mode=ro" % plain.replace("\\", "/"), uri=True)
        try:
            row = con.execute(
                "select remark, nick_name, alias from contact where username=?", (wxid,)
            ).fetchone()
            if row:
                return str(row[0] or row[1] or row[2] or "")
        finally:
            con.close()
        return ""

    # ------------------------------------------------------------ 白名单解析
    @staticmethod
    def _is_wxid(s: str) -> bool:
        s = (s or "").strip()
        return s.startswith("wxid_") or s.startswith("gh_") or s.endswith("@chatroom")

    def refresh_whitelist(self) -> None:
        """白名单既可写 wxid，也可只写名字——名字在这里查成 wxid。"""
        raw = self.cfg.get("whitelist") or {}
        resolved: dict[str, str] = {}
        for key, val in raw.items():
            key = (key or "").strip()
            val = (val or "").strip()
            if not key:
                continue
            if self._is_wxid(key):
                resolved[key] = val or key
                continue
            hits = wcdb.resolve_contacts(self.db_dir, self.keys, self.cache, key)
            if len(hits) == 1:
                h = hits[0]
                resolved[h["wxid"]] = val or h["name"]
                log("白名单解析: %s -> %s（命中%s）" % (val or key, h["wxid"], h["field"]))
            elif not hits:
                log("白名单名字未找到，已忽略: %s" % key)
            else:
                log("白名单名字有歧义，已跳过: %s -> %s" % (key, [h["wxid"] for h in hits]))
        self.whitelist = resolved
        if resolved:
            log("白名单生效: %s" % list(resolved.values()))

    # ------------------------------------------------------------ 唯一性硬闸门
    def name_is_unique(self, wxid: str, name: str) -> tuple[bool, str]:
        """确认 name 在本机只对应 wxid 这一个联系人。

        这是"绝不发错人"的硬闸门：Ctrl+F 搜同一个名字时，微信只会命中这个
        唯一联系人，不会打开别人。名字有歧义就拒绝发送。
        """
        import sqlite3
        if not name:
            return False, "显示名为空"
        plain = self.cache.get(os.path.join(self.db_dir, "contact", "contact.db"),
                               self.keys.get(os.path.join("contact", "contact.db"), b""))
        if not plain:
            return False, "联系人库不可读"
        con = sqlite3.connect("file:%s?mode=ro" % plain.replace("\\", "/"), uri=True)
        try:
            rows = con.execute(
                "select username from contact where remark=? or nick_name=? or alias=?",
                (name, name, name)).fetchall()
        finally:
            con.close()
        users = {r[0] for r in rows}
        if not users:
            return False, "联系人库里找不到该名字"
        if len(users) > 1:
            return False, "名字对应多个联系人: %s" % sorted(users)
        if wxid not in users:
            return False, "名字对应的不是目标 wxid: %s" % sorted(users)
        return True, "唯一匹配"

    # ------------------------------------------------------------ 生成
    def generate(self, chat_wxid: str, message: str, woke_up: bool = False,
                 cut_ts: int = 0) -> str:
        if not self.api_key:
            log("缺少 DEEPSEEK_API_KEY")
            return ""
        cfg = self.cfg
        prof = self.profile_for(chat_wxid)
        name = prof.get("name") or self.display_name(chat_wxid) or "对方"

        entries: list[tuple[int, str, str]] = []
        for m in wcdb.chat_history(self.db_dir, self.keys, self.cache, chat_wxid, limit=12):
            ts = int(m.get("create_time", 0))
            # 这次要回的这批消息已经在库里了，只取它之前的当作上下文，
            # 否则同一句话会既在历史里出现、又在最后再挂一次，模型会以为
            # "我已经答过了"，然后自说自话跑题。
            if cut_ts and ts >= cut_ts:
                continue
            who = "我" if m.get("sender_wxid") == self.self_wxid else name
            entries.append((ts, who, m.get("content", "")))
        # 微信把"我发出的消息"写进数据库有几十秒延迟，这里把刚发出的回复补进去，
        # 否则模型不知道自己上一句说了什么，容易答得驴唇不对马嘴。
        known = {text for _, _, text in entries}
        for ts, text in self.recent_sent.get(chat_wxid, []):
            if text not in known:
                entries.append((int(ts), "我", text))
        entries.sort(key=lambda x: x[0])
        turns: list[dict] = []
        for _, who, text in entries[-14:]:
            role = "assistant" if who == "我" else "user"
            text = (text or "").strip()
            if not text:
                continue
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"] += "\n" + text      # 同一个人连发，合并
            else:
                turns.append({"role": role, "content": text})

        # 对话必须收在"对方刚说的这句"上；历史里已经有了就不再重复挂一遍
        final = (message or "").strip()
        flat = "".join(final.split())
        if not (turns and turns[-1]["role"] == "user"
                and "".join(turns[-1]["content"].split()).endswith(flat)):
            turns.append({"role": "user", "content": final})

        relation = ""
        if prof:
            bits = []
            gender = str(prof.get("gender", "")).strip()
            eq = prof.get("eq")
            try:
                eq = int(eq)
            except (TypeError, ValueError):
                eq = 0
            if prof.get("relation"):
                bits.append("你和%s的关系是%s" % (name, prof["relation"]))
            if prof.get("my_tone"):
                bits.append("你平时对他说话%s" % prof["my_tone"])
            if prof.get("my_length"):
                bits.append("回复长度%s" % prof["my_length"])
            if prof.get("habits"):
                bits.append("你的习惯：" + "、".join(prof["habits"][:4]))
            if prof.get("taboos"):
                bits.append("注意：" + "、".join(prof["taboos"][:3]))
            if prof.get("summary"):
                bits.append("相处方式：" + prof["summary"])
            relation = "。".join(bits) + "。"

        voice = self.voice_samples(chat_wxid, cut_ts)
        payload = {
            "model": cfg.get("model", "deepseek-v4-pro"),
            "messages": [
                {"role": "system", "content": cfg.get("persona", "")},
                {"role": "system", "content": relation or ("你和%s是普通朋友，说话自然一点。" % name)},
                {"role": "system", "content": self._style_directive(prof, name)},
                *([{"role": "system", "content": self._voice_directive(voice)}]
                  if voice else []),
                {"role": "system", "content": self._time_directive()},
                *([{"role": "system", "content": self._sleepy_directive(prof)}]
                  if self._sleepy_directive(prof) else []),
                *([{"role": "system", "content": self._wake_directive(prof)}]
                  if woke_up and self._wake_directive(prof) else []),
                {"role": "system", "content": "下面是你们最近的对话，接着往下聊，"
                                              "结合上下文回，别重复你刚说过的话。"},
                {"role": "system", "content": TYPE_HINT},
                *turns,
            ],
            "temperature": clamp_temp(
                prof.get("temperature") if isinstance(prof.get("temperature"), (int, float))
                else cfg.get("temperature", 0.7)),
            "max_tokens": cfg.get("max_tokens", 2000),
            "thinking": {"type": "disabled"},
        }
        for attempt in (1, 2):
            try:
                req = urllib.request.Request(
                    "https://api.deepseek.com/chat/completions",
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Authorization": "Bearer " + self.api_key,
                             "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                reply = (data["choices"][0]["message"].get("content") or "").strip()

                # 对方在约见面：只要回复里松口，就重来一次，还不行换成固定的委婉拒绝
                if wants_meeting(message):
                    if agrees_meeting(reply):
                        log("对方在约见面，回复松口了，重试一次")
                        payload["messages"].insert(
                            len(payload["messages"]) - 1,
                            {"role": "system", "content":
                             "对方在约你见面。绝对不能答应，不要说可以、行、好、没问题，"
                             "不要问时间地点。用一句话委婉推掉：最近忙 / 这段时间不方便 / 改天。"})
                        payload["temperature"] = 0.6
                        req3 = urllib.request.Request(
                            "https://api.deepseek.com/chat/completions",
                            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                            headers={"Authorization": "Bearer " + self.api_key,
                                     "Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req3, timeout=60) as r3:
                            data3 = json.loads(r3.read().decode("utf-8"))
                        again = (data3["choices"][0]["message"].get("content") or "").strip()
                        if again and not agrees_meeting(again):
                            return again
                        return SAFE_REFUSALS[int(time.time()) % len(SAFE_REFUSALS)]

                # 太像客服/AI 就换一句
                reply = self._deai(reply, payload)

                # 温度调得太高时模型会崩，这里自动降档重来一次
                used = payload.get("temperature", 0.7)
                if self.looks_broken(reply) and used and used > 1.05:
                    log("回复异常，降到 0.8 重试（原温度 %.1f）" % used)
                    payload["temperature"] = 0.8
                    req2 = urllib.request.Request(
                        "https://api.deepseek.com/chat/completions",
                        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        headers={"Authorization": "Bearer " + self.api_key,
                                 "Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req2, timeout=60) as r2:
                        data2 = json.loads(r2.read().decode("utf-8"))
                    retry = (data2["choices"][0]["message"].get("content") or "").strip()
                    if not self.looks_broken(retry):
                        return self._deai(retry, payload)
                return reply
            except Exception as exc:
                if attempt == 2:
                    log("AI 生成失败: %s" % exc)
                    return ""
                payload.pop("thinking", None)
        return ""

    @staticmethod
    def looks_broken(reply: str) -> bool:
        """粗判回复是否已经崩坏（温度过高时会出现长串乱七八糟的话）。"""
        import re
        if not reply:
            return True
        if len(reply) > 60:
            return True
        if re.search(r"[，。、！？,.!?；;]{3,}", reply):
            return True
        if re.search(r"[A-Za-z0-9]{12,}", reply):
            return True
        return False

    # ------------------------------------------------------------ 语音转文字
    def transcribe_voice(self, name: str) -> str:
        """打开会话 → 右键语音 → 点「语音转文字」→ 读取转写结果。"""
        if not wxsend.ensure_ready():
            return ""
        if not wxsend.open_chat(name):
            return ""
        time.sleep(0.8)
        if not wxsend.transcribe_last_voice():
            log("语音转文字：菜单项未找到，跳过")
            return ""
        time.sleep(0.6)
        return wxsend.read_bottom_text()

    # ------------------------------------------------------------ 图片理解
    def describe_last_image(self, name: str) -> str:
        """打开会话 → 截聊天区 → 交给视觉模型描述最后一张图。"""
        hwnd = wxsend.ensure_ready()
        if not hwnd:
            return ""
        if not wxsend.open_chat(name):
            return ""
        time.sleep(0.6)
        bmp = wxsend.capture_chat_area("chat")
        if not bmp:
            return ""
        try:
            png = vision.bmp_to_png(bmp)
            return vision.describe(png, self.api_key, self.cfg.get("vision_model", "deepseek-flash"))
        finally:
            for p2 in (bmp, bmp.rsplit(".", 1)[0] + ".png"):
                try:
                    os.remove(p2)
                except OSError:
                    pass

    def _time_directive(self) -> str:
        """按当前时段给出"我现在在干嘛"的上下文。"""
        state, info = sched.schedule_state(self.cfg)
        self._last_state = (state, info)
        if state == "睡觉":
            # 消息在睡前到达、回复时刚好过点：既然要回，就回得迷迷糊糊
            return "现在是%s，你已经躺下快睡着了。回复要极短，像迷糊中回一句。" % info["time"]
        return sched.hint_text(state, info)

    def _wake_directive(self, prof: dict) -> str:
        """刚睡醒：关系够近的先说明自己醒了，再回对方之前的话。"""
        rel = str((prof or {}).get("relation") or "").strip()
        if rel not in CLOSE_RELATIONS:
            return ""
        return ("对方在你睡觉的时候发过消息，你才刚醒。先用一句自然的话说明自己刚睡醒"
                "（刚起、睡到现在、刚睁眼这类，别太正式），再回应他之前说的内容。")

    def _sleepy_directive(self, prof: dict) -> str:
        """快睡觉了、且关系够近时，说明自己困了要睡。"""
        rel = str((prof or {}).get("relation") or "").strip()
        if rel not in CLOSE_RELATIONS:
            return ""
        sleepy, info = sched.presleep_state(self.cfg)
        if not sleepy:
            return ""
        return ("现在是 %s，你困得不行了，还有 %d 分钟就要睡。回复里要自然带出"
                "「困了/撑不住了/准备睡了」的意思，别开新话题、别约事，让对方知道你马上要睡。"
                % (info["time"], max(1, info["minutes"])))

    def _style_directive(self, prof: dict, name: str) -> str:
        """把性别和情商转成一条针对本次回复的强指令。"""
        lines = []
        gender = str(prof.get("gender", "")).strip()
        if gender in GENDER_HINTS:
            lines.append(GENDER_HINTS[gender])
        try:
            eq = int(prof.get("eq"))
        except (TypeError, ValueError):
            eq = 0
        if eq in EQ_LEVELS:
            lines.append("这次回复的情商档位是 %d/5：%s" % (eq, EQ_LEVELS[eq]))
        if not lines:
            return "像平时一样自然回复。"
        return "；".join(lines) + "。回复依然保持简短。"

    # ------------------------------------------------------------ 发送后回读
    def confirm_sent(self, chat_wxid: str, text: str, timeout: float = 60.0) -> bool:
        """回读数据库，确认这条内容确实出现在目标会话里。

        这是"绝不发错人"的第二道闸：不仅要求发出去，还要求落在正确的会话。
        """
        target = "".join(text.split())
        deadline = time.time() + timeout
        while time.time() < deadline:
            msgs = wcdb.collect_new_messages(self.db_dir, self.keys, self.cache,
                                             int(time.time()) - 300)
            for m in msgs:
                if m.get("chat_wxid") != chat_wxid:
                    continue
                if m.get("sender_wxid") != self.self_wxid:
                    continue
                if "".join((m.get("content") or "").split()) == target:
                    return True
            time.sleep(2.0)
        return False

    # ------------------------------------------------------------ 睡眠补回
    def catch_up(self) -> None:
        """启动时把上一次睡眠期间收到的消息捡回来（软件关着也有效）。"""
        try:
            win = sched.sleep_window_last(self.cfg, datetime.datetime.now())
        except Exception:
            return
        if not win:
            return
        start, end = win
        try:
            last = int((self.load_state() or {}).get("last_ts") or 0)
        except Exception:
            last = 0
        since = max(start, min(last, end)) if last else start
        try:
            msgs = wcdb.collect_new_messages(self.db_dir, self.keys, self.cache, since)
        except Exception as exc:
            log("补回失败: %s" % exc)
            return
        n = 0
        for m in msgs:
            ct = int(m.get("create_time") or 0)
            if ct >= end:
                continue
            chat = m.get("chat_wxid") or ""
            sender = m.get("sender_wxid") or ""
            if not chat or sender == self.self_wxid:
                continue
            if chat not in self.whitelist and sender not in self.whitelist:
                continue
            if base_type(m.get("local_type", 0)) != 1:
                continue
            text = (m.get("content") or "").strip()
            if not text:
                continue
            m["_text"] = text
            box = self.deferred.setdefault(chat, [])
            if len(box) < 15:
                box.append(m)
                n += 1
        if n:
            log("补回睡眠期间 %d 条消息，醒来后回复" % n)
        # 把进度推到起床点，避免主循环再扫一遍这些旧消息（也防止重复回复）
        try:
            st = self.load_state() or {}
            st["last_ts"] = max(int(st.get("last_ts") or 0), end)
            self.save_state(st)
        except Exception:
            pass

    def wake_deferred(self) -> None:
        """已经醒了就把睡眠期间攒的消息转成待回复。"""
        if not self.deferred:
            return
        try:
            sleeping, _ = sched.is_sleeping(self.cfg, datetime.datetime.now())
        except Exception:
            sleeping = False
        if sleeping:
            return
        items, self.deferred = self.deferred, {}
        n = 0
        for chat, msgs in items.items():
            for m in msgs:
                self.enqueue(m, int(time.time()), backlog=True)
                n += 1
        if n:
            log("醒了，补回睡眠期间 %d 条消息" % n)

    # ------------------------------------------------------------ 关系演化
    def start_evolve_loop(self) -> None:
        """后台线程：每天给每个人重看一次关系，不阻塞回复主循环。"""
        import threading

        def loop():
            time.sleep(90)                 # 等启动稳定
            while True:
                try:
                    evolve.daily_tick()
                except Exception as exc:
                    log("关系分析异常: %s" % exc)
                time.sleep(600)

        threading.Thread(target=loop, daemon=True).start()

    # ------------------------------------------------------------ 状态
    def load_state(self) -> dict:
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            return {}

    def save_state(self, st: dict) -> None:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, STATE)

    def reload_config(self) -> None:
        """配置文件变了就重载，让面板改参数立刻生效。"""
        try:
            mt = os.path.getmtime(CONFIG)
        except OSError:
            return
        if getattr(self, "_cfg_mtime", None) == mt:
            return
        try:
            self.cfg = json.load(open(CONFIG, encoding="utf-8"))
        except Exception:
            return
        self._cfg_mtime = mt
        self.refresh_whitelist()
        log("配置已重载 | 合并=%ss | 间隔=%ss" % (
            self.cfg.get("debounce_seconds"), self.cfg.get("min_reply_interval")))

    # ------------------------------------------------------------ 主循环
    def run(self) -> int:
        st = self.load_state()
        since = int(st.get("last_ts", 0))
        if not since:
            since = int(time.time())
            st["last_ts"] = since
            self.save_state(st)
            log("基线建立 last_ts=%d（不回复历史消息）" % since)
        log("启动 | self=%s | 白名单=%s | 库=%s" %
            (self.self_wxid, list(self.whitelist.items()), os.path.basename(self.db_dir)))
        if persona_is_placeholder(self.cfg.get("persona", "")):
            log("【还没写人设】config/bot.json 的 persona 还是模板。"
                "打开控制面板 →「参数 → 全局人设」照着自己的说话方式填一遍，"
                "不然回复会很空、很像客服。")
        self.catch_up()
        self.start_evolve_loop()

        while True:
            try:
                self.reload_config()
                self.wake_deferred()
                now = int(time.time())
                msgs = wcdb.collect_new_messages(self.db_dir, self.keys, self.cache, since)
                for m in msgs:
                    since = max(since, int(m["create_time"]))
                    st["last_ts"] = since
                    self.save_state(st)
                    self.enqueue(m, now)
                self.flush(now)
                if now - int(st.get("last_prune", 0)) > 1800:
                    self.prune()
                    st["last_prune"] = now
                    self.save_state(st)
                time.sleep(POLL_SECONDS)
            except KeyboardInterrupt:
                log("收到中断")
                break
            except Exception as exc:
                log("主循环异常: %s" % exc)
                time.sleep(5)
        return 0

    def prune(self) -> None:
        """清理缓存目录：旧的解密库 + sqlite 边车文件，避免无限增长。"""
        d = self.cache.dir
        try:
            files = [os.path.join(d, f) for f in os.listdir(d)]
        except OSError:
            return
        now = time.time()
        removed = 0
        for f in files:
            try:
                age = now - os.path.getmtime(f)
                is_img = f.lower().endswith((".bmp", ".png"))
                if (is_img and age > 300) or age > 1800:
                    os.remove(f)
                    removed += 1
            except OSError:
                pass
        if removed:
            log("缓存清理 %d 个文件" % removed)
        # 回声表只拦刚发出去不久的消息，一小时前的记录没必要留着
        cutoff = time.time() - 3600
        self.sent_texts = {k: v for k, v in self.sent_texts.items() if v >= cutoff}

    def enqueue(self, m: dict, now: int, backlog: bool = False) -> None:
        chat = m.get("chat_wxid", "")
        sender = m.get("sender_wxid", "")
        if not chat or not sender:
            return
        if sender == self.self_wxid:
            return
        if chat not in self.whitelist and sender not in self.whitelist:
            return
        raw_type = int(m.get("local_type", 0))
        btype = base_type(raw_type)
        if btype not in REPLIABLE:
            return
        if btype == 1:
            text = (m.get("content") or "").strip()
            if not text:
                return
            norm = "".join(text.split())
            if ("%s|%s" % (chat, norm)) in self.sent_texts:
                log("跳过自己发出的回声: %s" % text[:30])
                return
        else:
            # 图片/语音等：内容字段是二进制，只用类型标记参与回复
            text = TYPE_LABELS[btype]
            log("非文本消息 type=%s -> %s" % (raw_type, text))
        if not backlog and now - int(m["create_time"]) > int(self.cfg.get("max_message_age_seconds", 180)):
            log("跳过过期消息 age=%ds" % (now - int(m["create_time"])))
            return

        # 睡眠时段：先记下来，醒来后统一回复
        if not backlog:
            state, sinfo = sched.schedule_state(self.cfg)
            if state == "睡觉":
                box = self.deferred.setdefault(chat, [])
                if len(box) < 15:
                    m["_text"] = text
                    box.append(m)
                log("睡眠时段，先记下待回: %s" % text[:20])
                return

        key = chat
        buf = self.pending.setdefault(key, {"texts": [], "ts": [], "deadline": 0.0,
                                            "has_image": False, "has_voice": False,
                                            "woke_up": False})
        if backlog:
            buf["woke_up"] = True
        buf["texts"].append(text)
        buf["ts"].append(int(m.get("create_time") or 0))
        if btype == 3:
            buf["has_image"] = True
        elif btype == 34:
            buf["has_voice"] = True
        buf["deadline"] = time.time() + float(self.cfg.get("debounce_seconds", 8))
        log("入缓冲 chat=%s 第%d条: %s" % (chat, len(buf["texts"]), text[:30]))

    def flush(self, now: int) -> None:
        for chat in list(self.pending.keys()):
            buf = self.pending[chat]
            if time.time() < buf["deadline"]:
                continue
            texts = list(buf["texts"])
            del self.pending[chat]
            combined = "\n".join(texts)[:2000]
            stamps = [t for t in (buf.get("ts") or []) if t]
            cut_ts = min(stamps) if stamps else 0
            name = self.display_name(chat)
            if not name:
                log("拿不到 %s 的显示名，放弃（不发到不确定的会话）" % chat)
                continue
            gap = time.time() - self.last_sent.get(chat, 0)
            if gap < float(self.cfg.get("min_reply_interval", 15)):
                time.sleep(float(self.cfg.get("min_reply_interval", 15)) - gap)
            self.ensure_profile(chat, name)
            if buf.get("has_voice"):
                spoken = self.transcribe_voice(name)
                if spoken:
                    log("语音转文字: %s" % spoken[:50])
                    combined = "[语音]（转文字：%s）\n%s" % (spoken, combined)
            if buf.get("has_image"):
                desc = self.describe_last_image(name)
                if desc:
                    log("图片内容: %s" % desc[:60])
                    combined = "[图片]（图片里是：%s）\n%s" % (desc, combined)
            reply = self.generate(chat, combined, woke_up=bool(buf.get("woke_up")),
                                  cut_ts=cut_ts)
            if not reply:
                log("AI 回复为空，跳过")
                continue
            reply = " ".join(reply.split())
            unique, why = self.name_is_unique(chat, name)
            if not unique:
                log("拒绝发送（名字不唯一）chat=%s name=%s 原因=%s" % (chat, name, why))
                continue
            if not bool(self.cfg.get("send_enabled", True)):
                # 安全模式（默认给新装的人开）：只生成、只记日志，不往微信里发
                log("安全模式·只生成不发送 chat=%s name=%s reply=%s" % (chat, name, reply[:40]))
                continue
            self.sent_texts["%s|%s" % (chat, "".join(reply.split()))] = time.time()
            self.recent_sent.setdefault(chat, []).append((time.time(), reply))
            self.recent_sent[chat] = self.recent_sent[chat][-5:]
            log("发送 chat=%s name=%s 唯一性=%s reply=%s" % (chat, name, why, reply[:40]))
            res = wxsend.send_to(name, reply)
            self.last_sent[chat] = time.time()
            if res["ok"]:
                if self.confirm_sent(chat, reply):
                    log("发送成功并已回读确认 name=%s" % name)
                else:
                    log("已发送但回读未确认 name=%s reply=%s（请人工核对）" % (name, reply[:30]))
            else:
                log("发送失败 stage=%s note=%s" % (res["stage"], res["note"]))


def main() -> int:
    if os.path.exists(LOCK):
        try:
            pid = int(open(LOCK, encoding="utf-8").read().strip())
            import ctypes
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x1000, False, int(pid))
            alive = False
            if h:
                try:
                    code = ctypes.c_ulong(0)
                    alive = bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
                finally:
                    k32.CloseHandle(h)
            if alive:
                log("已有实例运行 PID=%d" % pid)
                return 0
        except Exception:
            pass
    open(LOCK, "w", encoding="utf-8").write(str(os.getpid()))
    try:
        return Bot().run()
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
