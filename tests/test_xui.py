"""3X-UI 模块测试。"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import unittest

from app import projects, xui_client


class MockXUIHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if "panel/api/server/status" in self.path:
            body = json.dumps({"success": True, "obj": {"version": "3.10.2", "uptime": "10 days"}}).encode("utf-8")
        elif "panel/api/inbounds/list" in self.path:
            body = json.dumps({
                "success": True,
                "obj": [
                    {"remark": "vless-reality", "up": 1024 * 1024 * 100, "down": 1024 * 1024 * 500, "total": 0, "enable": True},
                    {"remark": "hy2", "up": 1024 * 1024 * 50, "down": 1024 * 1024 * 150, "total": 1024 * 1024 * 1024, "enable": False},
                ]
            }).encode("utf-8")
        else:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestXUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockXUIHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_xui_commands(self):
        proj = {
            "name": "3x-ui",
            "kind": "3x-ui",
            "source_type": "http",
            "source_path": f"http://127.0.0.1:{self.port}/deltrivx/",
            "token": "mock-token",
            "commands": {
                "状态": "面板运行状态",
                "流量": "各入站代理流量",
                "面板": "版本与入站数",
                "help": "本帮助",
            }
        }

        # 测试 help
        out = projects.run_query(proj, "help")
        self.assertIn("【3X-UI 可用指令】", out)

        # 测试 状态
        out = projects.run_query(proj, "状态")
        self.assertIn("【3X-UI 状态】", out)
        self.assertIn("10 days", out)

        # 测试 流量
        out = projects.run_query(proj, "流量")
        self.assertIn("【3X-UI 流量】", out)
        self.assertIn("vless-reality", out)
        self.assertIn("[停用]", out)

        # 测试 面板
        out = projects.run_query(proj, "面板")
        self.assertIn("【3X-UI 面板】", out)
        self.assertIn("3.10.2", out)
        self.assertIn("入站数量：2", out)

        # 测试 系统流量 指令
        out = projects.run_query(proj, "系统流量")
        self.assertIn("【VPS 系统流量】整机流量播报已停用", out)


if __name__ == "__main__":
    unittest.main()
