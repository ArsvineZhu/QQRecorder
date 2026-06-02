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
- **表情识别** — 自动区分普通图片与动画表情/贴纸，支持三重检测（字段、文本、启发式）和历史数据回溯
- **应用分享识别** — 自动识别 QQ 小程序、图文分享、位置分享等 JSON 格式消息（B站视频、网易云音乐等）并解析结构化元数据
- **统计面板** — 查看消息数、图片数等统计信息
- **增量备份** — 内置定时备份 SQLite 与图片，支持按天全量 + 日内增量
- **灵活配置** — 支持全量监控或指定群/私聊监控
- **异步存储** — 基于 SQLAlchemy + aiosqlite 的异步数据库，不阻塞消息处理
- **可选回复插件** — 新增 `qq_grok_reply` 平行插件，可在命中 @bot、前缀或私聊触发时基于 `recorder.db` 上下文生成回复，并将行为写入 `reply_traces`

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

仓库提供三类可提交的示例配置：

- 根配置：[config.example.yaml](D:/Dev/PythonProjects/QQRecorder/config.example.yaml)
- 记录插件：[plugins/qq_recorder/config.example.yaml](D:/Dev/PythonProjects/QQRecorder/plugins/qq_recorder/config.example.yaml)
- 回复插件：[plugins/qq_grok_reply/config.example.yaml](D:/Dev/PythonProjects/QQRecorder/plugins/qq_grok_reply/config.example.yaml)

实际运行时请分别使用本地真实文件：

- 根配置：`config.yaml`
- 记录插件：`plugins/qq_recorder/config.yaml`
- 回复插件：`plugins/qq_grok_reply/config.yaml`

这些真实配置都已加入 `.gitignore`，用于保存你自己的 QQ 号、token、本地路径和 AI Key 配置。

可先从示例生成本地配置：

```bash
copy config.example.yaml config.yaml
copy plugins\qq_recorder\config.example.yaml plugins\qq_recorder\config.yaml
copy plugins\qq_grok_reply\config.example.yaml plugins\qq_grok_reply\config.yaml
```

然后编辑插件自己的配置文件。`qq_recorder` 配置写在 `plugins/qq_recorder/config.yaml`：

```yaml
# 监控模式：true = 记录所有消息，false = 仅记录 targets 中的目标
monitor_all: true
# 监控目标（monitor_all 为 false 时生效）
targets:
  groups: ["群号1", "群号2"]    # 要监控的群号列表
  private: ["QQ号1"]            # 要监控的私聊对象 QQ 号列表
storage:
  database: data/recorder.db    # 数据库路径（相对于插件工作目录）
  images_dir: data/images       # 图片存储目录（相对于插件工作目录）
  lock_retry:
    enabled: true               # 启用 SQLite 锁冲突重试
    max_retries: 5              # 最大重试次数
    base_delay_ms: 50           # 首次退避毫秒（指数退避）
image:
  download: true                # 是否下载图片
  timeout: 30                   # 下载超时时间（秒）
  max_file_size: 52428800       # 最大文件大小（字节），默认 50MB
processing:
  max_inflight: 48              # 消息处理并发上限（背压）
  image_download_concurrency: 4 # 图片下载并发上限
forward:
  max_depth: 10                 # 合并转发消息最大递归深度
  parse_content: true           # 是否解析转发内容
backup:
  enabled: true                 # 是否启用定时备份
  output_dir: data/backups      # 备份输出目录（相对于插件工作目录）
  keep_last: 7                  # 保留最近 N 个全量链
  full_interval_days: 7         # 每隔 N 天执行一次全量备份
  full_time: "03:00"            # 全量备份时间（HH:MM）
  incremental_times:            # 每日增量备份时间列表
    - "12:00"
    - "18:00"
```

如需启用配套回复插件 `qq_grok_reply`，编辑 `plugins/qq_grok_reply/config.yaml`：

```yaml
enabled: false
recorder_db: "D:/absolute/path/to/recorder.db"  # 必须填写 QQRecorder 实际使用的绝对路径
monitor_all: false
targets:
  groups: ["群号1"]
  private: ["QQ号1"]
trigger:
  private_enabled: true
  group_enabled: true
  prefixes: ["/ask", "/ai", "grok"]
  allow_at: true
  allow_reply_to_bot: false
  ignore_self: true
  ignore_recorder_command: true
model:
  provider: ncatbot_ai
  model: ""                        # 留空时使用 AI 适配器的 completion_model
  temperature: 0.7
  max_tokens_group: 220
  max_tokens_private: 420
  timeout_sec: 12
  retries: 1
  llm_concurrency: 2
send:
  group_use_reply_segment: true
  group_at_sender: false
  group_max_chars_per_part: 250
  private_max_chars_per_part: 500
  group_max_parts: 2
  private_max_parts: 3
```

