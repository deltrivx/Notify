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


def _run_custom_sql(path: str, spec: Any) -> str:
    """执行项目级自定义 SQL（只读），返回格式化表格文本。

    spec 形如：
      {"sql": "SELECT domains, end_day FROM cert", "header": ["域名","剩余天数"]}

    安全约束：
      - 仅允许单条 SELECT（禁止 ; 多语句与写操作）
      - 只读打开数据库
      - 输出统一脱敏
    """
    if not isinstance(spec, dict):
        return "自定义查询配置格式错误"
    sql = str(spec.get("sql", "")).strip()
    header = spec.get("header") or []
    if not sql:
        return "自定义查询缺少 sql"
    low = sql.lower()
    if not low.startswith("select"):
        return "自定义查询只允许 SELECT"
    if ";" in sql:
        return "自定义查询禁止多语句"
    if not os.path.exists(path):
        raise ProjectError(f"数据库不存在: {path}")

    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        rows = conn.execute(sql).fetchall()
        cols = [d[0] for d in conn.description] if conn.description else []
        conn.close()
    except Exception as exc:  # noqa: BLE001
        raise ProjectError(f"查询失败: {exc}") from exc

    if not rows:
        return "（无数据）"

    title = header if isinstance(header, list) and header else cols
    lines = []
    for r in rows:
        vals = []
        for v in r:
            v = _redact(v)
            s = str(v)
            # 单元格截断，避免 PEM 之类超长内容刷屏
            if len(s) > 60:
                s = s[:57] + "..."
            vals.append(s)
        lines.append(" | ".join("%s: %s" % (title[i] if i < len(title) else cols[i] if i < len(cols) else "?", vals[i]) for i in range(len(vals))))
    return "\n".join(lines)


def _dechunk(data: bytes) -> bytes:
    """解析 HTTP chunked 响应体（iStoreOS CGI 返回 chunked，体前会带长度前缀如 2A3）。"""
    out = b""
    while data:
        line, _, rest = data.partition(b"\r\n")
        try:
            size = int(line.split(b";")[0].strip(), 16)
        except (ValueError, IndexError):
            break
        if size == 0:
            break
        out += rest[:size]
        data = rest[size + 2:]
    return out


def _raw_get_utf8(url: str, timeout: int = 8) -> str:
    """用原始 UTF-8 字节发送 GET（不做百分号编码），并解析 chunked 响应。

    实测：iStoreOS 的 CGI 不解码 %XX —— 发 ?cmd=%E7%8A%B6%E6%80%81 时，
    服务端把它当成指令名返回「未知指令：%E7%8A%B6%E6%80%81」；
    必须直接发送中文原始字节才能正确识别（与 curl 行为一致）。
    """
    import socket

    from urllib.parse import urlsplit

    p = urlsplit(url)
    host = p.hostname or ""
    port = p.port or 80
    path = p.path or "/"
    if p.query:
        path = path + "?" + p.query

    req = (
        "GET %s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Connection: close\r\n"
        "Accept: application/json, text/plain\r\n"
        "\r\n" % (path, host)
    )
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        s.sendall(req.encode("utf-8"))
        buf = b""
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()

    head, _, body = buf.partition(b"\r\n\r\n")
    if b"transfer-encoding: chunked" in head.lower():
        body = _dechunk(body)
    return body.decode("utf-8", "replace")


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
    if "RELAY_HOST" in url:
        raise ProjectError("请先配置中转地址（当前为占位符 RELAY_HOST）")
    # 支持 {cmd} 占位符：把指令名注入 URL，避免只能硬编码单条指令
    # （iStoreOS 的 CGI API 形如 ?cmd=状态，不同指令需不同参数）
    if "{cmd}" in url:
        # 注意：这里不做 quote —— 实测 iStoreOS 的 CGI 不解码 %XX，
        # 编码后会被当成指令名本身；直接放中文，由 _raw_get_utf8 以原始字节发送
        url = url.replace("{cmd}", command or "")
    try:
        text = _raw_get_utf8(url, timeout=timeout)[:4000]
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
        return _redact(text[:2000])
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

    # 项目级自定义 SQL 优先：让「证书」返回可读列表，而不是整表 dump
    # （通用 dump 会把 PEM 证书全文、access 凭据表一起吐出来，内容又长又乱）
    queries = project.get("queries") or {}
    if isinstance(queries, dict) and command in queries:
        return _run_custom_sql(path, queries[command])

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
