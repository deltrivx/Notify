# 配置说明

配置落在 `/config/config.yaml`（容器内），由挂载目录持久化。

> 以下取值均为**占位符示例**，请替换为你自己的实际值。仓库与文档不含任何真实凭据。

## 结构

```yaml
global:
  relay_host: RELAY_HOST
  relay_port: 8181
  relay_push_token: RELAY_PUSH_TOKEN
  wecom_corpid: ""
  wecom_agentid: ""
  wecom_secret: ""
  enable_notify: true
  enable_cmd: true
  min_importance: normal
  language: zh-CN
  timezone: Asia/Shanghai

projects:
  - name: ddns-go
    kind: ddns-go
    port: 8283
    source_type: file
    source_path: /data/ddns_go_config.yaml
    commands:
      状态: 读配置文件并摘要
  - name: allinssl
    kind: allinssl
    port: 8285
    source_type: sqlite
    source_path: /data/allinssl.db
    commands:
      证书: 列出证书与到期时间
```

## 全局设置

| 键 | 占位符示例 | 默认 | 说明 |
|---|---|---|---|
| `relay_host` | `RELAY_HOST` | — | 中转服务地址（公网可达） |
| `relay_port` | `RELAY_PORT` | `8181` | 中转服务端口 |
| `relay_push_token` | `RELAY_PUSH_TOKEN` | — | 与中转共享的令牌 |
| `wecom_corpid` / `wecom_agentid` / `wecom_secret` | — | 空 | 企微凭据；若由中转代发可留空 |
| `enable_notify` | `true` | `true` | 通知总开关 |
| `enable_cmd` | `true` | `true` | 交互总开关 |
| `min_importance` | `normal` | `normal` | 最低通知级别 `normal`/`warning`/`alert` |

## 项目实例（需要几个加几个）

| 键 | 说明 |
|---|---|
| `name` | 项目显示名，用于幂等更新与删除 |
| `kind` | 模板名（`ddns-go`/`allinssl`/`istoreos`）或自定义标识 |
| `port` | 该项目指令服务监听端口；`null` 表示不监听（如 istoreos 经隧道直连） |
| `source_type` | `file` / `sqlite` / `http` / `none` |
| `source_path` | 文件路径 / DB 路径 / HTTP 地址 |
| `commands` | 指令名 → 说明 的映射 |

**通用性设计**：内置模板只是「预填的自定义配置」，任何字段都能覆写。
新增一个项目 = 填「名称 + 数据源 + 端口 + 命令列表」，**不需要改代码**。

## 数据源只读约定

- `file`：只读打开，绝不写回原容器配置
- `sqlite`：以 `mode=ro` 只读连接，避免与原容器争写锁
- `http`：带超时；占位符 `RELAY_HOST` 未替换时直接报错，避免误连

## 网络模式

容器用 **host 网络**，让各项目端口（如 `8283`/`8285`）与既有 frp 隧道保持一致，
因此 **frpc / VPS / 企微侧无需任何改动**。
