"""项目实例：按配置声明式执行，不写死逻辑。

每个项目：
  - source_type: file | sqlite | http | none
  - commands: { "指令名": "说明" }

加新项目 = 填配置，不改代码。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any

# 敏感字段名：出现在这些键中的值一律脱敏，绝不外发
# （实测 allinssl 的 access 表存有 Cloudflare api_key、腾讯云 secret_key，
#   通用查询会把它们原样返回并推送到企微 —— 必须拦住）
SENSITIVE_KEYS = (
    "api_key", "apikey", "secret", "token", "password", "passwd",
    "private_key", "access_key", "secret_id", "secretid",
    "credential", "authorization", "cookie", "session",
)


def _redact(obj: Any) -> Any:
    """递归脱敏：命中敏感键的值替换为 ***。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(s in kl for s in SENSITIVE_KEYS):
                out[k] = "***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    if isinstance(obj, str):
        # 字符串内嵌的 JSON（如 config 列）也要脱敏
        if "{" in obj and ":" in obj:
            try:
                import json as _json

                parsed = _json.loads(obj)
                if isinstance(parsed, (dict, list)):
                    return _json.dumps(_redact(parsed), ensure_ascii=False)
            except Exception:
                pass
            # 非严格 JSON：用正则兜住 key":"value" 形态
            for s in SENSITIVE_KEYS:
                obj = re.sub(
                    r'("%s"\s*:\s*)"[^"]*"' % re.escape(s),
                    r'\1"***"',
                    obj,
                    flags=re.IGNORECASE,
                )
        return obj
    return obj


class ProjectError(Exception):
    pass


def _read_file(path: str, limit: int = 4000) -> str:
    if not os.path.exists(path):
        raise ProjectError(f"数据源不存在: {path}")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return _redact(fh.read(limit))
    except Exception as exc:  # noqa: BLE001
        raise ProjectError(f"读取失败: {exc}") from exc


def _read_sqlite(path: str, limit: int = 20) -> str:
    if not os.path.exists(path):
        raise ProjectError(f"数据库不存在: {path}")
    try:
        # 只读打开，避免与原容器争写锁
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        lines = [f"表: {', '.join(tables) if tables else '(空)'}"]
        for t in tables[:5]:
            try:
                rows = conn.execute(f'SELECT * FROM "{t}" LIMIT ?', (limit,)).fetchall()
                lines.append(f"\n[{t}] {len(rows)} 行")
                for row in rows[:3]:
                    # 脱敏后再输出：命中敏感键的值替换为 ***
                    lines.append("  " + str(_redact(dict(row)))[:200])
            except Exception:
                continue
        conn.close()
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        raise ProjectError(f"查询失败: {exc}") from exc


def _read_http(url: str, command: str = "", timeout: int = 8) -> str:
    import httpx

    if "RELAY_HOST" in url:
        raise ProjectError("请先配置中转地址（当前为占位符 RELAY_HOST）")
    # 支持 {cmd} 占位符：把指令名注入 URL，避免只能硬编码单条指令
    # （iStoreOS 的 CGI API 形如 ?cmd=状态，不同指令需不同参数）
    if "{cmd}" in url:
        from urllib.parse import quote

        url = url.replace("{cmd}", quote(command or ""))
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        text = resp.text[:4000]
        # JSON 接口优先取 result 字段（iStoreOS 返回 {"ok":..,"result":".."}）
        try:
            import json as _json

            data = _json.loads(text)
            if isinstance(data, dict) and "result" in data:
                return _redact(str(data.get("result", "")))
            if isinstance(data, dict) and data.get("ok") is False:
                return f"接口返回错误: {data.get('err', '未知')}"
        except Exception:
            pass
        return f"HTTP {resp.status_code}\n{_redact(text[:2000])}"
    except Exception as exc:  # noqa: BLE001
        raise ProjectError(f"请求失败: {exc}") from exc


def run_query(project: dict, command: str) -> str:
    """按项目配置执行一个查询类指令。"""
    commands = project.get("commands") or {}
    if command not in commands and command != "help":
        avail = "、".join(commands.keys()) or "(无)"
        return f"未知指令: {command}（可用: {avail}）"

    if command == "help":
        lines = [f"项目: {project.get('name', '?')}", "可用指令："]
        for k, v in commands.items():
            lines.append(f"  {k}  {v}")
        return "\n".join(lines)

    stype = project.get("source_type", "none")
    path = project.get("source_path", "")
    try:
        if stype == "file":
            return _read_file(path)
        if stype == "sqlite":
            return _read_sqlite(path)
        if stype == "http":
            return _read_http(path, command)
        if stype == "none":
            return "该项目无数据源（仅通知）"
        raise ProjectError(f"不支持的数据源类型: {stype}")
    except ProjectError as exc:
        # 数据源缺失/不可读时返回可读提示，而不是把异常抛给调用方
        # （VPS 会把返回文本直接发到企微，抛异常只会显示崩溃信息）
        return f"执行失败: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"执行失败: {exc}"


def validate(project: dict) -> list[str]:
    """返回问题列表；空列表表示配置可用。"""
    issues: list[str] = []
    if not project.get("name"):
        issues.append("缺少项目名")
    stype = project.get("source_type", "none")
    if stype not in {"file", "sqlite", "http", "none"}:
        issues.append(f"不支持的数据源类型: {stype}")
    if stype in {"file", "sqlite", "http"} and not project.get("source_path"):
        issues.append("缺少数据源路径")
    if project.get("port") is not None:
        try:
            int(project["port"])
        except (TypeError, ValueError):
            issues.append("端口必须是数字")
    return issues
