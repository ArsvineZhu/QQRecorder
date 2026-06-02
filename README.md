# QQContextBot

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![NcatBot](https://img.shields.io/badge/NcatBot-5.5.3+-orange)

QQContextBot 是一个基于 NcatBot 的 QQ 上下文记录项目。它会静默记录群聊与私聊消息，
将文本、图片、合并转发、贴纸和应用分享整理进 SQLite，并提供检索、统计、备份和可选
的上下文回复插件。

## 项目说明

- `QQContextBot` 是项目对外名称
- `qq_recorder` 和 `qq_grok_reply` 仍然是代码包名与插件目录名，保留以兼容现有代码
- 运行入口始终是 `uv run ncatbot run`

## 核心能力

- 静默记录群聊与私聊消息
- 下载并按日期归档图片，保留原始格式
- 识别普通图片、动画表情、商城贴纸与 emoji
- 递归解析合并转发消息
- 解析 QQ 小程序、图文分享和位置分享等 JSON 消息
- 提供统计、最近消息与关键词搜索命令
- 支持定时备份 SQLite 与图片
- 提供可选的 `qq_grok_reply` 平行插件，用记录到的上下文生成受控回复

## 项目结构

```
QQContextBot/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── config.yaml
├── devtools/
├── scripts/
├── plugins/
│   ├── qq_recorder/
│   └── qq_grok_reply/
├── start-bot.sh
├── start-bot.ps1
├── data/qq_recorder/
├── docs/
└── napcat/
```

## 运行方式

### 1. 安装依赖

```bash
uv sync
```

### 2. 准备配置

仓库里跟踪的是示例配置与代码，实际运行请使用本地文件：

- 根配置：`config.yaml`
- 记录插件：`plugins/qq_recorder/config.yaml`
- 回复插件：`plugins/qq_grok_reply/config.yaml`

根 `config.yaml` 负责 NcatBot 运行时配置。插件自己的运行参数放在各自目录内的本地配置文件中。

### 3. 配置 NapCat

按 NapCat 官方文档完成登录和 WebSocket 配置。`napcat/` 目录是第三方协议端内容，不建议直接修改。

### 4. 启动

```bash
uv run ncatbot run
```

## 记录插件配置

`plugins/qq_recorder/config.yaml` 主要字段如下：

```yaml
monitor_all: true
targets:
  groups: ["群号1", "群号2"]
  private: ["QQ号1"]
storage:
  database: data/recorder.db
  images_dir: data/images
image:
  download: true
  timeout: 30
  max_file_size: 52428800
processing:
  max_inflight: 48
  image_download_concurrency: 4
forward:
  max_depth: 10
  parse_content: true
backup:
  enabled: true
  output_dir: data/backups
  keep_last: 7
```

路径都是相对于插件工作目录 `data/qq_recorder/` 计算的，而不是项目根目录。

## 回复插件配置

`qq_grok_reply` 是与记录插件并行加载的独立插件。它只读取 QQContextBot 记录到的内容，
不修改主记录链路。

```yaml
enabled: false
recorder_db: "D:/absolute/path/to/recorder.db"
monitor_all: false
targets:
  groups: ["群号1"]
  private: ["QQ号1"]
trigger:
  private_enabled: true
  group_enabled: true
  prefixes: ["/ask", "/ai", "grok"]
  allow_at: true
  ignore_self: true
```

`recorder_db` 必须填写 QQContextBot 实际使用的 `recorder.db` 绝对路径。

## 命令

在群聊或私聊中发送：

| 命令 | 说明 |
|------|------|
| `/recorder stats` | 查看当前会话的消息统计 |
| `/recorder recent [N]` | 查看最近 N 条消息 |
| `/recorder search <关键词>` | 搜索包含关键词的消息 |

命令前缀支持：`recorder`、`/recorder`、`r`、`/r`，不区分大小写。

## 数据模型

| 表名 | 说明 |
|------|------|
| `messages` | 消息主表 |
| `message_segments` | 消息段 |
| `images` | 图片记录 |
| `app_shares` | 应用分享结构化数据 |
| `replies` | 回复关系 |
| `forward_messages` | 合并转发树 |
| `at_mentions` | @ 提及记录 |
| `monitored_chats` | 监控目标 |
| `reply_traces` | `qq_grok_reply` 的回复追踪 |

## 备份与导出

常用工具脚本：

```bash
python scripts/export_db.py summary
python scripts/export_db.py search "关键词"
python scripts/export_db.py stats
python scripts/backup_tool.py list --dir data/qq_recorder/data/backups
python scripts/backup_tool.py restore --archive <backup.zip> --db-path <recorder.db> --images-dir <images-dir>
```

完整说明见 [scripts/README.md](scripts/README.md)。

## 开发与维护

```bash
uv run ruff check .
uv run ruff format . --diff
uv run pyright
uv run pytest plugins/qq_recorder/tests/ plugins/qq_grok_reply/tests/
```

## 参考文档

- `AGENTS.md` - 项目级 AI 维护说明
- `plugins/qq_recorder/AGENTS.md` - 记录插件说明
- `plugins/qq_grok_reply/` - 回复插件源码与测试
- `CHANGELOG.md` - 版本变更记录

## 许可证

MIT License
