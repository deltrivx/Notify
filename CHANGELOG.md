# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-18

### Added
- **企业微信通用回调适配层**：新增 `/cb/{app_name}` 端点，原生支持企业微信 GET echostr 验签与 POST 加密 XML 消息/事件解密交互。
- **一通道一应用体系**：配置支持 `global.wecom.apps` 独立多应用映射，支持自持凭据与独立 Token / AES Key。
- **凭据分离隔离**：支持从 `/config/secrets.yaml`（权限 600）安全融合密钥，保护核心凭据不进入版本控制与公开配置。
- **出站统一代理发信**：异步发信支持指定出站透传代理（`global.wecom.proxy`），适配企业可信固定 IP 出口。
- **安全加解密套件**：引入 `wecom_crypto.py` 与单元测试 `test_wecom_crypto.py`，完整覆盖 PKCS7 填充、AES-CBC 与 SHA1 验签。

### Changed
- 完善 Dockerfile 与云端 GitHub Actions 流水线，引入 `cryptography` 依赖支持端到端安全传输。
- 增强 `config_store`，支持无缝加载外部注入的敏感凭据。
