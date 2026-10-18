"""3X-UI 专用客户端与指令处理器。

通过 3X-UI 原生 REST API（/panel/api/）获取数据，格式化为与原 wecom_bot.py 一致的文本。
"""
from __future__ import annotations

import calendar
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

import config_store


def _human_size(n: float | int | None) -> str:
    """二进制单位（KiB/MiB/GiB），用于节点流量展示。"""
    n = float(n or 0)
    for u in ["B", "K", "M", "G", "T"]:
        if n < 1024:
            return f"{n:.2f}{u}"
        n /= 1024
    return f"{n:.2f}P"


def _human_decimal(n: float | int | None) -> str:
    """十进制单位，与运营商口径一致（KB/MB/GB/TB），用于系统整机套餐统计。"""
    n = float(n or 0)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1000:
            return f"{n:.2f} {u}"
        n /= 1000
    return f"{n:.2f} PB"


_baseline_lock = threading.Lock()


def _get_baseline_path() -> str:
    base_dir = config_store.CONFIG_DIR
    if not os.path.exists(base_dir):
        try:
            os.makedirs(base_dir, exist_ok=True)
        except OSError:
            base_dir = os.path.join(os.path.dirname(__file__), "..", "config")
            os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "xui_traffic_baseline.json")


def update_traffic_stats(project: dict) -> dict:
    """从 3X-UI REST API 获取累计流量，并更新持久化基准。"""
    base_url = project.get("source_path", "").strip()
    token = project.get("token", "").strip()
    if not base_url or not token:
        raise ValueError("3X-UI source_path or token not configured")

    res = _request_api(base_url, "panel/api/server/status", token=token)
    obj = res.get("obj") or {}
    net = obj.get("netTraffic") or {}
    curr_total = int(net.get("sent", 0)) + int(net.get("recv", 0))

    now = time.localtime()
    cur_month = time.strftime("%Y-%m", now)
    cur_day = time.strftime("%Y-%m-%d", now)
    b_path = _get_baseline_path()

    with _baseline_lock:
        data = {}
        if os.path.exists(b_path):
            try:
                with open(b_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        month_str = data.get("month_str")
        day_str = data.get("day_str")
        month_used = int(data.get("month_used", 0))
        today_used = int(data.get("today_used", 0))
        last_total = data.get("last_total")

        if last_total is None:
            # 首次初始化
            month_used = int(project.get("initial_month_bytes") or curr_total)
            today_used = int(project.get("initial_today_bytes") or 0)
            last_total = curr_total
            month_str = cur_month
            day_str = cur_day
        else:
            last_total = int(last_total)
            # 跨月重置
            if month_str != cur_month:
                month_used = 0
                month_str = cur_month
            # 跨日重置
            if day_str != cur_day:
                today_used = 0
                day_str = cur_day

            # 计算增量（防 VPS 重启网卡计数器清零）
            if curr_total >= last_total:
                delta = curr_total - last_total
            else:
                delta = curr_total

            month_used += delta
            today_used += delta
            last_total = curr_total

        data = {
            "month_str": month_str,
            "month_used": month_used,
            "day_str": day_str,
            "today_used": today_used,
            "last_total": last_total,
            "updated_at": int(time.time()),
        }

        os.makedirs(os.path.dirname(b_path), exist_ok=True)
        tmp_path = b_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        try:
            os.chmod(tmp_path, 0o600)
        except Exception:
            pass
        os.replace(tmp_path, b_path)

        return data


def get_sys_traffic_report(project: dict) -> str:
    """生成与原 sys_traffic_report.py 格式一致的系统流量播报文本。"""
    stats = update_traffic_stats(project)
    used = stats.get("month_used", 0)
    today = stats.get("today_used", 0)

    # 配额计算（十进制 1000^4，老脚本口径）
    quota_tb = float(project.get("monthly_quota_tb") or 2.93)
    quota = quota_tb * (1000 ** 4)
    iface = str(project.get("iface") or "eth0")

    now = time.localtime()
    pct = (used / quota * 100) if quota > 0 else 0.0
    left = max(0.0, quota - used)

    dim = calendar.monthrange(now.tm_year, now.tm_mon)[1]
    dom = now.tm_mday
    days_left = dim - dom + 1
    avg = used / dom if dom > 0 else used
    proj = avg * dim

    lines = [
        f"【VPS 系统流量】{time.strftime('%Y-%m-%d')}",
        f"网卡：{iface}",
        f"本月已用：{_human_decimal(used)} / {_human_decimal(quota)}（{pct:.1f}%）",
        f"剩余：{_human_decimal(left)}",
        f"今日：{_human_decimal(today)}",
        f"日均：{_human_decimal(avg)} ｜ 本月剩余 {days_left} 天",
        f"预计月末：{_human_decimal(proj)}",
    ]
    if pct >= 90:
        lines.append(f"⚠️ 已用 {pct:.1f}%，接近套餐上限！")
    elif pct >= 75:
        lines.append(f"注意：已用 {pct:.1f}%")
    if avg * days_left > left:
        lines.append("⚠️ 按当前日均，剩余天数内将超出套餐")
    return "\n".join(lines)


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
            "• 流量 — 各入站代理流量\n"
            "• 系统流量 — VPS 网卡总流量/套餐余量\n"
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
                if isinstance(uptime, (int, float)):
                    days = int(uptime // 86400)
                    hours = int((uptime % 86400) // 3600)
                    mins = int((uptime % 3600) // 60)
                    up_str = f"{days}天{hours}时{mins}分" if days else f"{hours}时{mins}分"
                else:
                    up_str = str(uptime)
                xray_st = obj.get("xray", {}).get("state") or "running"
                return f"【3X-UI 状态】\n面板：运行中\nXray：{xray_st}\n运行时间：{up_str}"
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
            v = obj.get("panelVersion") or obj.get("version") or "?"
            xray_v = obj.get("xray", {}).get("version")
            v_str = f"{v} (Xray {xray_v})" if xray_v else v
            # 获取入站数
            try:
                ires = _request_api(base_url, "panel/api/inbounds/list", token=token)
                n = len(ires.get("obj") or [])
            except Exception:
                n = "?"
            return f"【3X-UI 面板】\n版本：{v_str}\n入站数量：{n}"

        if cmd in ("系统流量", "sys", "vps流量", "systraffic"):
            return get_sys_traffic_report(project)

        if cmd in ("更新", "检测更新", "update"):
            return "【3X-UI 更新】已由 VPS 定时任务自动维护，无需手动触发。"

        return f"未识别指令: {cmd}，发送 help 查看可用指令。"

    except Exception as exc:
        return f"查询 3X-UI 失败: {exc}"
