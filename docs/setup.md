# 安装与配置

## 安装核心

建议使用项目自己的 Python 3.11 虚拟环境。`pip install -e .` 安装 Web 控制台和守护进程；`pip install -e ".[desktop]"` 额外安装 pywebview。项目不依赖 Codex 常驻运行。

`wechat-ai init --state-dir "绝对路径"` 会把所有默认运行文件定位到同一目录，已有文件不会覆盖。用同一 `--state-dir` 启动控制台和守护进程。也可在整个会话设置 `WECHAT_AI_STATE_DIR`。

模型默认使用原实现的 Qwen 文本/视觉模型，模型是否可用由服务商决定。可以修改本地配置或在模型页面设置服务与路由。

## 微信后端

原项目的已知配套环境：`@agent-wechat/cli` 0.12.0、镜像 `ghcr.io/thisnick/agent-wechat:0.12.0`、容器名 `agent-wechat`、Linux 微信英文界面、显示器 `:99`。首次启动和扫码登录通过 `wx up` / `wx auth login` 进行。

底层消息工具读取以下环境变量：

| 变量 | 默认 |
| --- | --- |
| `WECHAT_AI_STATE_DIR` | 用户主目录下 `.wechat-ai` |
| `AGENT_WECHAT_URL` | `http://localhost:6174` |
| `AGENT_WECHAT_CONTAINER` | `agent-wechat` |
| `AGENT_WECHAT_DISPLAY` | `:99` |
| `AGENT_WECHAT_SESSION` | `default` |
| `AGENT_WECHAT_TOKEN` | 未设置时读取 `~/.config/agent-wechat/token` |
| `SILICONFLOW_API_KEY` | 本机模型配置为空时可使用环境变量 |

消息镜像的 SQLCipher 读取器使用同一容器环境变量；容器内还需要已生成 `db_storage/db_keys.json` 和 SQLCipher 可执行程序。缺少数据库密钥时控制台明确报告不可用，不会导出密钥。

## 常见问题

- `doctor` 未通过：逐项查看 `checks`；它检查本机前置项，不能证明在线服务可用。只用 Ollama/其他已配置路由时可忽略遗留 SiliconFlow 密钥项。
- 空聊天或无历史消息：Linux 微信未必回填全部历史，新消息与历史消息应分别验证。
- 容器在线但消息发送未验证：先检查是否已经送达，不要盲目重发。
- 控制台模型密钥存储不可用：检查系统 keyring；不要把真实密钥写入源码。
- PowerShell 修改 JSON：推荐 PowerShell 7，或用 UTF-8 编辑器，避免 Windows PowerShell 的编码差异。

控制台仅支持 loopback 访问。可选 API token 面向直接 HTTP 客户端，历史前端不提供 token 登录界面；普通本机使用不设置该参数。
