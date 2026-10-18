#!/usr/bin/env python3
"""projects 单元测试：数据源解析与配置校验（不依赖网络）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import projects  # noqa: E402


def test_help_lists_commands():
    proj = {
        "name": "ddns-go",
        "source_type": "file",
        "source_path": "/nonexistent.yaml",
        "commands": {"状态": "查看", "配置": "要点"},
    }
    out = projects.run_query(proj, "help")
    assert "ddns-go" in out
    assert "状态" in out and "配置" in out


def test_unknown_command_reports_available():
    proj = {
        "name": "x",
        "source_type": "none",
        "commands": {"状态": "查看"},
    }
    out = projects.run_query(proj, "no-such-cmd")
    assert "未知指令" in out


def test_file_source_reads_content():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        fh.write("key: value\n")
        path = fh.name
    proj = {
        "name": "f",
        "source_type": "file",
        "source_path": path,
        "commands": {"查看": "读取"},
    }
    out = projects.run_query(proj, "查看")
    assert "key: value" in out
    os.unlink(path)


def test_file_source_missing_is_error_not_crash():
    proj = {
        "name": "f",
        "source_type": "file",
        "source_path": "/definitely/not/here.yaml",
        "commands": {"查看": "读取"},
    }
    out = projects.run_query(proj, "查看")
    assert "不存在" in out or "失败" in out


def test_http_rejects_placeholder_host():
    proj = {
        "name": "istoreos",
        "source_type": "http",
        "source_path": "RELAY_HOST:10084/cgi-bin/istoreos-api",
        "commands": {"状态": "查询"},
    }
    out = projects.run_query(proj, "状态")
    assert "RELAY_HOST" in out


def test_validate_catches_missing_fields():
    assert projects.validate({})  # 空配置必须有报错
    assert projects.validate({"name": "a", "source_type": "none"}) == []


def test_validate_rejects_bad_port():
    issues = projects.validate(
        {"name": "a", "source_type": "none", "port": "not-a-number"}
    )
    assert any("端口" in i for i in issues)


def test_http_exec_mode_mock():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import json

    class MockExecHandler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode())
            if data.get("token") != "secret123":
                self.send_response(403)
                self.end_headers()
                return
            cmd = data.get("cmd")
            res = {"ok": True, "result": f"mock-{cmd}"}
            body = json.dumps(res).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), MockExecHandler)
    port = srv.server_port
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()

    proj = {
        "name": "unraid",
        "source_type": "http",
        "source_path": f"http://127.0.0.1:{port}/exec",
        "token": "secret123",
        "commands": {"status": "状态查询"},
    }
    out = projects.run_query(proj, "status")
    assert out == "mock-status"
    srv.shutdown()
    srv.server_close()


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK  ", name)
    print("projects tests passed")
