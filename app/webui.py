#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""本地控制面板：启停机器人、改参数、看日志、管理画像。

只监听 127.0.0.1，纯标准库（http.server），不依赖任何第三方包。
打开 http://127.0.0.1:8765 使用。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths  # noqa: E402

BASE = paths.ROOT
CONFIG = paths.BOT_CONFIG
PROFILES = paths.PROFILES
LOG = paths.BOT_LOG
LOCK = paths.BOT_LOCK
BOT = os.path.join(HERE, "bot.py")
PY = sys.executable
PORT = 8765


# ------------------------------------------------------------------ 机器人控制
def _pid_alive(pid: int) -> bool:
    """用 OpenProcess 判断，避免起子进程（子进程会闪控制台）。"""
    if not pid:
        return False
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong(0)
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def bot_pid() -> int:
    try:
        with open(LOCK, encoding="utf-8") as f:
            pid = int(f.read().strip() or 0)
    except Exception:
        return 0
    return pid if pid and _pid_alive(pid) else 0


def _pythonw() -> str:
    cand = os.path.join(os.path.dirname(PY), "pythonw.exe")
    return cand if os.path.isfile(cand) else PY


def start_bot() -> dict:
    pid = bot_pid()
    if pid:
        return {"ok": True, "note": "已经在运行", "pid": pid}
    try:
        os.remove(LOCK)
    except OSError:
        pass
    flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    p = subprocess.Popen([_pythonw(), BOT], cwd=BASE, creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.3)
        if bot_pid():
            return {"ok": True, "note": "已启动", "pid": bot_pid()}
    return {"ok": False, "note": "启动后未检测到进程（看日志）", "pid": 0}


def stop_bot() -> dict:
    pid = bot_pid()
    if not pid:
        return {"ok": True, "note": "本来就没在运行", "pid": 0}
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as exc:
        return {"ok": False, "note": "停止失败: %s" % exc, "pid": pid}
    for _ in range(20):
        time.sleep(0.2)
        if not bot_pid():
            break
    try:
        os.remove(LOCK)
    except OSError:
        pass
    return {"ok": True, "note": "已停止", "pid": 0}


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


