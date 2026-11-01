#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""安装路径。

所有位置都从本文件推导，整个目录可以放在任何地方（U 盘、别的盘符、中文路径），
不再依赖任何写死的绝对路径。需要固定位置时用环境变量 WEIX_HOME 覆盖。

    WEIX_HOME=D:\\Tools\\weix   → 配置、日志、缓存都放这里
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 打包成 exe 后，配置和日志放在 exe 旁边，而不是 PyInstaller 的临时解包目录
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    ROOT = os.environ.get("WEIX_HOME") or os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.environ.get("WEIX_HOME") or os.path.dirname(HERE)

CONFIG_DIR = os.path.join(ROOT, "config")
LOG_DIR = os.path.join(ROOT, "logs")
CACHE_DIR = os.path.join(ROOT, "cache")
ASSETS_DIR = os.path.join(ROOT, "assets")
ENV_FILE = os.path.join(ROOT, ".env")

BOT_CONFIG = os.path.join(CONFIG_DIR, "bot.json")
PROFILES = os.path.join(CONFIG_DIR, "profiles.json")
ALL_KEYS = os.path.join(CONFIG_DIR, "all_keys.json")
STATE = os.path.join(LOG_DIR, "state.json")
BOT_LOG = os.path.join(LOG_DIR, "bot.log")
EVOLVE_LOG = os.path.join(LOG_DIR, "evolve.log")
BOT_LOCK = os.path.join(LOG_DIR, "bot.lock")
PANEL_LOCK = os.path.join(LOG_DIR, "panel.lock")
PLAIN_CACHE = os.path.join(CACHE_DIR, "plain")


def ensure_dirs() -> None:
    """首次运行时把目录建好。"""
    for d in (CONFIG_DIR, LOG_DIR, CACHE_DIR, PLAIN_CACHE):
        os.makedirs(d, exist_ok=True)