如果要真正接入模型，还需要在根 `config.yaml` 的 `adapters` 中配置 NcatBot 的 `ai` 适配器，例如：

```yaml
adapters:
  - type: ai
    platform: ai
    enabled: true
    config:
      api_key: ""                       # 建议改用环境变量，例如 DEEPSEEK_API_KEY
      base_url: "https://api.deepseek.com"
      completion_model: "deepseek-chat"
      timeout: 120.0
      max_tokens: null
```

`qq_grok_reply` 是与 `qq_recorder` 平行加载的独立插件：

- 只读 `qq_recorder` 已写入的事实表，不修改 `qq_recorder` 主记录链路
- 只在显式命中私聊、前缀或 `@bot` 条件时回复
- 将调试与发送结果写入同库中的 `reply_traces` 表
- `recorder_db` 必须填 **QQRecorder 实际解析后的绝对路径**；不要复用相对路径猜测

## 使用

### 启动

```bash
uv run ncatbot run
```

### 命令

在群聊或私聊中发送以下命令：

| 命令 | 说明 |
|------|------|
| `/recorder stats` | 查看当前会话的消息统计 |
| `/recorder recent [N]` | 查看最近 N 条消息（默认 5，最多 20） |
| `/recorder search <关键词>` | 搜索包含关键词的消息（最多 10 条） |

> 命令前缀支持：`recorder`、`/recorder`、`r`、`/r`（不区分大小写）

### `qq_grok_reply` 触发规则

- 私聊：命中 `targets.private` 且 `private_enabled=true` 时默认可回复
- 群聊：仅在 `@bot` 或前缀（默认 `/ask`、`/ai`、`grok`）命中时回复
- 普通群聊消息、`/recorder ...` 命令、自发消息默认不触发
- 关闭插件只需将 `plugins/qq_grok_reply/config.yaml` 中的 `enabled` 设回 `false`

### 备份工具

备份由插件自动执行；如需查看或恢复归档，可使用：

```bash
python scripts/backup_tool.py list --dir data/qq_recorder/data/backups
python scripts/backup_tool.py restore \
  --archive <backup.zip> \
  --db-path <recorder.db> \
  --images-dir <images-dir>
```

全量归档包含 SQLite 一致性快照和全部图片。增量归档也会始终包含一份
SQLite 一致性快照，图片则按上一次归档后的新增、变更和删除差异记录；
恢复某个增量归档时，它依赖的父归档链必须仍在同一备份目录中。恢复前请先停止
正在使用目标数据库或图片目录的机器人进程。

## 项目结构

```
QQRecorder/
├── README.md                   # 项目文档
├── AGENTS.md                   # AI 辅助开发知识库
├── pyproject.toml              # Python 项目配置与依赖
├── config.example.yaml         # 可提交的 NcatBot 全局配置示例
├── scripts/
│   ├── export_db.py            # 数据库导出与查询工具
│   ├── backup_tool.py          # 备份归档查看与恢复工具
│   ├── fix_image_extensions.py # 图片格式修复工具（v1.1.2 迁移用）
│   ├── fix_newline_escaping.py # 换行符转义修复工具（v1.1.3 迁移用）
│   ├── fix_image_duplicates.py # 图片重复记录修复工具（v1.2.4 迁移用）
│   ├── migrate_add_is_sticker.py  # 表情检测数据库迁移（v1.3.0）
│   ├── migrate_add_app_share.py # 应用分享数据库迁移（v1.3.2）
│   └── backfill_sticker_flags.py  # 历史图片表情标记回填（v1.3.0）
├── .pre-commit-config.yaml     # Git pre-commit 钩子（ruff check + format）
└── recorder/
    ├── config.yaml             # 插件运行配置
    ├── napcat/                 # NapCat 协议端（第三方组件，请勿修改）
    ├── data/
    │   └── qq_recorder/        # 运行时数据
    │       ├── recorder.db     # SQLite 数据库
    │       └── images/         # 图片存储目录
    └── plugins/
        └── qq_recorder/        # 核心插件代码
            ├── config.example.yaml # 记录插件配置示例
            ├── plugin.py        # 插件入口，生命周期与事件注册
            ├── events.py        # 事件转换、命令检测、日志格式化
            ├── commands.py      # 命令处理（stats/recent/search）
            ├── processors.py    # 消息处理管道（消息/转发/图片）
            ├── config.py        # 配置模型与校验
            ├── models.py        # SQLAlchemy 数据模型
            ├── storage.py       # 异步数据库操作
            ├── message_parser.py # 消息段解析
            ├── image_handler.py  # 图片下载与格式检测
            ├── sticker_detector.py # 动画表情/贴纸三重检测
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

### migrate_add_is_sticker.py

v1.3.0 表情检测数据库迁移工具。此脚本为 `images` 表添加 `is_sticker`（布尔标记）和 `sticker_confidence`（置信度 0.0~1.0）列，用于存储三重检测结果。

```bash
# 预览修改（不实际执行）
python scripts/migrate_add_is_sticker.py --dry-run

