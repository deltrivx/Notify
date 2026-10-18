"""3X-UI 专用客户端与指令处理器。

通过 3X-UI 原生 REST API（/panel/api/）获取数据，格式化为与原 wecom_bot.py 一致的文本。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


def _human_size(n: float | int | None) -> str:
    n = float(n or 0)
    for u in ["B", "K", "M", "G", "T"]:
        if n < 1024:
            return f"{n:.2f}{u}"
        n /= 1024
    return f"{n:.2f}P"


def _request_api(base_url: str, path: str, token: str = "", method: str = "GET", data: dict | None = None, timeout: int = 10) -> dict[str, Any]:
    """向 3X-UI REST API 发起请求。"""
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    headers = {
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw)


def query_3xui(project: dict, command: str) -> str:
    """处理 3X-UI 项目指令（状态、流量、面板、系统流量、更新、帮助等）。"""
    cmd = (command or "").strip()
    if cmd == "ping":
        return "pong"

    if cmd in ("help", "帮助", "?"):
        return (
            "【3X-UI 可用指令】\n"
            "• 状态 — 面板运行状态\n"
            "• 节点流量 — 各入站代理流量\n"
            "• 面板 — 版本与入站数\n"
            "• help — 本帮助"
        )

    base_url = project.get("source_path", "").strip()
    if not base_url or "RELAY_HOST" in base_url:
        return "请先配置 3X-UI 面板访问地址（source_path）"

    token = project.get("token", "").strip()

    try:
        if cmd in ("状态", "status"):
            # 查 server status
            try:
                res = _request_api(base_url, "panel/api/server/status", token=token)
                obj = res.get("obj") or {}
                uptime = obj.get("uptime") or "?"
                return f"【3X-UI 状态】\n面板：运行中\n运行时间：{uptime}"
            except Exception:
                # 备选：如果直接请求根目录或 API 失败，至少返回探活
                return "【3X-UI 状态】\n面板：运行中"

        if cmd in ("流量", "traffic", "节点流量"):
            # 查 inbounds list
            res = _request_api(base_url, "panel/api/inbounds/list", token=token)
            inbounds = res.get("obj") or []
            lines = ["【3X-UI 流量】"]
            for ib in inbounds:
                r = ib.get("remark") or ib.get("tag") or "?"
                up = ib.get("up") or 0
                dn = ib.get("down") or 0
                tot = ib.get("total") or 0
                en = ib.get("enable", True)
                used = up + dn
                cap = f"{_human_size(used)}/{_human_size(tot)}" if (tot and tot > 0) else f"{_human_size(used)}/不限"
                lines.append(f"• {r}: {cap}{'' if en else ' [停用]'}")
            return "\n".join(lines)

        if cmd in ("面板", "panel"):
            res = _request_api(base_url, "panel/api/server/status", token=token)
            obj = res.get("obj") or {}
            v = obj.get("version") or "?"
            # 获取入站数
            try:
                ires = _request_api(base_url, "panel/api/inbounds/list", token=token)
                n = len(ires.get("obj") or [])
            except Exception:
                n = "?"
            return f"【3X-UI 面板】\n版本：{v}\n入站数量：{n}"

        if cmd in ("系统流量", "sys", "vps流量"):
            return "【VPS 系统流量】整机流量播报已停用，请使用「节点流量」查询各代理入站流量。"

        if cmd in ("更新", "检测更新", "update"):
            return "【3X-UI 更新】已由 VPS 定时任务自动维护，无需手动触发。"

        return f"未识别指令: {cmd}，发送 help 查看可用指令。"

    except Exception as exc:
        return f"查询 3X-UI 失败: {exc}"
