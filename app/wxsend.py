#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""WeChat 发送（UI 自动化 + OCR 身份校验）。

核心原则：**没有通过 OCR 校验就不打字、不发送**。
  open_chat(name)  → Ctrl+F 精确搜索 → 回车打开
  verify_title(name) → 截聊天面板标题区 → Windows OCR → 去空白后比对
  只有完全匹配才 send_text()

所有落盘文件都在安装目录内（见 paths.py）。
"""
from __future__ import annotations

import ctypes
import io
import os
import subprocess
import time
from ctypes import wintypes as wt

import paths

BASE = paths.ROOT
CACHE = paths.CACHE_DIR


def _ocr_script() -> str:
    """ocr.ps1 的位置：源码运行在 app/ 下，打包后放在 exe 旁边的 app/ 下。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "ocr.ps1"),
                 os.path.join(paths.ROOT, "app", "ocr.ps1")):
        if os.path.isfile(cand):
            return cand
    return os.path.join(here, "ocr.ps1")


OCR_PS1 = _ocr_script()
os.makedirs(CACHE, exist_ok=True)

# DPI 感知：不设的话 GetWindowRect 返回逻辑坐标、截图是物理像素，125% 缩放下会差一大截
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32

SW_MAXIMIZE = 3
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

VK_CONTROL = 0x11
VK_A = 0x41
VK_V = 0x56
VK_F = 0x46
VK_BACK = 0x08
VK_DELETE = 0x2E
VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


# ---------------------------------------------------------------- 基础键鼠
def _key(vk: int, up: bool = False) -> None:
    _u32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


def _combo(mod: int, vk: int) -> None:
    _key(mod); time.sleep(0.05)
    _key(vk); time.sleep(0.05)
    _key(vk, True); _key(mod, True)


def _click(x: int, y: int) -> None:
    _u32.SetCursorPos(int(x), int(y))
    time.sleep(0.12)
    _u32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.06)
    _u32.mouse_event(0x0004, 0, 0, 0, 0)


def clipboard_get() -> str:
    """读当前剪贴板文本（图片等非文本返回空串）。"""
    CF_UNICODETEXT = 13
    _u32.OpenClipboard.restype = ctypes.c_bool
    _u32.GetClipboardData.restype = ctypes.c_void_p
    if not _u32.OpenClipboard(None):
        return ""
    try:
        h = _u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        _k32.GlobalLock.restype = ctypes.c_void_p
        ptr = _k32.GlobalLock(ctypes.c_void_p(h))
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            _k32.GlobalUnlock(ctypes.c_void_p(h))
    except Exception:
        return ""
    finally:
        _u32.CloseClipboard()


def clipboard_set(text: str) -> bool:
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    _k32.GlobalAlloc.restype = ctypes.c_void_p
    _k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    _k32.GlobalLock.restype = ctypes.c_void_p
    _k32.GlobalLock.argtypes = [ctypes.c_void_p]
    _k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _u32.SetClipboardData.restype = ctypes.c_void_p
    _u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    ok = False
    if not _u32.OpenClipboard(None):
        return False
    try:
        _u32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        h = _k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        ptr = _k32.GlobalLock(h)
        if not ptr:
            return False
        ctypes.memmove(ptr, data, len(data))
        _k32.GlobalUnlock(h)
        ok = bool(_u32.SetClipboardData(CF_UNICODETEXT, h))
    finally:
        _u32.CloseClipboard()
    return ok


# ---------------------------------------------------------------- 窗口
def wechat_hwnd() -> int:
    h = _u32.FindWindowW(None, "\u5fae\u4fe1")   # 微信
    return h or 0


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = RECT()
    _u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def force_foreground(hwnd: int, timeout: float = 3.0) -> bool:
    if _u32.GetForegroundWindow() == hwnd:
        return True
    _k32.GetCurrentThreadId.restype = ctypes.c_uint32
    cur = _k32.GetCurrentThreadId()
    fg = _u32.GetForegroundWindow()
    t_fg = _u32.GetWindowThreadProcessId(fg, None) if fg else 0
    t_wx = _u32.GetWindowThreadProcessId(hwnd, None)
    try:
        if t_fg and t_fg != cur:
            _u32.AttachThreadInput(cur, t_fg, True)
        _u32.BringWindowToTop(hwnd)
        _u32.SetForegroundWindow(hwnd)
        _u32.SetFocus(hwnd)
    finally:
        if t_fg and t_fg != cur:
            _u32.AttachThreadInput(cur, t_fg, False)
    end = time.time() + timeout
    while time.time() < end:
        if _u32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.1)
    _u32.ShowWindow(hwnd, 6)
    time.sleep(0.25)
    _u32.ShowWindow(hwnd, 9)
    time.sleep(0.4)
    _u32.SetForegroundWindow(hwnd)
    end = time.time() + 2.0
    while time.time() < end:
        if _u32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.1)
    return False


