#!/usr/bin/env python3
"""config_store 单元测试（不依赖网络与外部服务）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import config_store  # noqa: E402


def test_default_has_placeholder():
    cfg = config_store.default_config()
    assert "global" in cfg
    assert "projects" in cfg
    # 默认必须是占位符，不得含真实地址
    assert cfg["global"]["relay_host"] == "RELAY_HOST"
    assert cfg["global"]["relay_push_token"] == "RELAY_PUSH_TOKEN"


def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        config_store.CONFIG_DIR = d
        config_store.CONFIG_PATH = os.path.join(d, "config.yaml")
        cfg = config_store.default_config()
        cfg["global"]["relay_host"] = "example.invalid"
        config_store.save(cfg)
        loaded = config_store.load()
        assert loaded["global"]["relay_host"] == "example.invalid"


def test_upsert_is_idempotent_by_name():
    cfg = config_store.default_config()
    proj = {
        "name": "ddns-go",
        "port": 8283,
        "source_type": "file",
        "source_path": "/data/ddns.yaml",
        "commands": {"状态": "查看"},
    }
    config_store.upsert_project(cfg, proj)
    assert len(cfg["projects"]) == 1
    # 同名再次写入 = 更新，不新增
    proj2 = dict(proj)
    proj2["port"] = 9999
    config_store.upsert_project(cfg, proj2)
    assert len(cfg["projects"]) == 1
    assert cfg["projects"][0]["port"] == 9999


def test_remove_project():
    cfg = config_store.default_config()
    config_store.upsert_project(cfg, {"name": "a", "source_type": "none"})
    config_store.upsert_project(cfg, {"name": "b", "source_type": "none"})
    config_store.remove_project(cfg, "a")
    assert [p["name"] for p in cfg["projects"]] == ["b"]


def test_builtin_templates():
    for key in ("ddns-go", "allinssl", "istoreos"):
        assert isinstance(config_store.template_for(key), dict)
    # 未知类型返回空 dict —— 保证纯自定义项目可用
    assert config_store.template_for("no-such-kind") == {}


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK  ", name)
    print("config_store tests passed")
