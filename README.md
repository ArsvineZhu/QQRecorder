# QQContextBot

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![NcatBot](https://img.shields.io/badge/NcatBot-5.5.3+-orange)

QQContextBot 是一个基于 NcatBot 的 QQ 消息记录与 AI 回复项目。

## 三个插件

| 插件 | 目录 | 作用 |
|------|------|------|
| `qq_recorder` | `plugins/qq_recorder/` | **静默记录** — SQLite 入库、图片下载、合并转发解析、贴纸识别、定时备份 |
| `qq_grok_reply` | `plugins/qq_grok_reply/` | **轻量回复** — 双轮单工具扩展，话题感知上下文 |
| `grok` | `plugins/grok/` | **多工具 Agent 回复** — 6 个工具、JSON 档案、视觉分析、思考模式 |

`qq_recorder` 是唯一必须启用的插件。两个回复插件独立可选，不依赖对方。

## 核心能力

- 静默记录群聊与私聊消息到 SQLite
- 下载并按日期归档图片（MD5 去重，格式检测）
- 递归解析合并转发消息（含非文本段的占位标记如 `[图片]` `[视频]`）
- 解析 QQ 小程序、图文分享、位置分享等 JSON 消息
- 三层次贴纸检测（元数据 → 文本 → 启发式）
- 定时全量/增量备份 SQLite + 图片
- 图片/视频 AI 解读结果永久存储（`image_analyses` 表）
- 用户档案管理（JSON 文件，CRUD 工具，群聊昵称独立）
- 禁言/解禁自动感知（写入档案 + recorder 通知记录）
- LLM 思考模式支持（`extra_body` 透传）
- Agent 多步工具调用（track_reply → load_context → read_picture → reply）

## 项目结构

```
QQContextBot/
├── README.md
├── AGENTS.md
├── CLAUDE.md
├── pyproject.toml
├── config.yaml              # NcatBot 运行时配置（适配器、插件加载）
├── CHANGELOG.md
├── devtools/
├── scripts/                 # 导出、迁移、备份工具
├── plugins/
│   ├── qq_recorder/         # 记录插件
│   ├── qq_grok_reply/       # 轻量回复插件
│   └── grok/                # Agent 回复插件
├── start-bot.sh
├── start-bot.ps1
├── data/qq_recorder/        # 运行期数据库 + 图片 + 备份
├── docs/                    # NcatBot 文档（不编辑）
└── napcat/                  # 第三方协议端（不编辑）
```

## 运行方式

### 1. 安装依赖

```bash
uv sync
```

### 2. 准备配置

仓库跟踪的是示例配置，实际运行请按需创建/修改：

- 根配置：`config.yaml`（适配器、API key）
- 记录插件：`plugins/qq_recorder/config.yaml`
- Agent 回复：`plugins/grok/config.yaml`

### 3. 启动

```bash
uv run ncatbot run
```

## 插件配置要点

### qq_recorder

路径相对于插件工作目录 `data/qq_recorder/`：

```yaml
storage:
  database: data/recorder.db
  images_dir: data/images
image:
  download: true
  timeout: 30
  max_file_size: 52428800
forward:
  max_depth: 8
```

### grok（Agent 回复）

`recorder_db` 必须为绝对路径。其他配置段包含 `trigger`、`agent`、`model`、`vision`、`profile` 等。

模型支持思考模式：

```yaml
model:
  model: "deepseek/deepseek-v4-flash"
  thinking_enabled: true
  thinking_effort: high
  timeout_sec: 60
```

用户档案存储在 `data/profiles.json`，不写在 YAML 配置中。

## 命令

群聊/私聊中发送：

| 命令 | 说明 |
|------|------|
| `/recorder stats` | 查看当前会话消息统计 |
| `/recorder recent [N]` | 查看最近 N 条消息 |
| `/recorder search <关键词>` | 关键词搜索 |

命令前缀：`recorder` / `/recorder` / `r` / `/r`，不区分大小写。

grok 插件前缀（`prefixes` 配置）：`/grok` / `/ask` / `grok` 或 @机器人。

## 数据模型

| 表名 | 说明 | 所属插件 |
|------|------|---------|
| `messages` | 消息主表 | recorder |
| `message_segments` | 消息段 | recorder |
| `images` | 图片记录 | recorder |
| `image_analyses` | 图片/视频 AI 解读结果 + 系统通知 | recorder + grok |
| `app_shares` | 应用分享 | recorder |
| `replies` | 回复关系 | recorder |
| `forward_messages` | 合并转发树 | recorder |
| `at_mentions` | @提及 | recorder |
| `monitored_chats` | 监控目标 | recorder |
| `vision_cache` | 视觉分析缓存 | grok |
| `agent_reply_traces` | Agent 回复追踪 | grok |
| `agent_profile_snapshots` | 用户档案（SQLite 旧版，迁移中） | grok |

## 备份与导出

```bash
python scripts/export_db.py summary
python scripts/export_db.py search "关键词"
python scripts/backup_tool.py list --dir data/qq_recorder/data/backups
```

## 开发

```bash
uv run ruff check plugins/
uv run ruff format plugins/ --check
uv run pyright plugins/
uv run pytest plugins/grok/tests/ plugins/qq_recorder/tests/ plugins/qq_grok_reply/tests/
```

## 许可证

MIT License
