# 迅雷 Telegram Bot

通过 Telegram 向DOCKER版迅雷（cnk3x/xunlei）推送磁力链接下载任务。

## 功能特点

- ✅ 发送磁力链接自动解析
- ✅ 智能过滤：只下载视频文件（>200MB）
- ✅ 支持选择下载目录
- ✅ 支持批量发送（空格或换行分隔）
- ✅ 自动跳过广告/垃圾文件

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
4. 从请求头中获取：
   - `XUNLEI_AUTH`: 请求头中的 `pan-auth` 值
   - `XUNLEI_COOKIE`: 请求头中的 `Cookie` 值（可选）
   - `XUNLEI_SYNO_TOKEN`: 请求头中的 `x-syno-token` 值（可选）

5. 从请求 URL/参数中获取：
   - `XUNLEI_SPACE`: URL 参数中的 `space` 值
   - `XUNLEI_PARENT_FILE_ID`: 目标文件夹的 ID

### 2. 修改配置

编辑 `docker-compose.yaml`，填入你的配置参数。

### 3. 启动服务

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 使用方法

1. 在 Telegram 中找到你的 Bot
2. 发送磁力链接（支持多个，用空格或换行分隔）
3. 选择下载目录
4. 等待下载完成

## 注意事项

- `XUNLEI_AUTH` (pan-auth) 是 JWT Token，有效期较短，过期后需要重新获取
- 建议使用代理确保 Telegram Bot 能正常连接
- 批量下载时每个任务间隔 10 秒，防止触发风控

## 文件说明

```
xunlei-tg-bot/
├── bot.py              # 主程序
├── Dockerfile          # Docker 镜像定义
├── docker-compose.yaml # Docker Compose 配置
└── README.md           # 本文档
```

## 常见问题

### Token 过期
如果出现认证错误，需要重新从浏览器获取 `XUNLEI_AUTH` 值并更新配置。

### 连接超时
检查代理配置，确保容器能访问 Telegram API 和迅雷 API。

### 下载到错误文件
已修复：使用 API 返回的 `file_index` 字段而非遍历顺序索引。
