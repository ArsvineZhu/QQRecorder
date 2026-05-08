# QQRecorder

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![NcatBot](https://img.shields.io/badge/NcatBot-5.5.3+-orange)

静默 QQ 消息记录器 —— 基于 NcatBot 框架的 QQ 消息自动记录插件，无感记录群聊与私聊中的所有消息。

## 特性

- **静默记录** — 自动记录群聊与私聊消息，不会发送任何提示消息
- **图片下载** — 自动下载消息中的图片，按日期归档存储，保留原始格式（JPG/PNG/GIF/WebP/BMP）
- **合并转发解析** — 递归解析合并转发消息，支持自定义最大深度
- **消息搜索** — 内置关键词搜索与最近消息查询
- **统计面板** — 查看消息数、图片数等统计信息
- **灵活配置** — 支持全量监控或指定群/私聊监控
- **异步存储** — 基于 SQLAlchemy + aiosqlite 的异步数据库，不阻塞消息处理

## 架构概览

```
QQ 消息
    │
    ▼
NcatBot Event Hook
    │
    ▼
监控过滤器（monitor_all / targets）
    │
    ▼
消息解析器（message_parser）
    │
    ├──────────────────────────────┐
    ▼                              ▼
消息段解析                    合并转发解析
(message_segments)           (forward_parser)
    │                              │ 递归
    ▼                              ▼
存储层（SQLite）◄──────── 图片处理
    │                    (image_handler)
    │                        │
    │                        ▼
    │                   下载图片
    │                   格式检测
    │                   存储归档
    │
    ▼
数据库（recorder.db）
```

## 环境要求

- Python >= 3.12
- [NcatBot](https://github.com/ncatbot/NcatBot) >= 5.5.3
- [NapCat](https://github.com/NapNeko/NapCatQQ)（QQ 协议端）

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/Arsvine/QQRecorder.git
cd QQRecorder
```

### 2. 安装依赖

推荐使用 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync
```

或使用 pip：

```bash
pip install -e .
```

### 3. 配置 NapCat

将 `recorder/napcat/` 目录中的 NapCat 配置到你自己的 QQ 账号。参考 [NapCat 文档](https://napneko.github.io/) 完成登录与 WebSocket 配置。

### 4. 配置插件

编辑 `recorder/config.yaml`：

```yaml
bot_uin: '你的QQ号'              # 机器人 QQ 号
root: '管理员QQ号'               # 管理员 QQ 号（用于执行命令）

plugin:
  plugin_configs:
    qq_recorder:
      # 监控模式：true = 记录所有消息，false = 仅记录 targets 中的目标
      monitor_all: true
      # 监控目标（monitor_all 为 false 时生效）
      targets:
        groups: ["群号1", "群号2"]    # 要监控的群号列表
        private: ["QQ号1"]            # 要监控的私聊对象 QQ 号列表
      storage:
        database: data/recorder.db    # 数据库路径（相对于插件工作目录）
        images_dir: data/images       # 图片存储目录（相对于插件工作目录）
      image:
        download: true                # 是否下载图片
        timeout: 30                   # 下载超时时间（秒）
        max_file_size: 20971520       # 最大文件大小（字节），默认 20MB
      forward:
        max_depth: 10                 # 合并转发消息最大递归深度
        parse_content: true           # 是否解析转发内容
```

## 使用

### 启动

```bash
cd recorder
python -m ncatbot
```

### 命令

在群聊或私聊中发送以下命令：

| 命令 | 说明 |
|------|------|
| `/recorder stats` | 查看当前会话的消息统计 |
| `/recorder recent [N]` | 查看最近 N 条消息（默认 5，最多 20） |
| `/recorder search <关键词>` | 搜索包含关键词的消息（最多 10 条） |

> 命令前缀支持：`recorder`、`/recorder`、`r`、`/r`（不区分大小写）

## 项目结构

```
QQRecorder/
├── README.md                   # 项目文档
├── AGENTS.md                   # AI 辅助开发知识库
├── pyproject.toml              # Python 项目配置与依赖
├── config.yaml                 # NcatBot 主配置
├── scripts/
│   ├── export_db.py            # 数据库导出与查询工具
│   ├── fix_image_extensions.py # 图片格式修复工具（v1.1.2 迁移用）
│   └── fix_newline_escaping.py # 换行符转义修复工具（v1.1.3 迁移用）
└── recorder/
    ├── config.yaml             # 插件运行配置
    ├── napcat/                 # NapCat 协议端（第三方组件，请勿修改）
    ├── data/
    │   └── qq_recorder/        # 运行时数据
    │       ├── recorder.db     # SQLite 数据库
    │       └── images/         # 图片存储目录
    └── plugins/
        └── qq_recorder/        # 核心插件代码
            ├── main.py          # 插件入口
            ├── plugin.py        # 消息处理、命令响应
            ├── config.py        # 配置模型与校验
            ├── models.py        # SQLAlchemy 数据模型
            ├── storage.py       # 异步数据库操作
            ├── message_parser.py # 消息段解析
            ├── image_handler.py  # 图片下载与格式检测
            ├── forward_parser.py # 合并转发解析
            ├── text_utils.py    # 文本转义/反转义工具
            ├── manifest.toml    # NcatBot 插件清单
            └── AGENTS.md         # 插件级知识库
```

## 工具脚本

### export_db.py

数据库导出与查询工具，支持 8 个子命令：

```bash
# 查看概览：表行数、消息时间范围、按类型统计
python scripts/export_db.py summary

# 查看完整表结构：列信息、类型、约束、外键、索引
python scripts/export_db.py schema

# 查看指定表数据（可指定行数限制）
python scripts/export_db.py table messages 50

# 查看消息列表（支持按类型/ID 过滤）
python scripts/export_db.py messages --chat group --id 123456

# 查看图片记录（支持过滤已下载/未下载）
python scripts/export_db.py images --downloaded
python scripts/export_db.py images --missing

# 搜索消息内容
python scripts/export_db.py search "关键词"

# 按会话统计消息数、发送者排行
python scripts/export_db.py stats

# 导出完整数据库（JSON 或 CSV）
python scripts/export_db.py export -o backup.json
python scripts/export_db.py export --format csv -o backup.csv
```

### fix_image_extensions.py

v1.1.2 图片格式修复工具。升级前版本的图片可能被错误地存储为 `.jpg` 格式，此脚本通过检测文件魔数来识别真实格式并修正文件名与数据库记录。

```bash
# 预览修改（不实际执行）
python scripts/fix_image_extensions.py --dry-run

# 执行修复
python scripts/fix_image_extensions.py
```

### fix_newline_escaping.py

v1.1.3 换行符转义修复工具。旧版本中消息内容以原始换行符存入数据库，导致显示和导出时格式异常。此脚本扫描 `messages.raw_message` 和 `forward_messages.content_summary`，将 `\n`/`\r`/`\t` 转义为 `\\n`/`\\t`。

```bash
# 预览修改（不实际执行）
python scripts/fix_newline_escaping.py --dry-run

# 执行修复
python scripts/fix_newline_escaping.py
```

## 数据模型

| 表名 | 说明 |
|------|------|
| `messages` | 消息主表：消息ID、发送者、时间、原始内容、类型标记 |
| `message_segments` | 消息段：文本、图片、@、回复等分段数据 |
| `images` | 图片记录：URL、本地路径、尺寸、下载状态 |
| `replies` | 回复关系：关联原消息ID |
| `forward_messages` | 合并转发：支持树形嵌套结构 |
| `at_mentions` | @提及记录 |
| `monitored_chats` | 监控目标管理 |

## 图片存储

图片按日期归档存储：

```
data/images/
├── 2026/
│   ├── 01/
│   │   └── 08/
│   │       ├── a1b2c3d4e5f6.jpg
│   │       └── f7e8d9c0b1a2.gif
│   └── 05/
│       └── ...
```

- 文件名基于内容 MD5 哈希，自动去重
- 保留图片原始格式，GIF 动图不会被转为静态 JPG
- 支持配置下载超时与文件大小上限

## 技术栈

- **框架**：[NcatBot](https://github.com/ncatbot/NcatBot) — QQ Bot 开发框架
- **协议端**：[NapCat](https://github.com/NapNeko/NapCatQQ) — 基于 NTQQ 的协议实现
- **ORM**：SQLAlchemy 2.0（异步）
- **数据库**：SQLite（aiosqlite）
- **HTTP**：aiohttp（异步图片下载）

## 常见问题

**Q: 项目中有两个 config.yaml，有什么区别？**

项目根目录的 `config.yaml` 是 NcatBot 框架的主配置文件，用于设置机器人 QQ 号、管理员等基础信息。`recorder/config.yaml` 是插件专属配置，用于设置监控目标、图片下载参数、合并转发解析深度等。

**Q: 数据库路径和图片路径是相对于哪里？**

插件配置中的 `database` 和 `images_dir` 路径都相对于插件工作目录（`recorder/data/qq_recorder/`），而不是项目根目录。例如配置 `database: data/recorder.db` 的实际路径为 `recorder/data/qq_recorder/data/recorder.db`。

**Q: `file_unique` 字段为什么总是 "0"？**

QQ 并不总是提供 `file_unique` 字段。本项目使用图片内容的 MD5 哈希作为去重依据，而非 `file_unique`。查询时请使用 MD5 字段进行图片去重。

**Q: `recorder/napcat/` 目录可以修改吗？**

不建议修改。`napcat/` 是第三方协议适配器组件，修改可能导致登录失败或协议异常。如需调整，请参考 NapCat 官方文档。

**Q: 升级后发现图片格式不对怎么办？**

v1.1.2 版本修复了图片格式检测逻辑。对于升级前的已有图片，可使用 `scripts/fix_image_extensions.py` 脚本进行批量修复：

```bash
python scripts/fix_image_extensions.py --dry-run  # 预览
python scripts/fix_image_extensions.py            # 执行
```

## 更新日志

### v1.1.3

- **修复**：消息中的换行符（`\n`、`\r`、`\t`）以原始形式存入数据库，导致命令输出和导出格式异常。现已在存储时将控制字符转义为字符串表示（`\n`→`\\n`、`\r`→`\\n`、`\t`→`\\t`），显示时还原原始文本。提供迁移脚本 `scripts/fix_newline_escaping.py` 修复已有数据。

### v1.1.2

- **修复**：处理图片时，所有图片都被存储为 `.jpg` 格式，导致一些动图（如 GIF）也变成静态 JPG。现已根据图片 URL 和实际格式正确保留原始扩展名（`jpg`、`jpeg`、`png`、`gif`、`bmp`、`webp`）。

## 许可证

MIT License

## 致谢

- [NcatBot](https://github.com/ncatbot/NcatBot) — QQ Bot 框架
- [NapCat](https://github.com/NapNeko/NapCatQQ) — QQ 协议端

---

由 [Arsvine Zhu](https://github.com/Arsvinezhu) 开发维护