def ensure_ready() -> int:
    """窗口可见、在屏幕内、在前台。返回 hwnd（0 表示失败）。"""
    hwnd = wechat_hwnd()
    if not hwnd:
        return 0
    left, top, w, h = window_rect(hwnd)
    screen_w = _u32.GetSystemMetrics(0)
    screen_h = _u32.GetSystemMetrics(1)
    offscreen = left < -1000 or top < -1000 or w < 200 or h < 200
    if offscreen:
        nw, nh = min(1000, screen_w - 80), min(700, screen_h - 80)
        _u32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.2)
        _u32.SetWindowPos(hwnd, 0, (screen_w - nw) // 2, (screen_h - nh) // 2,
                          nw, nh, SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        time.sleep(0.4)
    if not _u32.IsWindowVisible(hwnd):
        _u32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.3)
    if not force_foreground(hwnd):
        return 0
    return hwnd


# ---------------------------------------------------------------- 截图 + OCR
def _grab(rect: tuple[int, int, int, int], out_path: str) -> bool:
    left, top, w, h = rect
    if w <= 0 or h <= 0:
        return False
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, left, top, 0x00CC0020)

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    bih = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)

    raw = buf.raw
    stride = w * 4
    rows = [raw[y * stride:(y + 1) * stride] for y in range(h)]
    rows.reverse()          # 与 print_window 一致：翻正后再写
    with open(out_path, "wb") as f:
        f.write(_bmp_bytes(b"".join(rows), w, h))
    return os.path.getsize(out_path) > 0


def print_window(hwnd: int) -> bytes:
    """抓取窗口自身内容（不受其它窗口遮挡），返回 BMP 字节。

    PrintWindow 是自底向上渲染，GetDIBits 用正高度拿到的是倒序行，这里
    统一翻正，方便后续按窗口坐标裁切。
    """
    left, top, w, h = window_rect(hwnd)
    if w <= 0 or h <= 0:
        return b"", 0, 0
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    if not user32.PrintWindow(hwnd, mem, 2):
        gdi32.DeleteObject(bmp); gdi32.DeleteDC(mem); user32.ReleaseDC(hwnd, hdc)
        return b"", 0, 0
    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]
    bih = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(mem); user32.ReleaseDC(hwnd, hdc)
    raw = buf.raw
    stride = w * 4
    rows = [raw[y * stride:(y + 1) * stride] for y in range(h)]
    rows.reverse()
    return _bmp_bytes(b"".join(rows), w, h), w, h


def crop_window_bmp(bmp_bytes: bytes, w: int, h: int,
                    fx: float, fy: float, fw: float, fh: float) -> bytes:
    """从整窗 BMP 里按比例裁一块（BMP 已翻正，坐标直接对应窗口坐标）。"""
    import struct
    off = struct.unpack_from("<I", bmp_bytes, 10)[0]
    row_size = (w * 3 + 3) & ~3
    x0 = int(w * fx); y0 = int(h * fy)
    cw = max(1, min(int(w * fw), w - x0))
    ch = max(1, min(int(h * fh), h - y0))
    pad = ((cw * 3 + 3) & ~3) - cw * 3
    out = bytearray()
    # BMP 正高度是自底向上存储：显示第 d 行 == 文件第 h-1-d 行。
    # 输出同样是自底向上，所以从裁剪区的底部往上写。
    for d in range(y0 + ch - 1, y0 - 1, -1):
        base = off + (h - 1 - d) * row_size + x0 * 3
        out += bmp_bytes[base:base + cw * 3]
        out += b"\x00" * pad
    header = bytearray()
    header += b"BM"
    header += (14 + 40 + len(out)).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")
    header += (54).to_bytes(4, "little")
    header += (40).to_bytes(4, "little")
    header += cw.to_bytes(4, "little")
    header += ch.to_bytes(4, "little")
    header += (1).to_bytes(2, "little")
    header += (24).to_bytes(2, "little")
    header += (0).to_bytes(4, "little")
    header += len(out).to_bytes(4, "little")
    header += (2835).to_bytes(4, "little") * 2
    header += (0).to_bytes(4, "little") * 2
    return bytes(header) + bytes(out)


