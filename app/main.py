"""Notify 主入口。

职责：
  1. 管理界面（:8188）—— 全局设置 + 项目实例增删改
  2. 为每个已启用项目起一个指令服务线程（监听各自 port，处理 POST /exec）
  3. 提供 /notify，把通知转发到中转服务（RELAY_HOST:RELAY_PORT/notify）

所有数据源只读，不写回原容器。
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

import config_store
import projects

app = FastAPI(title="Notify")

MANAGE_PORT = int(os.environ.get("MANAGE_PORT", "8188"))


def cfg():
    return config_store.load()


def constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a, b):
        r |= ord(x) ^ ord(y)
    return r == 0


# ────────────────────────── 项目指令服务 ──────────────────────────


class ExecHandler(BaseHTTPRequestHandler):
    """处理 VPS 经 frp 隧道转来的指令：POST /exec"""

    project: dict = {}
    token: str = ""

    def log_message(self, fmt, *args):  # 静音访问日志
        pass

    def _send(self, code: int, text: str):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            self._send(400, "bad request")
            return

        if not constant_time_eq(str(data.get("token", "")), ExecHandler.token):
            self._send(403, "forbidden")
            return

        cmd = str(data.get("cmd", "") or "help").strip()
        try:
            out = projects.run_query(ExecHandler.project, cmd)
        except Exception as exc:  # noqa: BLE001
            out = f"执行失败: {exc}"
        self._send(200, out)

    def do_GET(self):  # noqa: N802
        self._send(200, "notify exec endpoint")


def start_project_server(project: dict, token: str):
    port = project.get("port")
    if not port:
        return None
    handler = type(
        "BoundExecHandler",
        (ExecHandler,),
        {"project": project, "token": token},
    )
    try:
        srv = HTTPServer(("0.0.0.0", int(port)), handler)
    except OSError as exc:
        print(f"[notify] 端口 {port} 启动失败: {exc}", flush=True)
        return None
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print(f"[notify] 项目 {project.get('name')} 监听 :{port}", flush=True)
    return srv


# ────────────────────────── 管理界面 API ──────────────────────────


@app.get("/health")
def health():
    return {"ok": True, "service": "notify"}


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <html><head><meta charset="utf-8"><title>Notify</title></head>
    <body style="font-family:system-ui;margin:24px">
      <h2>Notify — 通知与交互中枢</h2>
      <p>容器已运行。管理接口：
      <ul>
        <li><code>GET /api/config</code> 查看当前配置</li>
        <li><code>POST /api/global</code> 更新全局设置（表单）</li>
        <li><code>POST /api/projects</code> 新增/更新项目（表单）</li>
        <li><code>POST /api/projects/delete</code> 删除项目（表单）</li>
        <li><code>POST /notify</code> 推送通知到中转服务</li>
      </ul>
    </body></html>
    """


@app.get("/api/config")
def api_config():
    c = cfg()
    # 令牌只报长度，不回显
    safe = json.loads(json.dumps(c))
    tok = safe.get("global", {}).get("relay_push_token", "")
    safe["global"]["relay_push_token"] = f"<set:{len(tok)}>" if tok else "<unset>"
    return safe
