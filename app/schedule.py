#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""根据当前时间判断"我在什么状态"，让回复贴合作息。

规则（可在 config/bot.json 的 schedule 里改）：
  工作日 08:30-18:00        上班中
  工作日 08:00-08:30        通勤中（上班路上）
  工作日 18:00-18:30        通勤中（下班路上）
  工作日其余时间            在家
  休息日（周末 + 节假日）    休息
"""
from __future__ import annotations

import datetime

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

DEFAULTS = {
    "start": "08:30",
    "end": "18:00",
    "commute_minutes": 30,
    "rest_days": [5, 6],        # 0=周一 … 6=周日
    "holidays": [],             # "2026-01-01" 这种字符串
    "workdays": [],             # 调休上班日，优先于 rest_days
    # 睡眠时段：睡着期间完全不回复
    "sleep_workday": ["01:00", "07:30"],   # 上班日：1 点睡，7:30 起
    "sleep_rest": ["03:00", "12:00"],      # 休息日：3 点睡，12 点起
}


def _minutes(hhmm: str, fallback: int) -> int:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return fallback


def is_workday(cfg: dict, day: datetime.date) -> bool:
    sc = dict(DEFAULTS)
    sc.update((cfg or {}).get("schedule") or {})
    key = day.strftime("%Y-%m-%d")
    if key in {str(x) for x in (sc.get("workdays") or [])}:
        return True
    if key in {str(x) for x in (sc.get("holidays") or [])}:
        return False
    return day.weekday() not in {int(x) for x in (sc.get("rest_days") or [5, 6])}


def is_sleeping(cfg: dict, now: datetime.datetime | None = None) -> tuple[bool, dict]:
    """现在是睡眠时段吗。睡眠时段内机器人完全不回复。"""
    sc = dict(DEFAULTS)
    sc.update((cfg or {}).get("schedule") or {})
    now = now or datetime.datetime.now()
    workday = is_workday(cfg, now.date())
    span = sc.get("sleep_workday" if workday else "sleep_rest") or (
        ["01:00", "07:30"] if workday else ["03:00", "12:00"])
    start = _minutes(span[0], 60 if workday else 180)
    wake = _minutes(span[1], 450 if workday else 720)
    t = now.hour * 60 + now.minute
    info = {
        "workday": workday,
        "sleep": span[0].strip(),
        "wake": span[1].strip(),
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": WEEKDAY_CN[now.weekday()],
    }
    return (start <= t < wake), info


def presleep_state(cfg: dict, now: datetime.datetime | None = None) -> tuple[bool, dict]:
    """离睡觉还有几分钟？是否进入"困了准备睡"的提醒窗口。"""
    sc = dict(DEFAULTS)
    sc.update((cfg or {}).get("schedule") or {})
    now = now or datetime.datetime.now()
    workday = is_workday(cfg, now.date())
    span = sc.get("sleep_workday" if workday else "sleep_rest") or (
        ["01:00", "07:30"] if workday else ["03:00", "12:00"])
    start = _minutes(span[0], 60 if workday else 180)
    window = int(sc.get("sleepy_minutes", 30) or 0)
    t = now.hour * 60 + now.minute
    left = start - t
    info = {
        "minutes": left,
        "sleep_at": span[0].strip(),
        "time": now.strftime("%H:%M"),
        "weekday": WEEKDAY_CN[now.weekday()],
    }
    return (0 < left <= window), info


def sleep_window_last(cfg: dict, now: datetime.datetime | None = None):
    """最近一次已经结束的睡眠时段 (开始时间戳, 结束时间戳)。

    用来补回"睡觉期间收到的消息"。如果现在还在睡，返回 None。
    """
    now = now or datetime.datetime.now()
    sleeping, _ = is_sleeping(cfg, now)
    if sleeping:
        return None
    sc = dict(DEFAULTS)
    sc.update((cfg or {}).get("schedule") or {})
    workday = is_workday(cfg, now.date())
    span = sc.get("sleep_workday" if workday else "sleep_rest") or (
        ["01:00", "07:30"] if workday else ["03:00", "12:00"])
    start_min = _minutes(span[0], 60 if workday else 180)
    wake_min = _minutes(span[1], 450 if workday else 720)

    start = now.replace(hour=start_min // 60, minute=start_min % 60,
                        second=0, microsecond=0)
    wake = now.replace(hour=wake_min // 60, minute=wake_min % 60,
                       second=0, microsecond=0)
    if now >= wake:
        return (int(start.timestamp()), int(wake.timestamp()))
    # 还没到今天的起床点：最近一次睡完的是"昨天那一觉"，按昨天是否上班算
    prev = now - datetime.timedelta(days=1)
    wd_prev = is_workday(cfg, prev.date())
    span_prev = sc.get("sleep_workday" if wd_prev else "sleep_rest") or (
        ["01:00", "07:30"] if wd_prev else ["03:00", "12:00"])
    s_min = _minutes(span_prev[0], 60 if wd_prev else 180)
    w_min = _minutes(span_prev[1], 450 if wd_prev else 720)
    start = prev.replace(hour=s_min // 60, minute=s_min % 60, second=0, microsecond=0)
    wake = prev.replace(hour=w_min // 60, minute=w_min % 60, second=0, microsecond=0)
    return (int(start.timestamp()), int(wake.timestamp()))


def schedule_state(cfg: dict, now: datetime.datetime | None = None) -> tuple[str, dict]:
    """返回 (状态, 信息)。状态取值：上班 / 通勤 / 休息 / 在家。"""
    sc = dict(DEFAULTS)
    sc.update((cfg or {}).get("schedule") or {})
    now = now or datetime.datetime.now()

    day = now.strftime("%Y-%m-%d")
    holidays = {str(x) for x in (sc.get("holidays") or [])}
    workdays = {str(x) for x in (sc.get("workdays") or [])}
    rest_days = {int(x) for x in (sc.get("rest_days") or [5, 6])}

    is_rest = now.weekday() in rest_days or day in holidays
    if day in workdays:
        is_rest = False

    t = now.hour * 60 + now.minute
    start = _minutes(sc.get("start"), 8 * 60 + 30)
    end = _minutes(sc.get("end"), 18 * 60)
    commute = int(sc.get("commute_minutes", 30))

    info = {
        "date": day,
        "weekday": WEEKDAY_CN[now.weekday()],
        "time": now.strftime("%H:%M"),
        "is_rest": is_rest,
    }

    sleeping, _sinfo = is_sleeping(cfg, now)
    if sleeping:
        return "睡觉", info

    if is_rest:
        return "休息", info
    if start <= t < end:
        return "上班", info
    if (start - commute) <= t < start or end <= t < (end + commute):
        return "通勤", info
    return "在家", info


HINTS = {
    "睡觉": "现在是{weekday} {time}，你在睡觉。不要回消息。",
    "上班": "现在是上班时间（{weekday} {time}），你在公司。回复要短，像抽空看一眼手机；"
            "可以自然说在忙、在公司、晚点说；不要说自己很闲、不要说在睡觉、不要约人。",
    "通勤": "现在是上下班路上（{weekday} {time}），你在车上。回复简短，可以说在赶路、"
            "一会儿到了再说。",
    "休息": "今天是休息日（{weekday}），你在家休息。可以放松一点，别说得像在上班、"
            "别一本正经；依然不主动约见面。",
    "在家": "现在是{time}，你已经下班回家，说话可以放松一些。",
}


def hint_text(state: str, info: dict) -> str:
    tpl = HINTS.get(state, HINTS["在家"])
    return tpl.format(**info)