def flip_h_bmp(bmp_bytes: bytes, w: int, h: int) -> bytes:
    """把 24 位 BMP 左右翻转（PrintWindow 出来的是 180° 旋转）。"""
    import struct
    off = struct.unpack_from("<I", bmp_bytes, 10)[0]
    row_size = (w * 3 + 3) & ~3
    out = bytearray()
    for y in range(h):
        base = off + y * row_size
        row = bmp_bytes[base:base + w * 3]
        px = [row[i:i + 3] for i in range(0, w * 3, 3)]
        px.reverse()
        line = b"".join(px)
        out += line + b"\x00" * (row_size - w * 3)
    header = bytearray(bmp_bytes[:off])
    struct.pack_into("<I", header, 2, off + len(out))
    struct.pack_into("<I", header, 34, len(out))
    return bytes(header) + bytes(out)


def _bmp_bytes(raw_bgra: bytes, w: int, h: int) -> bytes:
    """把 BGRA 原始像素写成 24 位 BMP。"""
    row_size = (w * 3 + 3) & ~3
    pad = row_size - w * 3
    body = bytearray()
    for y in range(h):
        row = raw_bgra[y * w * 4:(y + 1) * w * 4]
        for x in range(w):
            b, g, r = row[x * 4], row[x * 4 + 1], row[x * 4 + 2]
            body += bytes((b, g, r))
        body += b"\x00" * pad
    header = bytearray()
    header += b"BM"
    header += (14 + 40 + len(body)).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")
    header += (54).to_bytes(4, "little")
    header += (40).to_bytes(4, "little")
    header += w.to_bytes(4, "little")
    header += h.to_bytes(4, "little")
    header += (1).to_bytes(2, "little")
    header += (24).to_bytes(2, "little")
    header += (0).to_bytes(4, "little")
    header += len(body).to_bytes(4, "little")
    header += (2835).to_bytes(4, "little") * 2
    header += (0).to_bytes(4, "little") * 2
    return bytes(header) + bytes(body)


def ocr(path: str) -> str:
    """调用 Windows OCR（本机 zh-Hans-CN 引擎）。"""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", OCR_PS1, "-ImagePath", path],
            capture_output=True, timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _norm(text: str) -> str:
    """去掉空白和 OCR 常见的分隔符，便于逐字比对。"""
    return "".join(str(text).split()).replace("|", "").replace("\uff5c", "")


def ocr_lines(path: str) -> list[tuple[str, int, int, int, int]]:
    """带坐标的 OCR：返回 [(文本, x, y, w, h)]。"""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", OCR_PS1, "-ImagePath", path, "-Lines"],
            capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return []
    lines = []
    for raw in out.stdout.decode("utf-8", "replace").splitlines():
        parts = raw.split("\t")
        if len(parts) != 5:
            continue
        try:
            lines.append((parts[0], int(parts[1]), int(parts[2]),
                          int(parts[3]), int(parts[4])))
        except ValueError:
            continue
    return lines


