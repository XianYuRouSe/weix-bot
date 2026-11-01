#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""自动获取中国法定节假日与调休上班日。

数据源：timor.tech 的公开节假日接口（按年返回每天是放假、调休还是正常）。
只读，不写任何文件；取回后由面板决定是否写入配置。
"""
from __future__ import annotations

import json
import urllib.request

import time

SOURCES = [
    "https://timor.tech/api/holiday/year/%d",
    "http://timor.tech/api/holiday/year/%d",
]


def _parse(data, year: int, url: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError("接口返回格式不对")
    table = data.get("holiday")
    if not isinstance(table, dict):
        raise ValueError("接口没有返回 holiday 字段（可能该年份还未发布）")
    holidays, workdays = [], []
    for key, item in table.items():
        if not isinstance(item, dict):
            continue
        day = str(item.get("date") or "")
        if not day:
            mm, dd = key.split("-") if "-" in key else ("01", "01")
            day = "%04d-%02d-%02d" % (int(year), int(mm), int(dd))
        if item.get("holiday"):
            holidays.append(day)
        else:
            workdays.append(day)      # holiday=false 表示调休上班
    return {"year": int(year), "holidays": sorted(set(holidays)),
            "workdays": sorted(set(workdays)), "source": url, "count": len(table)}


def fetch(year: int, timeout: int = 15, attempts: int = 2) -> dict:
    """多个源 + 重试，返回 {"year","holidays","workdays","source","count"}。"""
    errors = []
    for tpl in SOURCES:
        url = tpl % int(year)
        for i in range(attempts):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                return _parse(data, year, url)
            except Exception as exc:
                errors.append("%s -> %s: %s" % (url, type(exc).__name__, exc))
                time.sleep(1 + i)
    raise RuntimeError("获取失败：\n" + "\n".join(errors[-2:]))


def summary(res: dict) -> str:
    return "已获取 %d 年：放假 %d 天，调休上班 %d 天" % (
        res.get("year", 0), len(res.get("holidays") or []), len(res.get("workdays") or []))