# 执行迁移
python scripts/migrate_add_is_sticker.py
```

### backfill_sticker_flags.py

v1.3.0 历史图片表情标记回填工具。对数据库中已有的图片记录运行检测算法并回填 `is_sticker` 和 `sticker_confidence` 字段。

```bash
# 预览回填结果（不写入数据库）
python scripts/backfill_sticker_flags.py --dry-run

# 执行回填（所有记录）
python scripts/backfill_sticker_flags.py

# 指定 ID 范围（断点续传）
python scripts/backfill_sticker_flags.py --start-id 100 --end-id 200
```

### fix_image_duplicates.py

v1.2.4 图片重复记录修复工具。旧版本中图片查询使用 `file_unique` 字段，但 QQ 经常返回 `"0"`，导致同一消息下多张图片产生 `MultipleResultsFound` 异常。此脚本去重并重建 images 表，添加 `(message_id, file_url)` 唯一约束。

```bash
# 预览修改（不实际执行）
python scripts/fix_image_duplicates.py --dry-run

# 执行修复
python scripts/fix_image_duplicates.py
```

### migrate_add_app_share.py

v1.3.2 应用分享数据库迁移工具。为 `messages` 表添加 `has_app_share` 布尔列，创建 `app_shares` 表用于存储 QQ 小程序、图文分享、位置分享等 JSON 格式消息的结构化元数据。

```bash
# 预览修改（不实际执行）
python scripts/migrate_add_app_share.py --dry-run

