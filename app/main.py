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
        # VPS 侧各 cb 用 json.loads(...) 后取 result 字段。
        # 之前直接返回纯文本(text/plain)，VPS json.loads 会抛异常 -> 走进 except，
        # 企微最终收到的是「指令执行失败」。必须返回 JSON 才能对齐现有链路。
        payload = json.dumps(
            {"ok": code == 200, "result": text}, ensure_ascii=False
        )
        body = payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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

        # 必须用 self（绑定子类注入的 token），不能引用基类 ExecHandler.token
        # —— 基类默认是空串，会导致「正确 token 也被拒」
        if not constant_time_eq(str(data.get("token", "")), self.token):
            self._send(403, "forbidden")
            return

        cmd = str(data.get("cmd", "") or "help").strip()
        try:
            # 同理，用 self.project 而非基类空 dict
            out = projects.run_query(self.project, cmd)
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
        # allow_reuse_address：避免容器重启时 TIME_WAIT 导致端口占用失败
        HTTPServer.allow_reuse_address = True
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


@app.post("/api/global")
async def api_global(request: Request):
    """更新全局设置（表单提交）。令牌留空表示不修改。"""
    form = await request.form()
    c = cfg()
    g = c.setdefault("global", {})
    for key in ("relay_host", "relay_push_token", "wecom_corpid", "wecom_agentid",
                "wecom_secret", "min_importance", "language", "timezone"):
        if key in form and str(form[key]).strip():
            g[key] = str(form[key]).strip()
    for key in ("relay_port", "enable_notify", "enable_cmd"):
        if key in form:
            raw = str(form[key]).strip()
            if key == "relay_port":
                g[key] = int(raw) if raw.isdigit() else g.get(key)
            else:
                g[key] = raw.lower() in ("1", "true", "yes", "on")
    config_store.save(c)
    return {"ok": True}


@app.post("/api/projects")
async def api_projects_add(request: Request):
    """新增/更新项目实例（按 name 幂等）。"""
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not name:
        return JSONResponse({"ok": False, "error": "缺少项目名"}, status_code=400)

    project = {
        "name": name,
        "kind": str(form.get("kind", "")).strip() or "custom",
        "source_type": str(form.get("source_type", "none")).strip(),
        "source_path": str(form.get("source_path", "")).strip(),
        "commands": {"状态": "查询", "帮助": "列出指令"},
    }
    # 项目级 token（可选，覆盖全局）
    ptok = str(form.get("token", "")).strip()
    if ptok:
        project["token"] = ptok
    port = str(form.get("port", "")).strip()
    project["port"] = int(port) if port.isdigit() else None

    issues = projects.validate(project)
    if issues:
        return JSONResponse({"ok": False, "error": "; ".join(issues)}, status_code=400)

    c = cfg()
    config_store.upsert_project(c, project)
    config_store.save(c)

    # 立即尝试拉起该项目的指令服务
    token = str(project.get("token") or c.get("global", {}).get("relay_push_token", ""))
    start_project_server(project, token)
    return {"ok": True, "project": name}


@app.post("/api/projects/delete")
async def api_projects_del(request: Request):
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not name:
        return JSONResponse({"ok": False, "error": "缺少项目名"}, status_code=400)
    c = cfg()
    config_store.remove_project(c, name)
    config_store.save(c)
    return {"ok": True, "removed": name}


@app.post("/notify")
async def api_notify(request: Request):
    """把通知转发到中转服务。占位符未替换时直接报错，避免误连。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    c = cfg()
    g = c.get("global", {})
    host = str(g.get("relay_host", "")).strip()
    if not host or host == "RELAY_HOST":
        return JSONResponse(
            {"ok": False, "error": "未配置中转地址（当前为占位符 RELAY_HOST）"},
            status_code=400,
        )

    token = str(g.get("relay_push_token", "")).strip()
    payload = {
        "token": token,
        "title": str(body.get("title", "")),
        "content": str(body.get("content", "")),
        "importance": str(body.get("importance", "normal")),
    }
    url = "http://%s:%s/notify" % (host, int(g.get("relay_port", 8181)))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
        return {"ok": resp.status_code < 400, "status": resp.status_code}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)


# ────────────────────────── 启动入口 ──────────────────────────
# 之前 main.py 只定义了路由，从未真正启动服务 —— 脚本执行完即退出（ExitCode=0），
# 在 restart: unless-stopped 下表现为「无限重启」。这里补上真正的启动逻辑。


def bootstrap() -> None:
    c = cfg()
    gtoken = str(c.get("global", {}).get("relay_push_token", "") or "")
    enabled = bool(c.get("global", {}).get("enable_cmd", True))
    if not enabled:
        print("[notify] 交互总开关关闭，不起项目指令服务", flush=True)
        return
    for project in c.get("projects", []):
        issues = projects.validate(project)
        if issues:
            print(
                "[notify] 跳过项目 %s: %s" % (project.get("name"), "; ".join(issues)),
                flush=True,
            )
            continue
        # 项目级 token 覆盖全局（不同项目可能用不同令牌）
        token = str(project.get("token") or gtoken)
        start_project_server(project, token)


def main() -> None:
    import uvicorn

    bootstrap()
    print(f"[notify] 管理界面监听 :{MANAGE_PORT}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=MANAGE_PORT, log_level="info")


if __name__ == "__main__":
    main()