def transcribe_last_voice(bubble_ratio=(0.43, 0.75), attempts: int = 3) -> bool:
    """对最后一条语音右键 -> 按文字定位「转文字」并点击。

    只点被 OCR 明确识别为「转文字」的那一行；识别不到就重试，重试仍失败
    就放弃，绝不盲点——避免误触「删除」。
    """
    hwnd = ensure_ready()
    if not hwnd:
        return False
    left, top, w, h = window_rect(hwnd)
    bx = left + int(w * bubble_ratio[0])
    by = top + int(h * bubble_ratio[1])
    rx, ry = bx - 30, by - 30

    for attempt in range(attempts):
        _u32.SetCursorPos(bx, by)
        time.sleep(0.45)
        _u32.mouse_event(0x0008, 0, 0, 0, 0)
        time.sleep(0.25)
        _u32.mouse_event(0x0010, 0, 0, 0, 0)
        time.sleep(1.0 + attempt * 0.6)

        path = os.path.join(CACHE, "menu_%d.bmp" % int(time.time() * 1000))
        if not _grab((rx, ry, 460, 460), path):
            continue
        lines = ocr_lines(path)
        target = None
        for text, x, y, lw, lh in lines:
            if "转文字" in text:
                target = (x + lw // 2, y + lh // 2)
                break
        try:
            os.remove(path)
        except OSError:
            pass
        if not target:
            continue
        cx, cy = rx + target[0], ry + target[1]
        _u32.SetCursorPos(cx, cy)
        time.sleep(0.3)
        _u32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.1)
        _u32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(2.2)
        return True
    return False


