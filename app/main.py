"""Notify 主入口。

职责：
  1. 管理界面（:8188）—— 真正的交互面板（填表单保存，保存后热重载生效）
  2. 为每个项目起一个指令服务线程（监听各自 port，处理 POST /exec）
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
from fastapi.responses import HTMLResponse, JSONResponse

import config_store
import projects
import ui

app = FastAPI(title="Notify")

MANAGE_PORT = int(os.environ.get("MANAGE_PORT", "8188"))

# 运行中的项目指令服务（热重载用：停止旧的、按新配置重启，不重启容器
_servers: dict = {}
_servers_lock = threading.Lock()


def cfg():
    return config_store.load()


def constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a, b):
        r |= ord(x) ^ ord(y)
    return r == 0


def _parse_yaml_map(text: str) -> dict:
    """把 YAML 文本框内容解析成 dict（空则返回 {}）。"""
    t = (text or "").strip()
    if not t:
        return {}
    try:
        data = yaml.safe_load(t)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _stop_all_servers() -> None:
    """停止所有项目指令服务（热重载用）。

    先 shutdown() 让 serve_forever 线程退出，再 server_close() 释放监听 socket。
    配合 allow_reuse_address，端口可立即重新绑定。
    """
    with _servers_lock:
        for name, srv in list(_servers.items()):
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass
        _servers.clear()


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
        payload = json.dumps({"ok": code == 200, "result": text}, ensure_ascii=False)
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
    """启动一个项目的指令服务并记录到 _servers（热重载用）。"""
    port = project.get("port")
    if not port:
        return None

    name = project.get("name", "?")
    with _servers_lock:
        if name in _servers:
            return _servers[name]

    handler = type(
        "BoundExecHandler",
        (ExecHandler,),
        {"project": project, "token": token},
    )
    try:
        # allow_reuse_address：避免重启时 TIME_WAIT 导致端口占用失败
        HTTPServer.allow_reuse_address = True
        srv = HTTPServer(("0.0.0.0", int(port)), handler)
    except OSError as exc:
        print(f"[notify] 项目 {name} 端口 {port} 启动失败: {exc}", flush=True)
        return None
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    with _servers_lock:
        _servers[name] = srv
    print(f"[notify] 项目 {name} 监听 :{port}", flush=True)
    return srv


def apply_config() -> None:
    """按当前配置重启所有项目服务（热重载）。"""
    c = cfg()
    gtoken = str(c.get("global", {}).get("relay_push_token", "") or "")
    enabled = bool(c.get("global", {}).get("enable_cmd", True))
    _stop_all_servers()
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


# ────────────────────────── 管理面板 ──────────────────────────


@app.get("/health")
def health():
    return {"ok": True, "service": "notify"}


@app.get("/", response_class=HTMLResponse)
def index():
    """真正的交互面板：表单 + 项目卡片，不是 API 说明。"""
    return ui.render(cfg())


@app.get("/api/config")
def api_config():
    c = cfg()
    safe = json.loads(json.dumps(c))
    tok = safe.get("global", {}).get("relay_push_token", "")
    safe["global"]["relay_push_token"] = f"<set:{len(tok)}>" if tok else "<unset>"
    return safe


@app.post("/api/global")
async def api_global(request: Request):
    """保存全局设置并热重载（令牌留空=保持不变）。"""
    body = await _json_or_form(request)
    c = cfg()
    g = c.setdefault("global", {})
    for key in ("relay_host", "wecom_corpid", "wecom_agentid", "min_importance",
                "language", "timezone"):
        if key in body and str(body[key]).strip():
            g[key] = str(body[key]).strip()
    # 令牌类：留空 或 纯星号 = 保持不变（面板用 *** 表示已配置，不能把星号当成真值存进去）
    for key in ("relay_push_token", "wecom_secret"):
        if key in body:
            raw = str(body.get(key) or "").strip()
            if raw and not raw.startswith("<set:") and set(raw) != {"*"}:
                g[key] = raw
    if "relay_port" in body:
        raw = str(body["relay_port"]).strip()
        if raw.isdigit():
            g["relay_port"] = int(raw)
    for key in ("enable_notify", "enable_cmd"):
        if key in body:
            raw = str(body[key]).strip().lower()
            g[key] = raw in ("1", "true", "yes", "on")
    config_store.save(c)
    apply_config()  # 热重载
    return {"ok": True, "reloaded": True}


@app.post("/api/projects")
async def api_projects_add(request: Request):
    """新增/更新项目（按 name 幂等）并热重载。"""
    body = await _json_or_form(request)
    name = str(body.get("name", "")).strip()
    if not name:
        return JSONResponse({"ok": False, "error": "缺少项目名"}, status_code=400)

    port_raw = str(body.get("port") or "").strip()
    # 命令：优先用 YAML 文本框；无则给默认
    cmds = _parse_yaml_map(body.get("commands_yaml", ""))
    if not cmds:
        cmds = {"状态": "查询", "帮助": "列出指令", "help": "列出指令"}
    project = {
        "name": name,
        "kind": str(body.get("kind", "") or "").strip() or "custom",
        "source_type": str(body.get("source_type", "") or "none").strip(),
        "source_path": str(body.get("source_path", "") or "").strip(),
        "commands": cmds,
    }
    qs = _parse_yaml_map(body.get("queries_yaml", ""))
    if qs:
        project["queries"] = qs
    tok_raw = str(body.get("token") or "").strip()
    # 面板用 *** 表示「已配置、保持不变」，不能把星号当真值存进去
    if tok_raw and set(tok_raw) != {"*"}:
        project["token"] = tok_raw
    project["port"] = int(port_raw) if port_raw.isdigit() else None

    issues = projects.validate(project)
    if issues:
        return JSONResponse({"ok": False, "error": "; ".join(issues)}, status_code=400)

    c = cfg()
    # 保留原有项目级令牌（若本次留空）
    old = next((p for p in c.get("projects", []) if p.get("name") == name), None)
    if old and not tok_raw and old.get("token"):
        project["token"] = old["token"]

    config_store.upsert_project(c, project)
    config_store.save(c)
    apply_config()
    return {"ok": True, "project": name, "reloaded": True}


@app.post("/api/projects/delete")
async def api_projects_del(request: Request):
    body = await _json_or_form(request)
    name = str(body.get("name", "")).strip()
    if not name:
        return JSONResponse({"ok": False, "error": "缺少项目名"}, status_code=400)
    c = cfg()
    config_store.remove_project(c, name)
    config_store.save(c)
    apply_config()
    return {"ok": True, "removed": name, "reloaded": True}


@app.post("/api/test")
async def api_test(request: Request):
    """在不改动配置的前提下试跑一条指令（验证数据源与 SQL 是否可用）。"""
    body = await _json_or_form(request)
    name = str(body.get("name", "")).strip()
    if not name:
        return JSONResponse({"ok": False, "error": "缺少项目名"}, status_code=400)
    c = cfg()
    p = next((x for x in c.get("projects", []) if x.get("name") == name), None)
    if not p:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    cmd = str(body.get("test_cmd") or "help").strip() or "help"
    # 用表单里的临时值构造（不落库）便于调试
    tmp = dict(p)
    for k in ("source_type", "source_path"):
        if body.get(k):
            tmp[k] = str(body[k]).strip()
    cmds = _parse_yaml_map(body.get("commands_yaml", ""))
    if cmds:
        tmp["commands"] = cmds
    qs = _parse_yaml_map(body.get("queries_yaml", ""))
    if qs:
        tmp["queries"] = qs
    return {"ok": True, "result": projects.run_query(tmp, cmd)}


@app.post("/api/reload")
async def api_reload():
    apply_config()
    return {"ok": True, "reloaded": True}


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


async def _json_or_form(request: Request) -> dict:
    """同时接受 JSON 与表单提交（面板用 JSON，脚本/旧调用可能用表单）"""
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    try:
        form = await request.form()
        out = {}
        for k in form.keys():
            out[k] = form.get(k)

        # checkbox 未勾选时表单不带该键，显式补 false（面板 JS 已补，这里兜底）
        for k in ("enable_notify", "enable_cmd"):
            if k not in out:
                out[k] = "false"
    except Exception:  # noqa: BLE001
        return {}

    return out


def main() -> None:
    import uvicorn

    apply_config()
    print(f"[notify] 管理面板监听 :{MANAGE_PORT}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=MANAGE_PORT, log_level="info")


if __name__ == "__main__":
    main()
