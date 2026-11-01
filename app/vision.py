#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""把聊天截图交给视觉模型理解（图片消息用）。

不解析微信的加密 .dat 图片文件，而是直接截取聊天里渲染出来的图片——
这样既不需要解密，也不依赖任何第三方库。
"""
from __future__ import annotations

import base64
import json
import subprocess
import urllib.request

API = "https://api.deepseek.com/chat/completions"


def bmp_to_png(bmp_path: str) -> str:
    """用 System.Drawing 把 BMP 转成 PNG（视觉接口只认常见格式）。"""
    png = bmp_path.rsplit(".", 1)[0] + ".png"
    ps = ('Add-Type -AssemblyName System.Drawing; '
          '$i=[System.Drawing.Image]::FromFile("%s"); '
          '$i.Save("%s",[System.Drawing.Imaging.ImageFormat]::Png); $i.Dispose()'
          % (bmp_path.replace("\\", "\\\\"), png.replace("\\", "\\\\")))
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=40,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    return png


def read_transcript(png_path: str, api_key: str, model: str = "deepseek-flash") -> str:
    """读取语音气泡下方由微信「转文字」生成的文字。"""
    if not api_key:
        return ""
    try:
        enc = base64.b64encode(open(png_path, "rb").read()).decode()
    except OSError:
        return ""
    payload = {
        "model": model,
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 150,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "这是微信聊天截图。请找到最后一条语音消息气泡下方那一段由"
                    "「转文字」生成的小字，原样输出它。"
                    "只输出那段文字本身；如果没有找到，只输出 NONE。")},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + enc}},
            ],
        }],
    }
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        return ""


def describe(png_path: str, api_key: str, model: str = "deepseek-flash",
             question: str = "") -> str:
    """让视觉模型描述截图中最后一张图片的内容。"""
    if not api_key:
        return ""
    try:
        enc = base64.b64encode(open(png_path, "rb").read()).decode()
    except OSError:
        return ""
    prompt = (
        "这是一张微信聊天截图。请只看聊天内容区里最新的一条消息："
        "如果它是图片，用一两句话说明图片里有什么（人物、物体、文字、场景）；"
        "如果是文字，原样输出文字。"
        "不要描述界面、按钮、滚动条。回答控制在 60 字以内。"
    )
    if question:
        prompt += "另外请回答：" + question
    payload = {
        "model": model,
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_tokens": 200,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + enc}},
            ],
        }],
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        return ""