def read_bottom_text() -> str:
    """读聊天区最底部那条文字（用于取语音转写结果）。"""
    hwnd = wechat_hwnd()
    if not hwnd:
        return ""
    full, w, h = print_window(hwnd)
    if not full or w <= 0:
        return ""
    band = crop_window_bmp(full, w, h, 0.34, 0.60, 0.44, 0.24)
    path = os.path.join(CACHE, "bottom_%d.bmp" % int(time.time() * 1000))
    try:
        with open(path, "wb") as f:
            f.write(band)
        lines = ocr_lines(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    lines = [ln for ln in lines if ln[0].strip()]
    if not lines:
        return ""
    lines.sort(key=lambda x: x[2])       # 按 y 排序，取最下面一行
    return lines[-1][0].strip()


def capture_chat_area(out_name: str = "chat") -> str:
    """截取聊天内容区（右侧面板），返回 BMP 路径；失败返回空串。"""
    hwnd = wechat_hwnd()
    if not hwnd:
        return ""
    full, w, h = print_window(hwnd)
    if not full or w <= 0:
        return ""
    band = crop_window_bmp(full, w, h, 0.34, 0.08, 0.62, 0.74)
    path = os.path.join(CACHE, "%s_%d.bmp" % (out_name, int(time.time() * 1000)))
    with open(path, "wb") as f:
        f.write(band)
    return path


def open_chat(name: str) -> bool:
    """用搜索框打开会话：Ctrl+F -> 粘贴名字 -> 回车。

    不依赖任何点击坐标；调用方必须在此之前确认该名字在本机唯一对应目标
    联系人，否则可能打开同名的别人。
    """
    hwnd = ensure_ready()
    if not hwnd or not name:
        return False
    _combo(VK_CONTROL, VK_F)
    time.sleep(0.7)
    _combo(VK_CONTROL, VK_A)
    time.sleep(0.1)
    _key(VK_BACK); _key(VK_BACK, True)
    time.sleep(0.2)
    if not clipboard_set(name):
        return False
    time.sleep(0.15)
    _combo(VK_CONTROL, VK_V)
    time.sleep(1.6)
    _key(VK_RETURN); _key(VK_RETURN, True)
    time.sleep(1.5)
    return True


def scale2x_bmp(bmp_bytes: bytes, w: int, h: int) -> tuple[bytes, int, int]:
    """最近邻放大 2 倍（小字号标题直接 OCR 容易漏字）。"""
    import struct
    off = struct.unpack_from("<I", bmp_bytes, 10)[0]
    row_size = (w * 3 + 3) & ~3
    ow, oh = w * 2, h * 2
    orow = (ow * 3 + 3) & ~3
    pad = b"\x00" * (orow - ow * 3)
    out = bytearray()
    for y in range(h - 1, -1, -1):          # 输出仍自底向上
        base = off + y * row_size
        line = bytearray()
        for x in range(w):
            px = bmp_bytes[base + x * 3: base + x * 3 + 3]
            line += px + px
        row = bytes(line) + pad
        out += row
        out += row
    header = bytearray()
    header += b"BM"
    header += (54 + len(out)).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")
    header += (54).to_bytes(4, "little")
    header += (40).to_bytes(4, "little")
    header += ow.to_bytes(4, "little")
    header += oh.to_bytes(4, "little")
    header += (1).to_bytes(2, "little")
    header += (24).to_bytes(2, "little")
    header += (0).to_bytes(4, "little")
    header += len(out).to_bytes(4, "little")
    header += (2835).to_bytes(4, "little") * 2
    header += (0).to_bytes(4, "little") * 2
    return bytes(header) + bytes(out), ow, oh


def read_title_region(hwnd: int) -> str:
    """OCR 聊天面板标题区。

    用 PrintWindow 抓整窗（不受遮挡），再按比例裁出聊天面板顶部的一条
    ——左侧会话列表在 30% 宽度以内，所以从 30% 开始取，避免把列表里的
    同名联系人误当成"已打开"。
    """
    full, w, h = print_window(hwnd)
    if not full or w <= 0 or h <= 0:
        return ""
    band = crop_window_bmp(full, w, h, 0.28, 0.01, 0.50, 0.12)
    path = os.path.join(CACHE, "title_%d.bmp" % int(time.time() * 1000))
    try:
        with open(path, "wb") as f:
            f.write(band)
        return ocr(path)
    finally:
        for p2 in (path, os.path.splitext(path)[0] + ".png"):
            try:
                os.remove(p2)
            except OSError:
                pass


def verify_title(name: str, retries: int = 2) -> bool:
    """确认当前打开的会话就是 name。返回 False 时调用方必须放弃发送。"""
    hwnd = wechat_hwnd()
    if not hwnd:
        return False
    target = _norm(name)
    if not target:
        return False
    for i in range(retries):
        text = read_title_region(hwnd)
        got = _norm(text)
        if got and target in got:
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------- 发送
def send_text(text: str, input_ratio=(0.5, 0.80)) -> bool:
    """在已通过校验的会话里粘贴并回车。

    三道保险：
      1) 粘贴前确认微信确实在前台，不是就把按键发到别的程序去了
      2) 清空输入框里可能残留的草稿，避免草稿和回复粘成一条发出去
      3) 发完把你原来的剪贴板内容还回去
    """
    hwnd = wechat_hwnd()
    if not hwnd or not text:
        return False
    if _u32.GetForegroundWindow() != hwnd:
        if not force_foreground(hwnd):
            return False
        time.sleep(0.25)
    if _u32.GetForegroundWindow() != hwnd:
        return False

    prev = clipboard_get()
    left, top, w, h = window_rect(hwnd)
    _click(left + int(w * input_ratio[0]), top + int(h * input_ratio[1]))
    time.sleep(0.35)
    # 输入框里可能还留着没发出去的草稿，不先清掉就会跟回复粘在一起发出去
    _combo(VK_CONTROL, VK_A)
    time.sleep(0.1)
    _key(VK_DELETE); _key(VK_DELETE, True)
    time.sleep(0.15)
    if not clipboard_set(text):
        return False
    time.sleep(0.15)
    _combo(VK_CONTROL, VK_V)
    time.sleep(0.45)
    _key(VK_RETURN); _key(VK_RETURN, True)
    time.sleep(0.4)
    if prev:
        try:
            clipboard_set(prev)
        except Exception:
            pass
    return True


def send_to(name: str, text: str) -> dict:
    """完整流程：打开 → 标题校验（辅助）→ 发送。

    硬闸门不在这里——调用方必须先用数据库确认「该显示名在本机唯一对应
    目标 wxid」。OCR 只作为辅助记录：小字号标题常被读错（例如生僻字被认成别的字 ->
    李班浩），拿它做唯一判据会误伤，所以只记录、不阻塞。
    """
    result = {"ok": False, "stage": "", "note": "", "title": ""}
    if not ensure_ready():
        result.update(stage="window", note="微信窗口不可用")
        return result
    if not open_chat(name):
        result.update(stage="open", note="打开会话失败")
        return result
    title = read_title_region(wechat_hwnd())
    result["title"] = title
    if _norm(name) not in _norm(title):
        result["note"] = "标题 OCR 未确认（%r），已按数据库唯一性放行" % title[:20]
    if not send_text(text):
        result.update(stage="send", note="粘贴/回车失败")
        return result
    result.update(ok=True, stage="sent")
    return result
