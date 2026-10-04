"""配置存储：全局设置 + 项目实例列表。

配置落在 /config/config.yaml（由容器挂载持久化）。
所有示例值一律为占位符，不含真实凭据。
"""
from __future__ import annotations

import os
import shutil
import threading
import time

import yaml

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.yaml")

_lock = threading.RLock()

DEFAULT_GLOBAL = {
    # 中转服务（公网可达）；占位符，请替换为自己的值
    "relay_host": "RELAY_HOST",
    "relay_port": 8181,
    # 与中转服务共享的令牌
    "relay_push_token": "RELAY_PUSH_TOKEN",
    # 企微凭据（可选；若由中转代发，可留空）
    "wecom_corpid": "",
    "wecom_agentid": "",
    "wecom_secret": "",
    # 全局开关
    "enable_notify": True,
    "enable_cmd": True,
    # 默认通知级别：normal | warning | alert
    "min_importance": "normal",
    "language": "zh-CN",
    "timezone": "Asia/Shanghai",
}

# 内置模板：只是「预填的自定义配置」，任何字段都可覆写
BUILTIN_TEMPLATES = {
    "ddns-go": {
        "port": 8283,
        "source_type": "file",
        "source_path": "/data/ddns_go_config.yaml",
        "commands": {
            "状态": "读配置文件并摘要",
            "配置": "输出当前配置要点",
        },
    },
    "allinssl": {
        "port": 8285,
        "source_type": "sqlite",
        "source_path": "/data/allinssl.db",
        "commands": {
            "证书": "列出证书与到期时间",
            "工作流": "列出工作流状态",
        },
    },
    "istoreos": {
        "port": None,  # 经隧道直连，无本地监听
        "source_type": "http",
        "source_path": "RELAY_HOST:10084/cgi-bin/istoreos-api",
        "commands": {
            "状态": "查询路由状态",
            "接口": "列出网络接口",
        },
    },
}


def default_config() -> dict:
    return {"global": dict(DEFAULT_GLOBAL), "projects": []}


def load() -> dict:
    with _lock:
        if not os.path.exists(CONFIG_PATH):
            return default_config()
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except Exception:
            return default_config()
        cfg = default_config()
        if isinstance(data.get("global"), dict):
            cfg["global"].update(data["global"])
        if isinstance(data.get("projects"), list):
            cfg["projects"] = data["projects"]
        return cfg


def save(cfg: dict) -> None:
    """原子写：先写临时文件再重命名，避免半截配置。"""
    with _lock:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
        if os.path.exists(CONFIG_PATH):
            shutil.copy2(CONFIG_PATH, CONFIG_PATH + ".bak")
        os.replace(tmp, CONFIG_PATH)


def upsert_project(cfg: dict, project: dict) -> dict:
    """按 name 幂等更新；不存在则追加。"""
    with _lock:
        projects = cfg.setdefault("projects", [])
        for i, p in enumerate(projects):
            if p.get("name") == project.get("name"):
                merged = dict(p)
                merged.update(project)
                projects[i] = merged
                return cfg
        projects.append(project)
        return cfg


def remove_project(cfg: dict, name: str) -> dict:
    with _lock:
        cfg["projects"] = [p for p in cfg.get("projects", []) if p.get("name") != name]
        return cfg


def template_for(kind: str) -> dict:
    return dict(BUILTIN_TEMPLATES.get(kind, {}))


def stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