def clean_cache(age_seconds: int = 1800) -> dict:
    """清理解密缓存与截图临时文件，返回释放了多少。"""
    cache_dir = os.path.join(BASE, "cache")
    freed = 0
    removed = 0
    now = time.time()
    for root, _dirs, files in os.walk(cache_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                age = now - os.path.getmtime(path)
                is_img = name.lower().endswith((".bmp", ".png"))
                if (is_img and age > 300) or age > age_seconds:
                    size = os.path.getsize(path)
                    os.remove(path)
                    freed += size
                    removed += 1
            except OSError:
                pass
    return {"ok": True, "removed": removed, "freed_mb": round(freed / 1048576, 2),
            "note": "清理 %d 个临时文件，释放 %.2f MB" % (removed, freed / 1048576)}


def tail_log(n: int = 200) -> list[str]:
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [ln.rstrip("\n") for ln in lines[-n:]]
    except Exception:
        return []


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "WeixPanel/1.0"

    def log_message(self, fmt, *args):     # 静音，避免刷屏
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/state":
            cfg = read_json(CONFIG, {})
            profs = read_json(PROFILES, {})
            pid = bot_pid()
            self._json({
                "running": bool(pid),
                "pid": pid,
                "config": cfg,
                "profiles": profs,
                "log": tail_log(120),
            })
            return
        if path == "/api/log":
            self._json({"log": tail_log(300)})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        body = self._body()

        if path == "/api/action":
            act = body.get("action")
            if act == "start":
                self._json(start_bot())
            elif act == "stop":
                self._json(stop_bot())
            elif act == "restart":
                stop_bot()
                time.sleep(0.5)
                self._json(start_bot())
            elif act == "build_profiles":
                self._json(run_profiles())
            else:
                self._json({"ok": False, "note": "未知操作"}, 400)
            return

        if path == "/api/config":
            cfg = read_json(CONFIG, {})
            incoming = body.get("config") or {}
            if not isinstance(incoming, dict):
                self._json({"ok": False, "note": "格式错误"}, 400)
                return
            cfg.update(incoming)
            write_json(CONFIG, cfg)
            self._json({"ok": True, "note": "已保存（机器人会自动读取，无需重启）"})
            return

        if path == "/api/profiles":
            data = body.get("profiles")
            if not isinstance(data, dict):
                self._json({"ok": False, "note": "格式错误"}, 400)
                return
            write_json(PROFILES, data)
            self._json({"ok": True, "note": "画像已保存（立即生效）"})
            return

        self._json({"error": "not found"}, 404)


def run_profiles(wxid: str = "") -> dict:
    cmd = [PY, os.path.join(HERE, "build_profiles.py")]
    if wxid:
        cmd += ["--wxid", wxid]
    try:
        out = subprocess.run(cmd,
                             cwd=BASE, capture_output=True, text=True, timeout=300,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        text = (out.stdout or "") + (out.stderr or "")
        ok = out.returncode == 0
        return {"ok": ok, "note": text.strip()[-800:] or "完成"}
    except Exception as exc:
        return {"ok": False, "note": "执行失败: %s" % exc}


# ------------------------------------------------------------------ 页面
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>微信回复机器人 · 控制面板</title>
<style>
  :root { --bg:#0f1115; --card:#171a21; --line:#262b35; --fg:#e6e9ef; --dim:#8b93a3; --ok:#2ec27e; --bad:#e5484d; --pri:#3b82f6; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }
  header { padding:18px 24px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:14px; }
  h1 { font-size:16px; margin:0; font-weight:600; }
  .wrap { padding:20px 24px; display:grid; gap:18px; max-width:1080px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; }
  .card h2 { font-size:13px; margin:0 0 12px; color:var(--dim); font-weight:600; letter-spacing:.5px; }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:8px; }
  .on { background:var(--ok); box-shadow:0 0 8px var(--ok); }
  .off { background:var(--bad); }
  button { background:var(--pri); color:#fff; border:0; border-radius:7px; padding:8px 16px; font-size:13px; cursor:pointer; }
  button.ghost { background:#242a35; }
  button.danger { background:var(--bad); }
  button:disabled { opacity:.45; cursor:not-allowed; }
  input, textarea { background:#0e1117; color:var(--fg); border:1px solid var(--line); border-radius:7px; padding:8px 10px; font:inherit; width:100%; }
  textarea { resize:vertical; }
  label { color:var(--dim); font-size:12px; display:block; margin-bottom:4px; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .grid3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
  pre { background:#0b0e13; border:1px solid var(--line); border-radius:8px; padding:12px; height:260px; overflow:auto; margin:0; font:12px/1.5 Consolas,monospace; color:#b8c0cf; white-space:pre-wrap; }
  .muted { color:var(--dim); font-size:12px; }
  .toast { position:fixed; right:18px; bottom:18px; background:#1f2530; border:1px solid var(--line); border-radius:8px; padding:10px 14px; opacity:0; transition:.2s; max-width:420px; }
  .toast.show { opacity:1; }
</style>
</head>
<body>
<header>
  <h1>微信回复机器人</h1>
  <span id="state" class="muted"><span class="dot off"></span>连接中…</span>
</header>

<div class="wrap">
  <div class="card">
    <h2>运行控制</h2>
    <div class="row">
      <button id="btnStart" onclick="act('start')">启动</button>
      <button id="btnStop" class="danger" onclick="act('stop')">停止</button>
      <button class="ghost" onclick="act('restart')">重启</button>
      <span class="muted" id="pidInfo"></span>
    </div>
    <p class="muted" style="margin:12px 0 0">启动后机器人会监听微信新消息；停止后完全不运行，不影响你正常用微信。</p>
  </div>

  <div class="card">
    <h2>回复参数</h2>
    <div class="grid3">
      <div><label>合并等待（秒）</label><input id="debounce_seconds" type="number" step="1"></div>
      <div><label>同会话最小间隔（秒）</label><input id="min_reply_interval" type="number" step="1"></div>
      <div><label>消息最大时效（秒）</label><input id="max_message_age_seconds" type="number" step="10"></div>
    </div>
    <div class="grid3" style="margin-top:12px">
      <div><label>模型</label><input id="model"></div>
      <div><label>温度</label><input id="temperature" type="number" step="0.1" min="0" max="2"></div>
      <div><label>视觉模型</label><input id="vision_model"></div>
    </div>
    <div style="margin-top:12px">
      <label>白名单（每行一个：wxid=显示名）</label>
      <textarea id="whitelist" rows="3" placeholder="wxid_xxx=备注名"></textarea>
    </div>
    <div style="margin-top:12px">
      <label>全局人设（基础语气，所有人共用）</label>
      <textarea id="persona" rows="10"></textarea>
    </div>
    <div class="row" style="margin-top:14px">
      <button onclick="saveConfig()">保存参数</button>
    </div>
  </div>

  <div class="card">
    <h2>按人画像</h2>
    <p class="muted" style="margin:0 0 10px">关系、语气、长度、习惯、禁忌。改完立即生效。</p>
    <textarea id="profiles" rows="14" style="font:12px/1.6 Consolas,monospace"></textarea>
    <div class="row" style="margin-top:14px">
      <button onclick="saveProfiles()">保存画像</button>
      <button class="ghost" onclick="act('build_profiles')">按聊天记录重新生成</button>
    </div>
  </div>

  <div class="card">
    <h2>运行日志 <span class="muted" style="font-weight:400">（每 3 秒刷新）</span></h2>
    <pre id="log"></pre>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let cfg = null, profs = null;

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), 3200);
}

async function api(path, body) {
  const opt = body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {};
  const r = await fetch(path, opt);
  return await r.json();
}

function fillConfig(c) {
  cfg = c;
  for (const k of ['debounce_seconds','min_reply_interval','max_message_age_seconds','model','temperature','vision_model']) {
    const el = document.getElementById(k);
    if (el) el.value = (c[k] !== undefined && c[k] !== null) ? c[k] : '';
  }
  const wl = c.whitelist || {};
  document.getElementById('whitelist').value =
    Object.entries(wl).map(([k,v]) => k + '=' + v).join('\n');
  document.getElementById('persona').value = c.persona || '';
}

function readConfig() {
  const wl = {};
  for (const line of document.getElementById('whitelist').value.split('\n')) {
    const s = line.trim();
    if (!s) continue;
    const i = s.indexOf('=');
    if (i > 0) wl[s.slice(0,i).trim()] = s.slice(i+1).trim();
  }
  const num = id => { const v = parseFloat(document.getElementById(id).value); return isNaN(v) ? undefined : v; };
  return {
    debounce_seconds: num('debounce_seconds'),
    min_reply_interval: num('min_reply_interval'),
    max_message_age_seconds: num('max_message_age_seconds'),
    model: document.getElementById('model').value.trim(),
    temperature: num('temperature'),
    vision_model: document.getElementById('vision_model').value.trim(),
    whitelist: wl,
    persona: document.getElementById('persona').value,
  };
}

async function refresh(showLog = true) {
  const s = await api('/api/state');
  document.getElementById('state').innerHTML =
    s.running ? '<span class="dot on"></span>运行中' : '<span class="dot off"></span>已停止';
  document.getElementById('pidInfo').textContent = s.running ? ('PID ' + s.pid) : '';
  document.getElementById('btnStart').disabled = s.running;
  document.getElementById('btnStop').disabled = !s.running;
  if (showLog) {
    const el = document.getElementById('log');
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    el.textContent = (s.log || []).join('\n');
    if (atBottom) el.scrollTop = el.scrollHeight;
  }
  if (!cfg) fillConfig(s.config || {});
  if (!profs) {
    profs = s.profiles || {};
    document.getElementById('profiles').value = JSON.stringify(profs, null, 2);
  }
}

async function act(action) {
  const r = await api('/api/action', {action});
  toast(r.note || (r.ok ? '完成' : '失败'));
  cfg = null; profs = null;
  await refresh();
}

async function saveConfig() {
  const c = readConfig();
  for (const k of Object.keys(c)) if (c[k] === undefined) delete c[k];
  const r = await api('/api/config', {config: c});
  toast(r.note || '已保存');
}

async function saveProfiles() {
  try {
    const data = JSON.parse(document.getElementById('profiles').value);
    const r = await api('/api/profiles', {profiles: data});
    toast(r.note || '已保存');
  } catch (e) {
    toast('JSON 格式错误：' + e.message);
  }
}

refresh();
setInterval(() => refresh(true), 3000);
</script>
</body>
</html>
"""


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("控制面板: http://127.0.0.1:%d" % PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
