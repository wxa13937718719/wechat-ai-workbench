# 微信 AI 工作台

把原先散落在 Codex 技能、实验工作树里的微信自动回复代码，整理为独立的 Python 项目。包含聊天工作台、AI 回复守护进程、多模型路由、联系人规则和本机审计记录。

**整理版默认使用独立状态目录 `~/.wechat-ai`，以 shadow 模式启动。** 安装、初始化和打开控制台不会启动自动回复。旧项目和旧账号状态保持原样，迁移方法见 [本地迁移](docs/migration.md)。

## 包含什么

- 微信风格的聊天界面：会话、消息分页、引用、图片及 AI 侧栏。
- 独立守护进程：私聊关键词解锁、显式人工授权/撤销、群聊白名单、限流、失败重试和去重。
- AI 回复始终附加 `——该内容由AI生成`；手动发送不会解锁联系人。
- 文本、图片和表情理解；OpenAI 兼容接口、SiliconFlow、Ollama 的模型配置及路由。
- 配置变更预览、确认、审计与回滚；支持只生成草稿的沙盒。
- 可选 Windows 桌面壳和当前用户登录启动脚本。

## 快速开始

主要运行环境是 **Windows + Python 3.11+ + Docker Desktop Linux 引擎**。Web 控制台不需要桌面壳依赖。Linux/macOS 可安装核心包，真实微信收发依赖 `agent-wechat` 容器环境，尚未在本次整理中实测。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\wechat-ai.exe init
.\.venv\Scripts\wechat-ai.exe doctor
```

`doctor` 输出本机依赖与配置检查；缺少必要项时返回退出码 1。它不连接模型、不扫描聊天、不检查在线登录。

初始化生成 `~/.wechat-ai/daemon.json`、`siliconflow.json`、`persona.md`。在本机 `siliconflow.json` 填写模型密钥，或设置 `SILICONFLOW_API_KEY`。也可以在控制台中新增模型服务并配置路由；控制台保存的密钥使用系统凭据存储。

连接微信之前需要安装并手动登录后端：

```powershell
npm install -g @agent-wechat/cli@0.12.0
wx up
wx auth login
wx status
```

这里保留原项目验证过的后端版本 0.12.0，并不表示它是最新版。扫码登录需要本人操作，登录态由容器保存。完整前置条件见 [安装说明](docs/setup.md)。

启动控制台：

```powershell
.\.venv\Scripts\wechat-ai.exe console
```

在浏览器打开 <http://127.0.0.1:8765/conversations>。未配置后端时页面仍可打开，真实会话接口会报告后端不可用。

观察守护进程（初始配置是 shadow，不发送消息）：

```powershell
.\.venv\Scripts\wechat-ai.exe daemon
```

主动启用回复前，请阅读 [运行与停止](docs/operations.md)。需要打开桌面壳时先执行 `pip install -e ".[desktop]"`，再执行 `wechat-ai desktop`。

## 统一命令

| 命令 | 用途 |
| --- | --- |
| `wechat-ai init [--state-dir PATH]` | 创建缺失配置，不覆盖现有文件 |
| `wechat-ai doctor [--state-dir PATH]` | 只读检查本机依赖、配置和凭据是否存在 |
| `wechat-ai console [--state-dir PATH]` | 启动本机 Web 控制台 |
| `wechat-ai daemon [--state-dir PATH] [--status]` | 运行或查看守护进程 |
| `wechat-ai desktop [--state-dir PATH]` | 可选桌面壳 |
| `wechat-ai reply ...` | 原有消息工具，例如 `reply status`、`reply chats` |

全局可设置 `WECHAT_AI_STATE_DIR` 指向自己的运行目录。底层脚本仍保留在 `scripts/`，旧命令风格可以继续使用。

## 开发和验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
pwsh -NoProfile -File tests/test_bootstrap.ps1
pwsh -NoProfile -File tests/test_task_scripts.ps1
.\.venv\Scripts\python.exe scripts/check_publish.py
```

Python 测试使用临时状态和替身后端，不需要真实微信或模型密钥。GitHub Actions 在 Windows/Linux 上运行核心测试并构建安装包，Windows 额外运行 PowerShell dry-run。历史 Playwright 测试也保留在 `tests/ui/`，需 `npm ci` 后手动运行；涉及浏览器驱动时遵循当前用户的自动化权限规则。历史截图未发布，首次运行视觉测试需建立自己的虚构数据基线。

## 目录

```text
scripts/                 统一 CLI、守护进程、底层消息工具和 Windows 启动器
  wechat_ai_control/     FastAPI 控制台、规则、模型、镜像、审计及静态页面
config/                  不含密钥的配置示例
docs/                    安装、架构、迁移、运维、隐私和验证说明
tests/                   Python / PowerShell / 历史 UI 测试与虚构数据
.github/workflows/       自动测试与安装包验证
```

项目来源、保留内容及本次验证范围见 [整理记录](docs/consolidation.md)。这是非官方个人项目，真实收发依赖微信客户端版本和 `agent-wechat`；本次整理未向真实联系人发送测试消息。
