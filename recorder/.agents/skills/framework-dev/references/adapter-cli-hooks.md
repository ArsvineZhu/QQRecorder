# 适配器 CLI 配置钩子参考

## 机制概览

`BaseAdapter.cli_configure()` 是各适配器为 CLI 命令提供的交互式配置入口：

- **调用方**：`ncatbot adapter`（`ncatbot/cli/commands/adapter.py`）和 `ncatbot init`（通过 `adapter_interactive()`）
- **返回值**：`Dict[str, Any]`，序列化到 `config.yaml` 的 `adapters[].config`
- **默认实现**：返回空字典

## 实现位置

| 适配器 | 文件 | 方法 |
|--------|------|------|
| NapCat | `ncatbot/adapter/napcat/adapter.py` | `NapCatAdapter.cli_configure()` |
| Bilibili | `ncatbot/adapter/bilibili/adapter.py` | `BilibiliAdapter.cli_configure()` |
| GitHub | `ncatbot/adapter/github/adapter.py` | `GitHubAdapter.cli_configure()` |
| Lark | `ncatbot/adapter/lark/adapter.py` | `LarkAdapter.cli_configure()` |
| Base | `ncatbot/adapter/base.py` | `BaseAdapter.cli_configure()` |

## 智能跳过设计

各适配器应根据用户的前置选择，跳过不必要的交互环节：

### NapCat

```text
询问自动安装?
  ├─ Yes → 执行安装 → 直接返回默认值（ws/webui），由 configure_all() 启动时自动配置
  └─ No  → 逐项交互输入 ws_uri / ws_token / webui_uri / webui_token / enable_webui
```

设计原理：自动安装时，NapCat 由框架本地管理，`NapCatLauncher` 启动前调用 `NapCatConfigManager.configure_all()` 写入正确的 WS/WebUI 配置，因此 CLI 阶段无需用户手动输入。

### Bilibili

```text
询问扫码登录?
  ├─ Yes → 弹出二维码 → 扫码获取凭据 → 跳过 sessdata 等手动输入
  └─ No  → 逐项输入 sessdata / bili_jct / buvid3 / dedeuserid / ac_time_value
→ 无论哪种方式，继续配置 live_rooms / enable_session
```

设计原理：扫码登录已自动获取全部凭据，无需再手动输入同样的字段。

### GitHub / Lark

当前无跳过逻辑（所有字段均需用户输入或使用默认值）。

## adapter 命令与 init 命令中的适配器管理

`ncatbot adapter` 和 `ncatbot init` 均使用 `adapter_interactive()`（`ncatbot/cli/commands/adapter.py`）：

1. `_build_items()` 从 `adapter_registry.discover()` 和已有 `config.yaml` 合并构建列表（排除 mock）
2. 进入副屏（alternate screen）交互界面：↑/↓ 导航、空格切换启用/禁用、Enter 调用 `cli_configure()`、q 保存退出
3. 退出后收集结果写入 `config.yaml` 的 `adapters` 列表

`ncatbot init` 调用时传入 `default_first=True`，无已有配置时默认启用第一个适配器。

## 新增适配器的 cli_configure 实现规则

1. 使用 `import click` 延迟导入（CLI 可选依赖）
2. 先打印适配器名称 header（`click.style(..., fg="cyan", bold=True)`）
3. 可提供前置选择（安装/扫码等），据此跳过后续不必要的输入
4. 返回值的 key 必须与对应 `*Config` 模型的字段名一致

## 配置安全

NapCat 适配器的 `ws_token` / `webui_token` 在框架启动时会经过 `strong_password_check()` 校验。

- 校验白名单包含 URI 安全字符 + 常见密码特殊字符（`@#$%^&+=` 等）
- 生成 Token 仍仅使用 URI 安全子集
- 详见 `ncatbot/utils/config/security.py`

## 相关文档

- 用户指南：`docs/docs/notes/guide/2. 适配器/`（各适配器使用指南）
- 参考文档：`docs/docs/notes/reference/7. 适配器/README.md`（BaseAdapter 接口）
- CLI 参考：`docs/docs/notes/reference/10. CLI/1. 命令参考.md`
- 配置安全：`docs/docs/notes/guide/6. 配置管理/1. 配置安全.md`