# 执行迁移
python scripts/migrate_add_app_share.py
```

## 数据模型

| 表名 | 说明 |
|------|------|
| `messages` | 消息主表：消息ID、发送者、时间、原始内容、类型标记 |
| `message_segments` | 消息段：文本、图片、@、回复等分段数据 |
| `images` | 图片记录：URL、本地路径、尺寸、下载状态、是否表情、置信度 |
| `app_shares` | 应用分享：应用名称、标题、描述、链接、原始JSON数据 |
| `replies` | 回复关系：关联原消息ID |
| `forward_messages` | 合并转发：支持树形嵌套结构 |
| `at_mentions` | @提及记录 |
| `monitored_chats` | 监控目标管理 |
| `reply_traces` | `qq_grok_reply` 的回复决策、模型摘要、发送结果与错误码 |

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
- 同 URL 且本地文件存在时会直接复用本地路径，跳过重复下载
- 保留图片原始格式，GIF 动图不会被转为静态 JPG
- 下载采用流式读取，超过大小上限会立即中断
- 支持配置下载超时与文件大小上限（默认 50MB）

## 技术栈

- **框架**：[NcatBot](https://github.com/ncatbot/NcatBot) — QQ Bot 开发框架
- **协议端**：[NapCat](https://github.com/NapNeko/NapCatQQ) — 基于 NTQQ 的协议实现
- **ORM**：SQLAlchemy 2.0（异步）
- **数据库**：SQLite（aiosqlite）
- **HTTP**：aiohttp（异步图片下载）

## 常见问题

**Q: 插件配置放在哪里？**

全局配置放在项目根目录的本地 `config.yaml`。插件配置分别放在各自目录下的本地配置文件：

- `plugins/qq_recorder/config.yaml`
- `plugins/qq_grok_reply/config.yaml`

仓库跟踪的是对应的 `*.example.yaml`。如果确实需要统一覆盖，NcatBot 仍支持在全局 `config.yaml` 的 `plugin.plugin_configs.*` 中追加高优先级覆盖，但本项目默认不再把插件主配置放在全局文件里。

**Q: 数据库路径和图片路径是相对于哪里？**

插件配置中的 `database` 和 `images_dir` 路径都相对于插件工作目录（`recorder/data/qq_recorder/`），而不是项目根目录。例如配置 `database: data/recorder.db` 的实际路径为 `recorder/data/qq_recorder/data/recorder.db`。

`qq_grok_reply.recorder_db` 例外：它必须填写 **QQRecorder 启动后实际使用的 `recorder.db` 绝对路径**，因为回复插件与记录插件不是同一个 workspace。

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

**Q: 如何区分普通图片和动画表情/贴纸？**

项目使用三重检测机制：
1. **元数据检测**（主检测）— 分析 QQ 消息段中的 `sub_type` 字段：`0`=普通图片，`1`=动画表情，`7`=QQ商城贴纸，`13`=emoji 表情。置信度 0.95。
2. **文本检测** — 在 CQ 码原始消息中匹配 `sub_type=1` 模式。置信度 0.95。
3. **启发式检测**（回退）— 检测 GIF/WebP 格式及小文件（<100KB）。置信度 0.7-0.85。

最终置信度 ≥ 0.7 则标记为表情，存储在 `images.is_sticker` 字段。

## 更新日志

### v1.5.0

- **新增**：消息处理并发闸门（`processing.max_inflight`），高并发刷屏时启用背压，避免任务无限堆积
- **新增**：图片下载全局并发限制（`processing.image_download_concurrency`）
- **新增**：SQLite 锁冲突重试配置（`storage.lock_retry`），写路径遇到 `database is locked` 时指数退避重试
- **优化**：图片下载改为流式读取并按阈值即时截断，降低大文件峰值内存压力
- **优化**：图片大小上限默认调整为 **50MB**（`52428800`）
- **优化**：图片支持 URL 快速命中复用；同 URL 且本地文件存在时跳过重复下载

### v1.4.0

- **新增**：定时全量/增量备份，归档 SQLite 一致性快照与下载图片，支持配置全量间隔、每日执行时间和保留链数
- **新增**：`scripts/backup_tool.py` — 查看备份归档并按全量/增量父链恢复数据库与图片
- **修复**：增量归档始终携带 SQLite 快照，避免 WAL 模式下仅主库文件未变化时漏掉新消息
- **修复**：恢复时数据库与图片目录采用双目标回滚，避免其中一步失败后留下半恢复状态

### v1.3.2

- **新增**：QQ 应用分享消息（JSON 格式）的解析与存储，支持识别三种类型：
  - QQ 小程序卡片（B站等）— 提取标题、链接
  - QQ 图文分享（豆包AI视频等）— 提取标题、来源链接
  - QQ 位置分享 — 提取位置描述
- **新增**：`AppShare` 数据表（app_name、title、description、url、prompt、raw_data）
- **新增**：`scripts/migrate_add_app_share.py` — 为 messages 表添加 `has_app_share` 列并创建 app_shares 表
- **增强**：消息日志格式显示分享来源，如 `[share(QQ图文)]`
- **变更**：`messages` 数据模型新增 `has_app_share`（布尔）字段

### v1.3.1

- **配置规范化**：将 `ruff` 从运行时依赖移至开发依赖；修正 `authors` 字段符合 PEP 621；移除被 `license` 字段取代的许可证分类器
- **类型检查清理**：移除 `storage.py`（22处）、`image_handler.py`（6处）、`scripts/`（2处）中的 `# pyright: ignore` 抑制注释，改用正确的类型注解
- **代码质量**：全项目 Ruff 检查通过（65处自动修复 + 35处手动修复），统一代码格式
- **新增**：`pre-commit` 开发依赖与 `.pre-commit-config.yaml`，提交时自动运行 `ruff check` + `ruff format`
- **文档**：全面刷新根目录和插件级 `AGENTS.md` 知识库，新增代码映射、命令速查

### v1.3.0

- **新增**：动画表情/贴纸检测功能，三重检测算法（元数据 `sub_type` 字段 → CQ码文本匹配 → 启发式格式/大小）
- **新增**：`plugins/qq_recorder/sticker_detector.py` — 检测引擎核心
- **新增**：`plugins/qq_recorder/tests/test_sticker_detection.py` — 8 个单元测试
- **新增**：`scripts/migrate_add_is_sticker.py` — 为 images 表添加 `is_sticker`/`sticker_confidence` 列
- **新增**：`scripts/backfill_sticker_flags.py` — 历史图片表情标记回填脚本
- **增强**：`stats` 命令增加表情数量统计
- **变更**：`images` 数据模型新增 `is_sticker`（布尔）和 `sticker_confidence`（浮点）字段

### v1.2.4

- **重构**：拆分臃肿的 `plugin.py`（328行→73行），提取为独立模块：
  - `events.py` — 事件转换、命令检测、日志格式化（纯函数）
  - `commands.py` — 命令处理（stats/recent/search）
  - `processors.py` — 消息处理管道（消息/转发/图片）
- **修复**：合并转发消息含空 ID 时导致 `ValueError` 崩溃，现过滤空白 ID
- **修复**：图片查询因 `file_unique` 为 `"0"` 产生 `MultipleResultsFound` 异常，现改用 `file_url` 匹配
- **移除**：多余的 `main.py` 入口文件，`manifest.toml` 直接指向 `plugin.py`
- **新增**：`scripts/fix_image_duplicates.py` 迁移脚本，为 images 表添加唯一约束并去重

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
