# 迅雷 Telegram Bot

通过 Telegram 向DOCKER版迅雷（cnk3x/xunlei）推送磁力链接下载任务。

## 功能特点V1.0

- ✅ 发送磁力链接自动解析
- ✅ 智能过滤：只下载视频文件（>200MB）
- ✅ 支持选择下载目录
- ✅ 支持批量发送（空格或换行分隔）
- ✅ 自动跳过广告/垃圾文件

## 功能特点V2.0
### 🔄 全自动 Token 续期
告别手动复制粘贴 Token！ 支持BOT面板直接操作以及定时健康检查
- **重要**：需开启 Docker `privileged: true` 及 `host` 网络模式。
### 📝 任务详情透传
- **文件名反馈**：Telegram 返回的消息不再只显示任务名，而是直接列出**具体选中的文件名**（如 `MyMovie.2024.mp4`），下载对了没一目了然。
### ⚡️ 启动即自检
- 容器启动后**立即**执行一次连通性检查，随后每小时（可配置）自动巡检。

## 功能特点V3.0
### 🧠 无感知 Token 全自动刷新
- Token 过期后，Bot 自动请求迅雷 Web UI 主页，从 HTML 中提取嵌入的 UIAuth JWT，**全程无需任何用户操作**。
- 原理：xlp 将有效期约 **72 小时**的 UIAuth JWT 直接注入 Web UI 页面，Bot 通过简单 HTTP 请求即可获取，无需 tcpdump、进程内存扫描或任何特权操作。
- **降级兜底**：若 Web 提取失败（如迅雷服务未运行），才会通知用户打开迅雷网页并发送 `/check`，此时降级为 tcpdump 嗅探方式。
- V3.0 不再需要 `pid: host`，Docker 配置更简洁。

## 快速开始

### 1. 获取配置参数

#### Telegram 配置
- `BOT_TOKEN`: 从 @BotFather 创建机器人获取
- `CHAT_ID`: 你的 Telegram 用户 ID（可通过 @userinfobot 获取）

#### 迅雷配置
需要从浏览器开发者工具中获取以下参数：

1. 打开迅雷网页版，按 F12 打开开发者工具
2. 切换到 Network 标签
3. 在迅雷中操作（如打开文件夹），找到 API 请求
4. 从请求 URL/参数中获取：
   - `XUNLEI_SPACE`: URL 参数中的 `device_id` 值
   - `XUNLEI_PARENT_FILE_ID`: 目标文件夹的 ID
   - `XUNLEI_AUTH`: 请求头中的 `pan-auth` 值（**可不填**，Bot 启动后会自动获取）

### 2. 修改配置

编辑 `docker-compose.yaml`，填入你的配置参数。关键配置：

```yaml
privileged: true      # tcpdump 兜底抓包权限
network_mode: host    # 共享宿主机网络
```

### 3. 启动服务

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 使用指南

`/start`: 呼出状态面板，查看当前 Token 状态和迅雷连接情况。

**直接发送磁力链接**：Bot 会自动解析并询问下载目录，点击目录按钮后开始添加任务。

`/check`: 手动强制触发一次健康检查。

**Token 失效时**：Bot 会自动请求迅雷 Web UI 静默获取新 Token，全程无感知。若自动获取失败（如迅雷服务异常），Bot 会通知用户，此时请打开迅雷网页后发送 `/check`。

## 常见问题

**Q: Web UI 提取失败？**
A: 确认迅雷容器正在运行，且 `XUNLEI_HOST` 地址配置正确（Bot 需能访问迅雷 Web UI）。

**Q: 嗅探器一直提示超时？**
A: 检查 `privileged: true` 是否开启、`network_mode` 是否为 `host`、`SNIFF_PORT` 是否与迅雷端口一致。此为兜底机制，正常情况下不会触发。

**Q: Bot 没反应？**
A: 检查日志 `docker logs -f xunlei_tg_bot`。如果是网络问题（Telegram 连不上），请在环境变量中配置 `HTTP_PROXY`。

**Q: 为什么下载的文件名带反引号？**
A: 为防止 Telegram Markdown 解析错误（如文件名含下划线），Bot 在显示时故意包裹，不影响实际下载的文件名。
