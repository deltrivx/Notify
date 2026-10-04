# 图标资源

图标来自 [xushier/HD-Icons](https://github.com/xushier/HD-Icons)（高清仪表盘图标，1024×1024，MIT）。

## 选用

| 文件 | 来源 | 用途 |
|---|---|---|
| `assets/logo.png` | `border-radius/ntfy-1.png` | 主图标原图（1024×1024） |
| `assets/logo-512.png` | 由 logo.png 缩放 | 仓库 / 文档展示 |
| `assets/icon-256.png` | 由 logo.png 缩放 | **容器图标**（Unraid 模板用） |
| `assets/icon-128.png` | 由 logo.png 缩放 | 小尺寸场景 |
| `assets/logo-wecom.png` | `border-radius/wecom-1.png` | 企微关联场景备用 |
| `assets/icon-wecom-256.png` | 由 logo-wecom.png 缩放 | 企微风格容器图标备选 |

**为何选 ntfy**：Notify 的定位是「通知推送 + 交互中枢」，`ntfy` 是推送类图标，比通用铃铛或聊天图标更贴合"中枢/广播"语义。
企微图标（`wecom-1`）作为备选保留，因为 Notify 当前主要服务企业微信场景。

## 用法

Unraid 模板中图标字段指向宿主机 PNG 绝对路径，例如：

```xml
<Icon>/mnt/user/icons/notify.png</Icon>
```

把 `assets/icon-256.png` 放到该路径即可。
