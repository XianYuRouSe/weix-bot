#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""控制面板（原生窗口版）。

- 白名单：输入关键字实时搜索，点选加入，存的是 wxid
- 作息：闹钟式设置上下班、睡眠、节假日
- 画像：每人独立设置 性别 / 情商 / 温度 / 关系 / 语气（档位自动套用长度、习惯、禁忌）
"""
from __future__ import annotations

import ctypes
import datetime
import json
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths
import schedule as sched
import evolve
import webui as core

BASE = paths.ROOT

# ---------------------------------------------------------------- 配色
BG = "#0d1016"
CARD = "#161a22"
CARD_HI = "#1c2129"
LINE = "#262c38"
FG = "#e8ebf2"
DIM = "#8b94a6"
FAINT = "#5b6478"
ACCENT = "#4b8bf5"
ACCENT_HI = "#6ba1ff"
OK = "#2ec27e"
BAD = "#e5484d"
BAD_HI = "#f2666b"

TITLE = ("Microsoft YaHei UI", 15, "bold")
FONT = ("Microsoft YaHei UI", 10)
FONT_S = ("Microsoft YaHei UI", 9)
MONO = ("Consolas", 9)

PANEL_LOCK = os.path.join(BASE, "logs", "panel.lock")

GENDER_ITEMS = ["未知", "男", "女"]
EQ_ITEMS = ["1 · 最直，几乎不照顾情绪", "2 · 偏理性", "3 · 正常",
            "4 · 会照顾情绪", "5 · 很会共情"]

RELATION_TIERS = {
    "女朋友": {"length": "一两句，会哄会接话",
               "habits": ["称呼亲昵", "会撒娇或接梗", "她说累就先心疼"],
               "taboos": ["不冷场", "不敷衍", "不评价她的朋友"]},
    "男朋友": {"length": "几个字到一两句",
               "habits": ["说话随意", "会打趣", "少用客套词"],
               "taboos": ["不矫情", "不翻旧账"]},
    "妻子": {"length": "一两句，会商量",
             "habits": ["说事之前先应一声", "家里的事一起商量"],
             "taboos": ["不冷暴力", "不敷衍", "不擅自决定"]},
    "丈夫": {"length": "一两句，会商量",
             "habits": ["回话干脆", "有事直接说"],
             "taboos": ["不冷暴力", "不敷衍"]},
    "暧昧对象": {"length": "几个字，留点余地",
                 "habits": ["不主动追问", "偶尔接个梗", "不秒回也不冷落"],
                 "taboos": ["不越界", "不承诺", "不表白"]},
    "父母": {"length": "一两句，报平安",
             "habits": ["说挺好的", "问他们身体", "不顶嘴"],
             "taboos": ["不让他们担心", "不顶撞", "不报忧太多"]},
    "兄弟姐妹": {"length": "几个字到一两句",
                 "habits": ["互相打趣", "说话随意"],
                 "taboos": ["不客气", "不见外"]},
    "子女": {"length": "一两句，耐心",
             "habits": ["多问一句", "语气放缓"],
             "taboos": ["不急躁", "不说教"]},
    "亲戚": {"length": "一两句，客气",
             "habits": ["带称呼", "多应声"],
             "taboos": ["不打探隐私", "不评价"]},
    "长辈": {"length": "一两句，客气",
             "habits": ["带称呼", "先应声再说话"],
             "taboos": ["不顶嘴", "不敷衍"]},
    "发小": {"length": "几个字，随便说",
             "habits": ["爱互损", "省略主语", "说话不过脑"],
             "taboos": ["不客套", "不端着"]},
    "好朋友": {"length": "几个字到一两句",
               "habits": ["爱打趣", "省略主语", "常用语气词"],
               "taboos": ["不客套", "不端着"]},
    "同学": {"length": "几个字到一两句",
             "habits": ["说话随意", "会聊近况"],
             "taboos": ["不攀比", "不打听收入"]},
    "室友": {"length": "几个字，直接说",
             "habits": ["有话直说", "说事不说人"],
             "taboos": ["不阴阳怪气", "不翻旧账"]},
    "普通朋友": {"length": "几个字",
                 "habits": ["简短回应", "少用标点"],
                 "taboos": ["不主动展开话题", "不聊太深"]},
    "网友": {"length": "几个字",
             "habits": ["简短回复", "不透露真实信息"],
             "taboos": ["不透露隐私", "不承诺见面"]},
    "领导": {"length": "一两句，简洁明确",
             "habits": ["先回收到", "说结论再说过程"],
             "taboos": ["不讨价还价", "不抱怨", "不越级"]},
    "同事": {"length": "一两句，说清楚",
             "habits": ["句子说完整", "少用表情"],
             "taboos": ["不聊私事", "不打听工资"]},
    "下属": {"length": "一两句，说清要求",
             "habits": ["讲清楚要什么", "给出明确说法"],
             "taboos": ["不模糊", "不情绪化"]},
    "客户": {"length": "一两句，礼貌",
             "habits": ["用敬语", "复述确认信息"],
             "taboos": ["不承诺时间", "不闲聊"]},
    "合作伙伴": {"length": "一两句，专业",
                 "habits": ["说结论", "留出确认空间"],
                 "taboos": ["不口头承诺", "不谈私事"]},
    "服务人员": {"length": "几个字，礼貌",
                 "habits": ["说谢谢", "说清楚需求"],
                 "taboos": ["不催促", "不苛责"]},
    "陌生人": {"length": "几个字，克制",
               "habits": ["只回必要的话", "不透露信息"],
               "taboos": ["不加好友", "不透露隐私", "不承诺"]},
}

TONE_TIERS = {
    "温柔关心": {"length": "一两句，带一句关心", "habits": ["先问一句怎么了", "说他辛苦了"]},
    "随意打趣": {"length": "几个字，带点梗", "habits": ["爱接梗", "口语化"]},
    "简短敷衍": {"length": "几个字", "habits": ["常用“在的”“嗯嗯”", "少用标点"]},
    "客气正式": {"length": "一两句，句子完整", "habits": ["用“好的”“您”", "不打错别字"]},
    "热络健谈": {"length": "两三句", "habits": ["主动追问", "多用语气词"]},
    "克制有分寸": {"length": "几个字到一句", "habits": ["不追问", "只回必要的话"]},
}

EQ_TWEAKS = {
    1: {"habits": ["不追问对方感受"]},
    2: {"habits": ["只给结论不安慰"]},
    3: {},
    4: {"habits": ["先回应情绪再说事"]},
    5: {"habits": ["先接情绪再给回应", "关心要具体"]},
}


def is_wxid(s: str) -> bool:
    s = (s or "").strip()
    return s.startswith("wxid_") or s.startswith("gh_") or s.endswith("@chatroom")


def _alive(pid: int) -> bool:
    if not pid:
        return False
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong(0)
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == 259
    finally:
        k32.CloseHandle(h)


def focus_existing() -> bool:
    try:
        with open(PANEL_LOCK, encoding="utf-8") as f:
            pid = int(f.read().strip() or 0)
    except Exception:
        return False
    if not _alive(pid):
        return False
    u = ctypes.windll.user32
    h = u.FindWindowW(None, "微信回复机器人")
    if h:
        u.ShowWindow(h, 9)
        u.SetForegroundWindow(h)
    return True


def setup_style(root: tk.Tk) -> None:
    st = ttk.Style()
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=BG)

    st.configure(".", background=BG, foreground=FG, font=FONT, borderwidth=0)
    st.configure("TFrame", background=CARD)
    st.configure("Bg.TFrame", background=BG)
    st.configure("TLabel", background=CARD, foreground=FG, font=FONT)
    st.configure("Dim.TLabel", background=CARD, foreground=DIM, font=FONT_S)
    st.configure("Faint.TLabel", background=CARD, foreground=FAINT, font=FONT_S)
    st.configure("Head.TLabel", background=BG, foreground=FG, font=TITLE)
    st.configure("Sub.TLabel", background=BG, foreground=DIM, font=FONT_S)
    st.configure("Now.TLabel", background=CARD, foreground=FG,
                 font=("Microsoft YaHei UI", 12, "bold"))

    # 按钮三种
    for name, bg, fg, hi in (
            ("Primary.TButton", ACCENT, "#ffffff", ACCENT_HI),
            ("Danger.TButton", BAD, "#ffffff", BAD_HI),
            ("Ghost.TButton", "#242b37", FG, "#2f3846")):
        st.configure(name, background=bg, foreground=fg, font=FONT_S,
                     padding=(16, 7), relief="flat", borderwidth=0, focusthickness=0)
        st.map(name, background=[("active", hi), ("pressed", hi)],
               foreground=[("disabled", FAINT)],
               relief=[("pressed", "flat")])

    st.configure("TEntry", fieldbackground="#0b0e14", foreground=FG,
                 insertcolor=FG, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                 padding=6)
    st.map("TEntry", bordercolor=[("focus", ACCENT)])
    st.configure("TSpinbox", fieldbackground="#0b0e14", foreground=FG,
                 arrowcolor=DIM, bordercolor=LINE, padding=4)
    st.configure("TCombobox", fieldbackground="#0b0e14", background="#0b0e14",
                 foreground=FG, arrowcolor=DIM, bordercolor=LINE, padding=5)
    st.map("TCombobox", fieldbackground=[("readonly", "#0b0e14")],
           foreground=[("readonly", FG)])
    # 复选框：Tk 默认用「×」，这里换成自己画的方框 + 对勾
    def _check_img(checked: bool):
        size = 16
        img = tk.PhotoImage(width=size, height=size)
        img.put("#0b0e14", to=(0, 0, size, size))
        edge = ACCENT if checked else "#3d4759"
        for i in range(size):
            img.put(edge, to=(i, 0, i + 1, 1))
            img.put(edge, to=(i, size - 1, i + 1, size))
            img.put(edge, to=(0, i, 1, i + 1))
            img.put(edge, to=(size - 1, i, size, i + 1))
        if checked:
            img.put("#1a2a45", to=(1, 1, size - 1, size - 1))
            for x, y in ((4, 8), (5, 8), (5, 9), (6, 9), (6, 10), (7, 10),
                         (8, 9), (8, 8), (9, 8), (9, 7), (10, 7), (10, 6),
                         (11, 6), (11, 5)):
                img.put(ACCENT_HI, to=(x, y, x + 2, y + 2))
        return img

    root._chk_off = _check_img(False)
    root._chk_on = _check_img(True)
    # 用独立元素名，内置的 Checkbutton.indicator 不能覆盖
    st.element_create("Chk.ind", "image", root._chk_off,
                      ("selected", root._chk_on), padding=1, sticky="")
    st.layout("TCheckbutton", [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("Chk.ind", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})])

    st.configure("TCheckbutton", background=CARD, foreground=FG, font=FONT_S,
                 focuscolor=CARD)

    for orient in ("Vertical", "Horizontal"):
        st.configure("%s.TScrollbar" % orient, gripcount=0, arrowsize=0,
                     background="#2b3240", troughcolor="#0f131a",
                     bordercolor="#0f131a", darkcolor="#2b3240", lightcolor="#2b3240",
                     arrowcolor=DIM, borderwidth=0, relief="flat", width=10)
        st.map("%s.TScrollbar" % orient,
               background=[("active", "#3a4353"), ("pressed", "#44506a")],
               troughcolor=[("active", "#0f131a")])

    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    st.configure("TNotebook.Tab", background="#141821", foreground=DIM,
                 padding=(20, 9), font=FONT, borderwidth=0)
    st.map("TNotebook.Tab",
           background=[("selected", CARD)],
           foreground=[("selected", FG)],
           expand=[("selected", (0, 0, 0, 0))])


class Panel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("微信回复机器人")
        root.geometry("1140x920")
        root.minsize(1040, 800)
        setup_style(root)

        self.wl_selected: dict[str, str] = {}
        self._cand_items: list[dict] = []
        self._search_job = None
        self._db = None
        self._profiles: dict = {}
        self._people: list[str] = []
        self._busy = False
        self._last_log_size = -1
        self._now = datetime.datetime.now()

        self._build_header()
        self._build_statusbar()
        self._build_tabs()
        self.tick_status()
        self.tick_log()

    # ------------------------------------------------------------ 通用
    def _btn(self, parent, text, cmd, kind="ghost", width=None):
        b = ttk.Button(parent, text=text, command=cmd, style=kind + ".TButton")
        if width:
            b.configure(width=width)
        return b

    def _card(self, parent, title=None):
        """返回卡片内部的容器。"""
        wrap = tk.Frame(parent, bg=LINE)          # 1px 描边
        wrap.pack(fill="x", padx=0, pady=(0, 12))
        inner = tk.Frame(wrap, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        if title:
            tk.Label(inner, text=title, bg=CARD, fg=ACCENT,
                     font=("Microsoft YaHei UI", 9, "bold")).pack(
                anchor="w", padx=16, pady=(12, 6))
        return inner

    def _label(self, parent, text, kind="Dim.TLabel"):
        return ttk.Label(parent, text=text, style=kind)

    # ------------------------------------------------------------ 顶部
    def _build_header(self) -> None:
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=22, pady=(18, 10))

        left = tk.Frame(bar, bg=BG)
        left.pack(side="left")
        ttk.Label(left, text="微信回复机器人", style="Head.TLabel").pack(anchor="w")
        ttk.Label(left, text="自动回复 · 按人设语气 · 作息感知",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        right = tk.Frame(bar, bg=BG)
        right.pack(side="right")
        self._btn(right, "停止", lambda: self.do("stop"), "Danger").pack(side="right", padx=(8, 0))
        self._btn(right, "启动", lambda: self.do("start"), "Primary").pack(side="right", padx=(8, 0))
        self._btn(right, "重启", lambda: self.do("restart")).pack(side="right")

        info = tk.Frame(bar, bg=BG)
        info.pack(side="right", padx=(0, 18))
        self.dot = tk.Canvas(info, width=14, height=14, bg=BG, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 8))
        self._dot_id = self.dot.create_oval(3, 3, 12, 12, fill=BAD, outline="")
        self.lbl_state = tk.Label(info, text="检测中…", bg=BG, fg=FG,
                                  font=("Microsoft YaHei UI", 11, "bold"))
        self.lbl_state.pack(side="left")
        self.lbl_pid = tk.Label(info, text="", bg=BG, fg=FAINT, font=FONT_S)
        self.lbl_pid.pack(side="left", padx=10)
        self.lbl_sched = tk.Label(info, text="", bg=CARD_HI, fg=DIM, font=FONT_S,
                                  padx=10, pady=2)
        self.lbl_sched.pack(side="left")

    def _build_statusbar(self) -> None:
        wrap = tk.Frame(self.root, bg=LINE)
        wrap.pack(side="bottom", fill="x")
        self.status = tk.Label(wrap, text="就绪", bg=BG, fg=DIM, font=FONT_S,
                               anchor="w", padx=22, pady=7)
        self.status.pack(fill="x", padx=1, pady=(1, 0))

    def _build_tabs(self) -> None:
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        self._tab_params()
        self._tab_schedule()
        self._tab_profiles()
        self._tab_logs()

    # ------------------------------------------------------------ 小部件
    def _scroll_text(self, parent, height, mono=True):
        frame = tk.Frame(parent, bg="#0b0e14", highlightbackground=LINE,
                         highlightthickness=1)
        txt = tk.Text(frame, height=height, bg="#0b0e14", fg=FG, insertbackground=FG,
                      relief="flat", font=MONO if mono else FONT, wrap="word",
                      padx=10, pady=8, selectbackground="#2a3446",
                      selectforeground="#ffffff", highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return frame, txt

    def _listbox(self, parent, height):
        frame = tk.Frame(parent, bg="#0b0e14", highlightbackground=LINE,
                         highlightthickness=1)
        lb = tk.Listbox(frame, height=height, bg="#0b0e14", fg=FG, relief="flat",
                        font=FONT, activestyle="none", selectbackground="#2a3446",
                        selectforeground="#ffffff", highlightthickness=0,
                        borderwidth=0, exportselection=False)
        sb = ttk.Scrollbar(frame, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True, pady=2)
        sb.pack(side="right", fill="y")
        return frame, lb

    def _scrollable(self, parent):
        """返回 (外层容器, 可滚动内容帧)。滚轮只在鼠标进入时绑定。"""
        outer = tk.Frame(parent, bg=CARD)
        canvas = tk.Canvas(outer, bg=CARD, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=CARD)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        outer.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", on_wheel))
        outer.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return outer, inner

    # ------------------------------------------------------------ 参数页
    def _tab_params(self) -> None:
        tab = tk.Frame(self.nb, bg=CARD)
        self.nb.add(tab, text="   参数   ")

        outer, body = self._scrollable(tab)
        outer.pack(fill="both", expand=True, padx=18, pady=(16, 6))

        box = self._card(body, "发送开关")
        self.var_send_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="允许真实发送（关掉 = 安全模式：只生成回复并写日志，不往微信里发）",
                        variable=self.var_send_enabled).pack(anchor="w", padx=16, pady=(0, 6))
        self.var_log_content = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="日志记录聊天正文（关掉 = 只记字数，日志可以放心贴到 issue 里）",
                        variable=self.var_log_content).pack(anchor="w", padx=16, pady=(0, 14))

        box = self._card(body, "节奏")
        g = tk.Frame(box, bg=CARD)
        g.pack(fill="x", padx=16, pady=(0, 14))
        self._field(g, "合并等待（秒）", "debounce_seconds", 0)
        self._field(g, "同会话最小间隔（秒）", "min_reply_interval", 1)
        self._field(g, "消息最大时效（秒）", "max_message_age_seconds", 2)

        box = self._card(body, "模型")
        g = tk.Frame(box, bg=CARD)
        g.pack(fill="x", padx=16, pady=(0, 14))
        self._field(g, "对话模型", "model", 0, 18)
        self._field(g, "温度（全局默认）", "temperature", 1, 8)
        self._field(g, "视觉模型", "vision_model", 2, 18)

        box = self._card(body, "白名单")
        tk.Label(box, text="输入名字或 wxid 片段，从搜索结果里点选加入",
                 bg=CARD, fg=FAINT, font=FONT_S).pack(anchor="w", padx=16)
        srow = tk.Frame(box, bg=CARD)
        srow.pack(fill="x", padx=16, pady=(8, 6))
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *a: self._schedule_search())
        self.ent_search = ttk.Entry(srow, textvariable=self.var_search)
        self.ent_search.pack(side="left", fill="x", expand=True)
        self._btn(srow, "加入", self.add_selected, "Primary").pack(side="left", padx=(8, 0))

        f1, self.lb_candidates = self._listbox(box, 3)
        f1.pack(fill="x", padx=16)
        self.lb_candidates.bind("<Double-Button-1>", lambda e: self.add_selected())

        self.lbl_selected = tk.Label(box, text="已加入（0 人，双击可移除）", bg=CARD,
                                     fg=FAINT, font=FONT_S)
        self.lbl_selected.pack(anchor="w", padx=16, pady=(10, 4))
        fsel, self.lb_selected = self._listbox(box, 3)
        fsel.pack(fill="x", padx=16)
        self.lb_selected.bind("<Double-Button-1>", lambda e: self.remove_selected())
        brow = tk.Frame(box, bg=CARD)
        brow.pack(fill="x", padx=16, pady=(8, 14))
        self._btn(brow, "移除所选", self.remove_selected).pack(side="left")

        box = self._card(body, "全局人设")
        self.lbl_persona_hint = tk.Label(
            box, text="", bg=CARD, fg="#f0b429", font=FONT_S,
            anchor="w", justify="left", wraplength=760)
        self.lbl_persona_hint.pack(anchor="w", padx=16, pady=(8, 4))
        f2, self.txt_persona = self._scroll_text(box, 6, mono=True)
        f2.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        bar = tk.Frame(tab, bg=CARD)
        bar.pack(fill="x", padx=18, pady=(0, 14))
        self._btn(bar, "保存参数", self.save_params, "Primary").pack(side="left")
        self._btn(bar, "清理缓存", self.clean_cache).pack(side="left", padx=10)
        tk.Label(bar, text="保存后几秒内自动生效", bg=CARD, fg=FAINT,
                 font=FONT_S).pack(side="left", padx=6)

    def _field(self, parent, label, key, col, width=14):
        cell = tk.Frame(parent, bg=CARD)
        cell.pack(side="left", padx=(0, 20))
        tk.Label(cell, text=label, bg=CARD, fg=DIM, font=FONT_S).pack(anchor="w")
        var = tk.StringVar()
        ttk.Entry(cell, textvariable=var, width=width).pack(pady=(4, 0))
        setattr(self, "var_" + key, var)

    # ------------------------------------------------------------ 作息页
    def _num_entry(self, parent, var, width=3, lo=0, hi=59, maxlen=2):
        """无箭头的数字输入：只允许数字，自动限长。"""
        ent = ttk.Entry(parent, textvariable=var, width=width, justify="center")
        ent.configure(font=("Consolas", 11))

        def _filter(*_a):
            s = var.get()
            cleaned = "".join(ch for ch in s if ch.isdigit())
            if len(cleaned) > maxlen:
                cleaned = cleaned[:maxlen]
            if cleaned != s:
                var.set(cleaned)
                return
            if cleaned and int(cleaned) > hi:
                var.set(str(hi))

        var.trace_add("write", _filter)
        ent.bind("<FocusOut>", lambda e: var.set(
            "%0*d" % (maxlen, max(lo, min(hi, int(var.get() or 0))))))
        return ent

    def _spin_time(self, parent, label, hh, mm):
        cell = tk.Frame(parent, bg=CARD)
        cell.pack(side="left", padx=(0, 22))
        tk.Label(cell, text=label, bg=CARD, fg=DIM, font=FONT_S).pack(anchor="w")
        row = tk.Frame(cell, bg=CARD)
        row.pack(pady=(4, 0))
        vh, vm = tk.StringVar(value=hh), tk.StringVar(value=mm)
        self._num_entry(row, vh, hi=23).pack(side="left", ipady=3)
        tk.Label(row, text=":", bg=CARD, fg=FAINT,
                 font=("Consolas", 12, "bold")).pack(side="left", padx=4)
        self._num_entry(row, vm, hi=59).pack(side="left", ipady=3)
        return vh, vm

    def _tab_schedule(self) -> None:
        tab = tk.Frame(self.nb, bg=CARD)
        self.nb.add(tab, text="   作息   ")

        outer, body = self._scrollable(tab)
        outer.pack(fill="both", expand=True, padx=18, pady=(16, 6))

        box = self._card(body)
        self.lbl_now = tk.Label(box, text="当前状态：—", bg=CARD, fg=FG,
                                font=("Microsoft YaHei UI", 12, "bold"))
        self.lbl_now.pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(box, text="机器人会按下面的时段调整说话状态；睡眠时段完全不回复",
                 bg=CARD, fg=FAINT, font=FONT_S).pack(anchor="w", padx=16, pady=(0, 14))

        box = self._card(body, "时间")
        r1 = tk.Frame(box, bg=CARD)
        r1.pack(fill="x", padx=16, pady=(0, 10))
        self.sp_start = self._spin_time(r1, "上班", "08", "30")
        self.sp_end = self._spin_time(r1, "下班", "18", "00")
        self.var_commute = tk.StringVar(value="30")
        cell = tk.Frame(r1, bg=CARD)
        cell.pack(side="left")
        tk.Label(cell, text="通勤（分钟）", bg=CARD, fg=DIM, font=FONT_S).pack(anchor="w")
        self._num_entry(cell, self.var_commute, width=5, hi=180,
                        maxlen=3).pack(pady=(4, 0), ipady=3)

        cell2 = tk.Frame(r1, bg=CARD)
        cell2.pack(side="left", padx=(20, 0))
        tk.Label(cell2, text="睡前提醒（分钟）", bg=CARD, fg=DIM,
                 font=FONT_S).pack(anchor="w")
        self.var_sleepy = tk.StringVar(value="30")
        self._num_entry(cell2, self.var_sleepy, width=5, hi=120,
                        maxlen=3).pack(pady=(4, 0), ipady=3)

        r2 = tk.Frame(box, bg=CARD)
        r2.pack(fill="x", padx=16, pady=(0, 10))
        self.sp_w_sleep = self._spin_time(r2, "上班日 睡", "01", "00")
        self.sp_w_wake = self._spin_time(r2, "上班日 起", "07", "30")

        r3 = tk.Frame(box, bg=CARD)
        r3.pack(fill="x", padx=16, pady=(0, 10))
        self.sp_r_sleep = self._spin_time(r3, "休息日 睡", "03", "00")
        self.sp_r_wake = self._spin_time(r3, "休息日 起", "12", "00")

        r4 = tk.Frame(box, bg=CARD)
        r4.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(r4, text="休息日", bg=CARD, fg=DIM, font=FONT_S).pack(side="left", padx=(0, 12))
        self.day_vars = {}
        for i, name in enumerate(sched.WEEKDAY_CN):
            v = tk.BooleanVar(value=i in (5, 6))
            self.day_vars[i] = v
            ttk.Checkbutton(r4, text=name.replace("周", ""), variable=v).pack(
                side="left", padx=(0, 12))

        box = self._card(body, "法定节假日")
        hr = tk.Frame(box, bg=CARD)
        hr.pack(fill="x", padx=16, pady=(0, 6))
        self._btn(hr, "自动获取", self.fetch_holidays, "Primary").pack(side="left")
        self.lbl_holiday = tk.Label(hr, text="", bg=CARD, fg=FAINT, font=FONT_S)
        self.lbl_holiday.pack(side="left", padx=12)

        f1, self.txt_holidays = self._scroll_text(box, 7, mono=True)
        f1.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        tk.Label(box, text="调休上班日（优先级最高）", bg=CARD, fg=DIM,
                 font=FONT_S).pack(anchor="w", padx=16)
        f2, self.txt_workdays = self._scroll_text(box, 3, mono=True)
        f2.pack(fill="x", padx=16, pady=(4, 14))

        bar = tk.Frame(tab, bg=CARD)
        bar.pack(fill="x", padx=18, pady=(0, 14))
        self._btn(bar, "保存作息", self.save_schedule, "Primary").pack(side="left")
        tk.Label(bar, text="改完几秒内生效", bg=CARD, fg=FAINT,
                 font=FONT_S).pack(side="left", padx=12)

    # ------------------------------------------------------------ 画像页
    def _tab_profiles(self) -> None:
        tab = tk.Frame(self.nb, bg=CARD)
        self.nb.add(tab, text="   按人画像   ")

        left = tk.Frame(tab, bg=CARD)
        left.pack(side="left", fill="y", padx=(18, 14), pady=(16, 14))
        tk.Label(left, text="联系人", bg=CARD, fg=ACCENT,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(0, 6))
        f, self.lb_people = self._listbox(left, 20)
        f.configure(width=200)
        f.pack(fill="y", expand=True)
        self.lb_people.configure(width=20)
        self.lb_people.bind("<<ListboxSelect>>", lambda e: self.load_person())

        right = tk.Frame(tab, bg=CARD)
        right.pack(side="left", fill="both", expand=True, padx=(0, 18), pady=(16, 14))

        outer, body = self._scrollable(right)
        outer.pack(fill="both", expand=True)

        self._build_relation_card(body)

        box = self._card(body, "基本")
        r1 = tk.Frame(box, bg=CARD)
        r1.pack(fill="x", padx=16, pady=(0, 14))
        for label, var_name, values, width in (
                ("性别", "var_gender", GENDER_ITEMS, 6),
                ("情商", "var_eq", EQ_ITEMS, 20)):
            cell = tk.Frame(r1, bg=CARD)
            cell.pack(side="left", padx=(0, 20))
            tk.Label(cell, text=label, bg=CARD, fg=DIM, font=FONT_S).pack(anchor="w")
            v = tk.StringVar(value=values[0])
            combo = ttk.Combobox(cell, textvariable=v, values=values,
                                 state="readonly", width=width)
            combo.pack(pady=(4, 0))
            setattr(self, var_name, v)
            if var_name == "var_eq":
                combo.bind("<<ComboboxSelected>>", lambda e: self.apply_tiers())

        cell = tk.Frame(r1, bg=CARD)
        cell.pack(side="left")
        tk.Label(cell, text="温度", bg=CARD, fg=DIM, font=FONT_S).pack(anchor="w")
        self.var_temp = tk.StringVar()
        ttk.Entry(cell, textvariable=self.var_temp, width=6).pack(pady=(4, 0))
        tk.Label(cell, text="留空=全局 · 上限 1.5", bg=CARD, fg=FAINT,
                 font=FONT_S).pack(anchor="w")

        box = self._card(body, "关系与语气")
        r2 = tk.Frame(box, bg=CARD)
        r2.pack(fill="x", padx=16)
        cell = tk.Frame(r2, bg=CARD)
        cell.pack(side="left", padx=(0, 20))
        tk.Label(cell, text="关系", bg=CARD, fg=DIM, font=FONT_S).pack(anchor="w")
        self.var_relation = tk.StringVar()
        self.cmb_rel = ttk.Combobox(cell, textvariable=self.var_relation,
                                    values=list(RELATION_TIERS), state="readonly",
                                    width=12)
        self.cmb_rel.pack(pady=(4, 0))
        self.cmb_rel.bind("<<ComboboxSelected>>", lambda e: self.apply_tiers())

        tk.Label(box, text="语气（可多选，叠加生效）", bg=CARD, fg=DIM,
                 font=FONT_S).pack(anchor="w", padx=16, pady=(12, 4))
        tf = tk.Frame(box, bg=CARD)
        tf.pack(fill="x", padx=16)
        self.tone_vars: dict[str, tk.BooleanVar] = {}
        for i, name in enumerate(TONE_TIERS):
            v = tk.BooleanVar(value=False)
            self.tone_vars[name] = v
            ttk.Checkbutton(tf, text=name, variable=v,
                            command=self.apply_tiers).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 18), pady=3)

        r2b = tk.Frame(box, bg=CARD)
        r2b.pack(fill="x", padx=16, pady=(10, 14))
        self.var_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(r2b, text="改档位时自动套用（覆盖长度/习惯/禁忌）",
                        variable=self.var_auto).pack(side="left")
        self._btn(r2b, "重新套用档位",
                  lambda: self.apply_tiers(force=True)).pack(side="left", padx=12)
        self.var_auto_style = tk.BooleanVar(value=True)
        ttk.Checkbutton(r2b, text="允许每天自动更新语气/习惯",
                        variable=self.var_auto_style).pack(side="left", padx=(24, 0))

        box = self._card(body, "细节")
        r3 = tk.Frame(box, bg=CARD)
        r3.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(r3, text="长度", bg=CARD, fg=DIM, font=FONT_S).pack(side="left", padx=(0, 8))
        self.var_len = tk.StringVar()
        ttk.Entry(r3, textvariable=self.var_len).pack(side="left", fill="x", expand=True)

        tk.Label(box, text="说话习惯（每行一条）", bg=CARD, fg=DIM,
                 font=FONT_S).pack(anchor="w", padx=16, pady=(2, 4))
        f1, self.txt_habits = self._scroll_text(box, 4, mono=False)
        f1.pack(fill="x", padx=16)

        tk.Label(box, text="禁忌（每行一条）", bg=CARD, fg=DIM,
                 font=FONT_S).pack(anchor="w", padx=16, pady=(10, 4))
        f2, self.txt_taboos = self._scroll_text(box, 3, mono=False)
        f2.pack(fill="x", padx=16, pady=(0, 14))

        bar = tk.Frame(right, bg=CARD)
        bar.pack(fill="x", pady=(10, 0))
        self._btn(bar, "保存此人", self.save_person, "Primary").pack(side="left")
        self._btn(bar, "按聊天记录生成本人", self.rebuild_person).pack(side="left", padx=10)
        self._btn(bar, "重新生成全部", self.rebuild_profiles).pack(side="left")

    # ------------------------------------------------------------ 关系变化卡
    def _build_relation_card(self, body) -> None:
        box = self._card(body, "关系变化（每天自动看一次）")
        self.lbl_rel = tk.Label(box, text="—", bg=CARD, fg=FG, font=FONT,
                                anchor="w", justify="left", wraplength=660)
        self.lbl_rel.pack(anchor="w", padx=16, pady=(0, 6))
        self.lbl_pend = tk.Label(box, text="", bg=CARD, fg=DIM, font=FONT_S,
                                 anchor="w", justify="left", wraplength=660)
        self.lbl_pend.pack(anchor="w", padx=16, pady=(0, 8))
        row = tk.Frame(box, bg=CARD)
        row.pack(anchor="w", padx=16, pady=(0, 12))
        self.btn_apply_rel = self._btn(row, "应用变更", self.apply_relation, "Primary")
        self.btn_apply_rel.pack(side="left")
        self.btn_ignore_rel = self._btn(row, "忽略", self.ignore_relation)
        self.btn_ignore_rel.pack(side="left", padx=10)
        self._btn(row, "立即分析此人", self.analyze_person).pack(side="left")

        tk.Label(box, text="变更历史", bg=CARD, fg=FAINT,
                 font=FONT_S).pack(anchor="w", padx=16)
        f, self.txt_rel_hist = self._scroll_text(box, 4, mono=False)
        f.pack(fill="x", padx=16, pady=(4, 14))
        self.txt_rel_hist.configure(state="disabled")

        self._cur_wxid = ""
        self._pending_shown: set = set()

    def refresh_relation(self, wxid: str, prof: dict | None = None) -> None:
        self._cur_wxid = wxid or ""
        if prof is None:
            prof = (core.read_json(core.PROFILES, {}) or {}).get(wxid, {}) or {}
        bits = ["当前关系：%s" % (prof.get("relation") or "未设置")]
        conf = prof.get("relation_confidence")
        if isinstance(conf, (int, float)) and conf:
            bits.append("置信 %.2f" % float(conf))
        since = prof.get("relation_since")
        if isinstance(since, (int, float)) and since:
            bits.append("自 %s" % datetime.datetime.fromtimestamp(since).strftime("%m-%d %H:%M"))
        last = prof.get("last_analysis_ts")
        if isinstance(last, (int, float)) and last:
            bits.append("上次分析 %s" % datetime.datetime.fromtimestamp(last).strftime("%m-%d %H:%M"))
        self.lbl_rel.configure(text=" · ".join(bits))

        pend = prof.get("pending_relation") or {}
        if pend.get("to"):
            hours = 48
            try:
                hours = int((core.read_json(core.CONFIG, {}) or {})
                            .get("evolution", {}).get("pending_hours", 48))
            except Exception:
                pass
            left = hours - (time.time() - float(pend.get("created_ts") or time.time())) / 3600
            lines = ["待确认：%s → %s（置信 %.2f）" % (
                prof.get("relation") or "—", pend.get("to"),
                float(pend.get("confidence") or 0))]
            if pend.get("why"):
                lines.append("依据：%s" % pend["why"])
            if pend.get("evidence"):
                lines.append("原话：%s" % " / ".join(pend["evidence"][:2]))
            lines.append("还剩 %.0f 小时未处理将自动应用" % max(0.0, left))
            self.lbl_pend.configure(text="\n".join(lines), fg="#f0b429")
            self.btn_apply_rel.state(["!disabled"])
            self.btn_ignore_rel.state(["!disabled"])
        else:
            self.lbl_pend.configure(text="没有待确认的变更", fg=DIM)
            self.btn_apply_rel.state(["disabled"])
            self.btn_ignore_rel.state(["disabled"])

        hist = list(prof.get("relation_history") or [])[-6:]
        self.txt_rel_hist.configure(state="normal")
        self.txt_rel_hist.delete("1.0", "end")
        if hist:
            for h in hist:
                when = datetime.datetime.fromtimestamp(int(h.get("at") or 0)).strftime("%m-%d %H:%M")
                self.txt_rel_hist.insert(
                    "end", "%s  %s → %s  %s  %s\n" % (
                        when, h.get("from") or "—", h.get("to") or "—",
                        "（面板）" if h.get("by") == "user" else "（自动）",
                        (h.get("why") or "")[:40]))
        else:
            self.txt_rel_hist.insert("end", "还没有变更记录\n")
        self.txt_rel_hist.configure(state="disabled")

    def apply_relation(self) -> None:
        if not self._cur_wxid:
            return
        res = evolve.apply_pending(self._cur_wxid)
        self.set_status(res.get("note") or "")
        self._pending_shown.clear()
        self.refresh_people()
        self.load_person()

    def ignore_relation(self) -> None:
        if not self._cur_wxid:
            return
        res = evolve.reject_pending(self._cur_wxid)
        self.set_status(res.get("note") or "")
        self._pending_shown.clear()
        self.refresh_people()
        self.load_person()

    def analyze_person(self) -> None:
        if not self._cur_wxid:
            self.set_status("先在左边选一个人")
            return
        name = (self._profiles.get(self._cur_wxid, {}) or {}).get("name") or self._cur_wxid
        self._run_async(evolve.run, self._cur_wxid, True)

    def _popup_relation(self, wxid: str, prof: dict, pend: dict) -> None:
        top = tk.Toplevel(self.root)
        self._popup_open = True
        top.title("关系变化待确认")
        top.configure(bg=CARD)
        top.attributes("-topmost", True)
        top.geometry("420x240")
        name = prof.get("name") or wxid
        tk.Label(top, text="%s 的关系可能有变化" % name, bg=CARD, fg=FG,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=18, pady=(16, 8))
        body = "%s → %s（置信 %.2f）\n%s" % (
            prof.get("relation") or "—", pend.get("to"),
            float(pend.get("confidence") or 0), pend.get("why") or "")
        if pend.get("evidence"):
            body += "\n原话：%s" % " / ".join(pend["evidence"][:2])
        tk.Label(top, text=body, bg=CARD, fg=DIM, font=FONT_S, justify="left",
                 wraplength=380).pack(anchor="w", padx=18)
        hours = 48
        try:
            hours = int((core.read_json(core.CONFIG, {}) or {})
                        .get("evolution", {}).get("pending_hours", 48))
        except Exception:
            pass
        tk.Label(top, text="%d 小时内不处理会自动应用" % hours, bg=CARD, fg=FAINT,
                 font=FONT_S).pack(anchor="w", padx=18, pady=(10, 0))

        def close():
            self._popup_open = False
            top.destroy()

        def act(apply_it: bool):
            if apply_it:
                evolve.apply_pending(wxid)
            else:
                evolve.reject_pending(wxid)
            close()
            self.refresh_people()
            if self._cur_wxid == wxid:
                self.load_person()

        bar = tk.Frame(top, bg=CARD)
        bar.pack(side="bottom", fill="x", padx=18, pady=14)
        self._btn(bar, "应用", lambda: act(True), "Primary").pack(side="left")
        self._btn(bar, "忽略", lambda: act(False)).pack(side="left", padx=10)
        self._btn(bar, "稍后", close).pack(side="right")
        top.protocol("WM_DELETE_WINDOW", close)

    def _check_pending(self) -> None:
        if getattr(self, "_popup_open", False):
            return                      # 已经弹着一个了，别叠窗
        profs = core.read_json(core.PROFILES, {}) or {}
        for wxid, prof in profs.items():
            pend = prof.get("pending_relation") or {}
            if not pend.get("to"):
                continue
            key = (wxid, pend.get("to"), pend.get("created_ts"))
            if key in self._pending_shown:
                continue
            self._pending_shown.add(key)
            self._popup_relation(wxid, prof, pend)
            break

    # ------------------------------------------------------------ 日志页
    def _tab_logs(self) -> None:
        tab = tk.Frame(self.nb, bg=CARD)
        self.nb.add(tab, text="   日志   ")
        body = tk.Frame(tab, bg=CARD)
        body.pack(fill="both", expand=True, padx=18, pady=16)
        f, self.txt_log = self._scroll_text(body, 26, mono=True)
        f.pack(fill="both", expand=True)
        self.txt_log.configure(state="disabled")

    # ------------------------------------------------------------ 白名单
    def _db_bundle(self):
        if self._db is None:
            import wcdb
            db_dir, keys = wcdb.load_keys()
            self._db = (wcdb, db_dir, keys, wcdb.PlainCache())
        return self._db

    def _schedule_search(self) -> None:
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(250, self.do_search)

    def do_search(self) -> None:
        self._search_job = None
        term = self.var_search.get().strip()
        self.lb_candidates.delete(0, "end")
        self._cand_items = []
        if not term:
            return
        try:
            wcdb, db_dir, keys, cache = self._db_bundle()
            items = wcdb.search_contacts(db_dir, keys, cache, term, limit=30)
        except Exception as exc:
            self.set_status("搜索失败: %s" % exc)
            return
        self._cand_items = items
        for it in items:
            bits = [it["display"]]
            if it["remark"] and it["nick"] and it["nick"] != it["remark"]:
                bits.append("(%s)" % it["nick"])
            if it["alias"]:
                bits.append("@" + it["alias"])
            bits.append("· " + it["wxid"])
            self.lb_candidates.insert("end", "  ".join(bits))
        self.set_status("找到 %d 个，点选后按「加入」或双击" % len(items) if items
                        else "没有找到包含「%s」的联系人" % term)

    def add_selected(self) -> None:
        sel = self.lb_candidates.curselection()
        if not sel:
            self.set_status("先在搜索结果里点一个")
            return
        it = self._cand_items[sel[0]]
        self.wl_selected[it["wxid"]] = it["display"]
        self.render_selected()
        self.set_status("已加入：%s（%s）" % (it["display"], it["wxid"]))

    def remove_selected(self) -> None:
        sel = self.lb_selected.curselection()
        if not sel:
            self.set_status("先在「已加入」里点一个")
            return
        keys = list(self.wl_selected.keys())
        wxid = keys[sel[0]]
        name = self.wl_selected.pop(wxid)
        self.render_selected()
        self.set_status("已移除：%s" % name)

    def render_selected(self) -> None:
        self.lb_selected.delete(0, "end")
        for wxid, name in self.wl_selected.items():
            if is_wxid(wxid):
                self.lb_selected.insert("end", "%s   · %s" % (name, wxid))
            else:
                self.lb_selected.insert("end", "%s（未识别）" % name)
        if hasattr(self, "lbl_selected"):
            self.lbl_selected.configure(
                text="已加入（%d 人，双击可移除）" % len(self.wl_selected))

    # ------------------------------------------------------------ 画像
    def apply_tiers(self, force: bool = False) -> None:
        if not force and not self.var_auto.get():
            return
        rel = self.var_relation.get().strip()
        tones = [n for n, v in self.tone_vars.items() if v.get()]
        length = ""
        habits: list[str] = []
        taboos: list[str] = []

        rp = RELATION_TIERS.get(rel)
        if rp:
            length = rp.get("length", "")
            habits += rp.get("habits", [])
            taboos += rp.get("taboos", [])
        for tone in tones:
            tp = TONE_TIERS.get(tone)
            if tp:
                length = length or tp.get("length", "")
                habits += tp.get("habits", [])
        try:
            eq = int(str(self.var_eq.get()).split(" ")[0])
        except (ValueError, IndexError):
            eq = 3
        eqw = EQ_TWEAKS.get(eq, {})
        habits += eqw.get("habits", [])
        if not length:
            length = eqw.get("length", "")

        seen: set[str] = set()
        habits = [h for h in habits if not (h in seen or seen.add(h))]

        if length:
            self.var_len.set(length)
        self.txt_habits.delete("1.0", "end")
        self.txt_habits.insert("end", "\n".join(habits))
        self.txt_taboos.delete("1.0", "end")
        self.txt_taboos.insert("end", "\n".join(taboos))
        self.set_status("已套用：%s / %s · 习惯 %d 条 · 禁忌 %d 条" % (
            rel or "—", "、".join(tones) or "—", len(habits), len(taboos)))

    def refresh_people(self) -> None:
        self._profiles = core.read_json(core.PROFILES, {})
        cfg = core.read_json(core.CONFIG, {})
        wl = {k: v for k, v in (cfg.get("whitelist") or {}).items() if is_wxid(k)}

        keep = None
        sel = self.lb_people.curselection()
        if sel and getattr(self, "_people", None) and sel[0] < len(self._people):
            keep = self._people[sel[0]]

        self.lb_people.delete(0, "end")
        self._people = []
        seen: set[str] = set()
        for wxid, name in wl.items():
            prof = self._profiles.get(wxid, {}) or {}
            label = prof.get("name") or name or wxid
            if not prof:
                label += "（未生成）"
            self._people.append(wxid)
            self.lb_people.insert("end", label)
            seen.add(wxid)
        for wxid, prof in self._profiles.items():
            if wxid in seen:
                continue
            self._people.append(wxid)
            self.lb_people.insert("end", prof.get("name") or wxid)

        if keep and keep in self._people:
            idx = self._people.index(keep)
            self.lb_people.selection_clear(0, "end")
            self.lb_people.selection_set(idx)
            self.lb_people.see(idx)

    def load_person(self) -> None:
        sel = self.lb_people.curselection()
        if not sel:
            return
        wxid = self._people[sel[0]]
        prof = self._profiles.get(wxid, {}) or {}
        self.var_gender.set(prof.get("gender") if prof.get("gender") in GENDER_ITEMS else "未知")
        try:
            eq = max(1, min(5, int(prof.get("eq", 3))))
        except (TypeError, ValueError):
            eq = 3
        self.var_eq.set(EQ_ITEMS[eq - 1])
        t = prof.get("temperature")
        if isinstance(t, (int, float)):
            t = max(0.0, min(1.5, float(t)))
        self.var_temp.set("" if t is None else str(t))
        self.var_relation.set(prof.get("relation") or "")
        picked = [x.strip() for x in
                  str(prof.get("my_tone") or "").replace("，", "、").split("、") if x.strip()]
        for tname, tvar in self.tone_vars.items():
            tvar.set(tname in picked)
        self.var_len.set(prof.get("my_length") or "")
        self.txt_habits.delete("1.0", "end")
        self.txt_habits.insert("end", "\n".join(prof.get("habits") or []))
        self.txt_taboos.delete("1.0", "end")
        self.txt_taboos.insert("end", "\n".join(prof.get("taboos") or []))
        self._loaded_prof = dict(prof)
        if prof:
            self.set_status("正在编辑：%s" % (prof.get("name") or wxid))
        else:
            self.set_status("这个人还没有画像，设好档位后点「保存此人」即可创建")
        try:
            self.var_auto_style.set(not prof.get("style_locked"))
        except Exception:
            pass
        self.refresh_relation(wxid, prof)

    def save_person(self) -> None:
        sel = self.lb_people.curselection()
        if not sel:
            self.set_status("先在左边选一个人")
            return
        wxid = self._people[sel[0]]
        prof = dict(self._profiles.get(wxid, {}))
        if not prof:
            cfg = core.read_json(core.CONFIG, {})
            prof["name"] = (cfg.get("whitelist") or {}).get(wxid) or wxid
        prof["gender"] = self.var_gender.get()
        try:
            prof["eq"] = int(str(self.var_eq.get()).split(" ")[0])
        except (ValueError, IndexError):
            prof["eq"] = 3
        raw_t = self.var_temp.get().strip()
        note = ""
        if raw_t:
            try:
                t_val = float(raw_t)
                capped = max(0.0, min(1.5, t_val))
                prof["temperature"] = capped
                if abs(capped - t_val) > 1e-9:
                    note = " · 温度上限 1.5，已存成 %s" % capped
                self.var_temp.set(str(capped))
            except ValueError:
                self.set_status("温度要填数字，已忽略")
                self.var_temp.set("")
        else:
            prof.pop("temperature", None)
        old_rel = str((self._profiles.get(wxid, {}) or {}).get("relation") or "")
        new_rel = self.var_relation.get().strip()
        prof["style_locked"] = not bool(self.var_auto_style.get())
        prof["my_tone"] = "、".join(n for n, v in self.tone_vars.items() if v.get())
        prof["my_length"] = self.var_len.get().strip()
        prof["habits"] = [x.strip() for x in self.txt_habits.get("1.0", "end").splitlines() if x.strip()]
        prof["taboos"] = [x.strip() for x in self.txt_taboos.get("1.0", "end").splitlines() if x.strip()]
        if new_rel and new_rel != old_rel:
            # 手动改关系也记一笔，方便以后回看是谁改的
            evolve.set_relation(prof, new_rel, "user", "面板手动修改")
            prof.pop("pending_relation", None)
            prof.pop("relation_confidence", None)
        else:
            prof["relation"] = new_rel
        try:
            # 写回前先读一遍磁盘：后台线程可能刚写过 pending_relation /
            # relation_history / analyzed_until，直接覆盖会把它们冲掉
            data = core.read_json(core.PROFILES, {}) or {}
            fresh = dict(data.get(wxid) or {})
            # 表单里没动过的字段不要覆盖——后台可能刚写过新分析结果
            loaded = getattr(self, "_loaded_prof", {}) or {}
            edited = ("name", "gender", "eq", "temperature", "my_tone",
                      "my_length", "habits", "taboos", "style_locked")
            for key in edited:
                if key not in prof:
                    continue
                if key in ("my_tone", "my_length", "habits", "taboos"):
                    if loaded.get(key) != prof[key]:
                        fresh[key] = prof[key]
                else:
                    fresh[key] = prof[key]
            if new_rel and new_rel != old_rel:
                for key in ("relation", "relation_since", "relation_history"):
                    if key in prof:
                        fresh[key] = prof[key]
                fresh.pop("pending_relation", None)
                fresh.pop("relation_confidence", None)
            data[wxid] = fresh
            self._profiles = data
            core.write_json(core.PROFILES, data)
            self.set_status("已保存 %s：%s / %s · 情商%d · 温度%s%s" % (
                prof.get("name") or wxid, prof.get("relation") or "—",
                prof.get("my_tone") or "—", prof["eq"],
                prof.get("temperature", "全局"), note))
            self.refresh_people()
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def rebuild_person(self) -> None:
        sel = self.lb_people.curselection()
        if not sel:
            self.set_status("先在左边选一个人")
            return
        wxid = self._people[sel[0]]
        name = (self._profiles.get(wxid, {}) or {}).get("name") or wxid
        if not messagebox.askyesno(
                "重新生成 %s" % name,
                "会根据他的聊天记录重新分析关系、语气、习惯，\n"
                "并覆盖你手动调过的性别/情商/温度/档位。继续？"):
            return
        self._run_async(core.run_profiles, wxid)

    def rebuild_profiles(self) -> None:
        if not messagebox.askyesno("重新生成全部",
                                   "会重新分析所有人的聊天记录，\n"
                                   "并覆盖所有手动设置。可能耗时 1 分钟，继续？"):
            return
        self._run_async(core.run_profiles)

    # ------------------------------------------------------------ 作息
    @staticmethod
    def _hm(hv, mv) -> str:
        try:
            h = max(0, min(23, int(float(str(hv.get()).strip() or 0))))
            m = max(0, min(59, int(float(str(mv.get()).strip() or 0))))
        except (TypeError, ValueError):
            return "00:00"
        return "%02d:%02d" % (h, m)

    @staticmethod
    def _split_hm(text, dh="00", dm="00"):
        try:
            h, m = str(text).split(":")
            return "%02d" % int(h), "%02d" % int(m)
        except Exception:
            return dh, dm

    def load_schedule(self, cfg: dict) -> None:
        sc = (cfg.get("schedule") or {})
        for pair, key, dh, dm in ((self.sp_start, "start", "08", "30"),
                                  (self.sp_end, "end", "18", "00")):
            hh, mm = self._split_hm(sc.get(key, dh + ":" + dm), dh, dm)
            pair[0].set(hh)
            pair[1].set(mm)
        self.var_commute.set(str(sc.get("commute_minutes", 30)))
        self.var_sleepy.set(str(sc.get("sleepy_minutes", 30)))

        def span(key, idx, dh, dm):
            val = sc.get(key) or []
            txt = val[idx] if len(val) > idx else (dh + ":" + dm)
            return self._split_hm(txt, dh, dm)

        hh, mm = span("sleep_workday", 0, "01", "00")
        self.sp_w_sleep[0].set(hh); self.sp_w_sleep[1].set(mm)
        hh, mm = span("sleep_workday", 1, "07", "30")
        self.sp_w_wake[0].set(hh); self.sp_w_wake[1].set(mm)
        hh, mm = span("sleep_rest", 0, "03", "00")
        self.sp_r_sleep[0].set(hh); self.sp_r_sleep[1].set(mm)
        hh, mm = span("sleep_rest", 1, "12", "00")
        self.sp_r_wake[0].set(hh); self.sp_r_wake[1].set(mm)

        rest = set(int(x) for x in (sc.get("rest_days") or [5, 6]))
        for i, v in self.day_vars.items():
            v.set(i in rest)

        self.txt_holidays.delete("1.0", "end")
        self.txt_holidays.insert("end", "\n".join(sc.get("holidays") or []))
        self.txt_workdays.delete("1.0", "end")
        self.txt_workdays.insert("end", "\n".join(sc.get("workdays") or []))
        self.lbl_holiday.configure(text="共 %d 天假 · %d 天调休" % (
            len(sc.get("holidays") or []), len(sc.get("workdays") or [])))

    def save_schedule(self) -> None:
        cfg = core.read_json(core.CONFIG, {})
        sc = cfg.get("schedule") or {}
        sc["start"] = self._hm(*self.sp_start)
        sc["end"] = self._hm(*self.sp_end)
        try:
            sc["commute_minutes"] = max(0, int(float(self.var_commute.get() or 0)))
        except ValueError:
            sc["commute_minutes"] = 30
        try:
            sc["sleepy_minutes"] = max(0, int(float(self.var_sleepy.get() or 0)))
        except ValueError:
            sc["sleepy_minutes"] = 30
        sc["sleep_workday"] = [self._hm(*self.sp_w_sleep), self._hm(*self.sp_w_wake)]
        sc["sleep_rest"] = [self._hm(*self.sp_r_sleep), self._hm(*self.sp_r_wake)]
        sc["rest_days"] = sorted(i for i, v in self.day_vars.items() if v.get())
        sc["holidays"] = [x.strip() for x in self.txt_holidays.get("1.0", "end").splitlines() if x.strip()]
        sc["workdays"] = [x.strip() for x in self.txt_workdays.get("1.0", "end").splitlines() if x.strip()]
        cfg["schedule"] = sc
        try:
            core.write_json(core.CONFIG, cfg)
            self.lbl_holiday.configure(text="共 %d 天假 · %d 天调休" % (
                len(sc["holidays"]), len(sc["workdays"])))
            self.set_status("作息已保存（几秒内生效）")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def fetch_holidays(self) -> None:
        import threading

        def work():
            import holidays_api
            got = {}
            for year in (self._now.year, self._now.year + 1):
                try:
                    r = holidays_api.fetch(year)
                    if r["holidays"] or r["workdays"]:
                        got[year] = r
                except Exception:
                    continue

            def apply():
                if not got:
                    self.set_status("获取失败：网络不通，或该年份还没发布")
                    return
                hs, ws = set(), set()
                for y, r in got.items():
                    hs.update(r["holidays"])
                    ws.update(r["workdays"])
                self.txt_holidays.delete("1.0", "end")
                self.txt_holidays.insert("end", "\n".join(sorted(hs)))
                self.txt_workdays.delete("1.0", "end")
                self.txt_workdays.insert("end", "\n".join(sorted(ws)))
                self.lbl_holiday.configure(
                    text="共 %d 天假 · %d 天调休（点保存生效）" % (len(hs), len(ws)))
                self.set_status("已获取 %s 的节假日，记得点保存" %
                                "、".join(str(y) for y in sorted(got)))
            self.root.after(0, apply)

        self.set_status("正在获取法定节假日…")
        threading.Thread(target=work, daemon=True).start()

    def update_now(self) -> None:
        try:
            cfg = core.read_json(core.CONFIG, {})
            state, info = sched.schedule_state(cfg)
            self.lbl_now.configure(text="当前状态：%s · %s %s" % (
                state, info["weekday"], info["time"]))
            self.lbl_sched.configure(text="%s · %s" % (state, info["time"]))
        except Exception:
            pass

    # ------------------------------------------------------------ 数据
    def load_all(self) -> None:
        cfg = core.read_json(core.CONFIG, {})
        for key in ("debounce_seconds", "min_reply_interval", "max_message_age_seconds",
                    "temperature"):
            v = cfg.get(key)
            getattr(self, "var_" + key).set("" if v is None else str(v))
        for key in ("model", "vision_model"):
            getattr(self, "var_" + key).set(str(cfg.get(key) or ""))
        try:
            self.var_send_enabled.set(bool(cfg.get("send_enabled", True)))
            self.var_log_content.set(bool(cfg.get("log_content", True)))
        except Exception:
            pass

        self.wl_selected = {}
        try:
            wcdb, db_dir, keys, cache = self._db_bundle()
            for k, v in (cfg.get("whitelist") or {}).items():
                k = str(k).strip()
                v = str(v or "").strip()
                if is_wxid(k):
                    self.wl_selected[k] = v or k
                elif k:
                    hits = wcdb.resolve_contacts(db_dir, keys, cache, k)
                    if len(hits) == 1:
                        self.wl_selected[hits[0]["wxid"]] = v or hits[0]["name"]
                    else:
                        self.wl_selected["?" + k] = (v or k) + "（未识别）"
        except Exception:
            for k, v in (cfg.get("whitelist") or {}).items():
                self.wl_selected[str(k)] = str(v or k)
        self.render_selected()

        persona_text = cfg.get("persona") or ""
        self.txt_persona.delete("1.0", "end")
        self.txt_persona.insert("end", persona_text)
        try:
            is_tpl = (not persona_text.strip()) or ("改成你自己的" in persona_text)
            self.lbl_persona_hint.configure(
                text=("还没写人设——下面还是模板，把括号里的例子换成你自己的说话方式，"
                      "否则回复会很空、很像客服" if is_tpl else ""))
        except Exception:
            pass

        try:
            self.load_schedule(cfg)
        except Exception:
            pass

        self.refresh_people()
        if self._people and not self.lb_people.curselection():
            self.lb_people.selection_set(0)
            self.load_person()

    # ------------------------------------------------------------ 动作
    def _run_async(self, fn, *args) -> None:
        if self._busy:
            return
        self._busy = True
        self.set_status("处理中…")
        self.root.update_idletasks()

        def work():
            try:
                res = fn(*args)
            except Exception as exc:
                res = {"ok": False, "note": "出错: %s" % exc}
            self.root.after(0, lambda: self._done(res))

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _done(self, res: dict) -> None:
        self._busy = False
        self.set_status((res or {}).get("note") or ("完成" if (res or {}).get("ok") else "失败"))
        self.load_all()
        # 后台刚改过画像的话，表单里还是旧值；不重载的话下次点保存会把
        # 新分析结果又写回旧值（关系一改一还原就是这么来的）
        if self.lb_people.curselection():
            self.load_person()
        self.tick_status()

    def do(self, action: str) -> None:
        if self._busy:
            return
        if action == "restart":
            def both():
                core.stop_bot()
                import time
                time.sleep(0.5)
                return core.start_bot()
            self._run_async(both)
            return
        fn = {"start": core.start_bot, "stop": core.stop_bot}.get(action)
        if fn:
            self._run_async(fn)

    def clean_cache(self) -> None:
        res = core.clean_cache()
        self.set_status(res.get("note") or "已清理")

    def save_params(self) -> None:
        cfg = core.read_json(core.CONFIG, {})

        def num(name):
            raw = getattr(self, "var_" + name).get().strip()
            if not raw:
                return None
            try:
                v = float(raw)
                return int(v) if abs(v - int(v)) < 1e-9 else v
            except ValueError:
                return None

        for key in ("debounce_seconds", "min_reply_interval", "max_message_age_seconds",
                    "temperature"):
            v = num(key)
            if v is not None:
                cfg[key] = v
        for key in ("model", "vision_model"):
            v = getattr(self, "var_" + key).get().strip()
            if v:
                cfg[key] = v

        try:
            cfg["send_enabled"] = bool(self.var_send_enabled.get())
            cfg["log_content"] = bool(self.var_log_content.get())
        except Exception:
            pass

        wl = {k: v for k, v in self.wl_selected.items() if is_wxid(k)}
        skipped = len(self.wl_selected) - len(wl)
        cfg["whitelist"] = wl
        cfg["persona"] = self.txt_persona.get("1.0", "end").rstrip()

        try:
            core.write_json(core.CONFIG, cfg)
            names = "、".join(wl.values()) if wl else "（空）"
            msg = "已保存 · 白名单：%s" % names
            if skipped:
                msg += " · 跳过 %d 个未识别项" % skipped
            self.refresh_people()
            self.set_status(msg)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    # ------------------------------------------------------------ 刷新
    def tick_status(self) -> None:
        pid = core.bot_pid()
        running = bool(pid)
        self.dot.itemconfigure(self._dot_id, fill=OK if running else BAD)
        self.lbl_state.configure(text="运行中" if running else "已停止",
                                 fg=FG if running else "#c2c8d4")
        self.lbl_pid.configure(text=("PID %d" % pid) if pid else "")
        self._now = datetime.datetime.now()
        self.update_now()
        try:
            self._check_pending()
        except Exception:
            pass
        self.root.after(2000, self.tick_status)

    def tick_log(self) -> None:
        try:
            size = os.path.getsize(core.LOG)
        except OSError:
            size = 0
        if size != self._last_log_size:
            self._last_log_size = size
            self.txt_log.configure(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.insert("end", "\n".join(core.tail_log(400)))
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        self.root.after(3000, self.tick_log)

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)


def main() -> int:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    root = tk.Tk()
    if focus_existing():
        try:
            root.destroy()
        except Exception:
            pass
        return 0
    try:
        with open(PANEL_LOCK, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    try:
        ico = os.path.join(BASE, "assets", "weix.ico")
        if os.path.isfile(ico):
            root.iconbitmap(ico)
    except Exception:
        pass

    app = Panel(root)
    app.load_all()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
