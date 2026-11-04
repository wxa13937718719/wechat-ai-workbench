# 运行与停止

## 模式

`wechat-ai init` 生成 `daemonMode: shadow`。shadow 读取和分类消息，写本地观察日志，不发送或确认消息。它仍需要可用的微信后端，不是离线演示器。

只有本人决定开启时，才把本地 `daemon.json` 中 `daemonMode` 改成 `live`，再重启守护进程。私聊需要对方发解锁关键词或本人在控制台显式授权。群聊还需填写 `groupChatIds`；默认是空列表。

消息工具的 `poll` 默认可能发送解锁确认；若仅预览，应使用 `poll --no-send-confirmation`，不要把 `poll` 当作纯只读命令。`reply send` 只有带 `--send` 才发送。

## 查看与停止

`wechat-ai daemon --status` 查看 writer 和心跳。当前终端中的守护进程可用 Ctrl+C 停止；后台进程可在其状态目录创建 `daemon.stop`，循环结束时释放 writer 标记。再次启动前删除该 stop 文件。不要随意删除活动 writer 锁。

运行目录包含 `daemon.log`、`daemon.heartbeat`、`daemon.active`、`state.json`、`control/`；这些可能含聊天标识、待处理内容和操作记录。

## Windows 登录启动（可选）

先在项目根目录创建 `.venv` 并安装依赖、运行 `wechat-ai init`。检查脚本内容和 dry-run 后，再由本人选择执行：

```powershell
pwsh -NoProfile -File scripts/install-wechat-ai-task.ps1 -DryRun
pwsh -NoProfile -File scripts/install-wechat-ai-task.ps1
pwsh -NoProfile -File scripts/status-wechat-ai-task.ps1
pwsh -NoProfile -File scripts/uninstall-wechat-ai-task.ps1
```

安装写入当前用户的 Run 注册表项并创建隐藏 VBS 启动器，无需管理员；它会覆盖同名的旧启动项和桌面快捷方式，所以本次整理没有执行安装。安装使用 `.venv` 的解释器；若使用自定义状态目录，安装前保持 `WECHAT_AI_STATE_DIR` 为持久的用户环境变量。bootstrap 的 `-Config` 可以显式指定配置文件。

自动拉起 Docker、容器和登录二维码属于启动脚本的行为。该脚本保留原项目用途，不会由 `pip install`、`init` 或 `console` 自动调用。

## 限制

- 本地 6174/8765 端口不应公开暴露；后端 token 可控制真实微信会话。
- AI 风险分类有局限，资金、隐私和本人承诺仍需人工决定。
- 群聊、视觉识别和虚拟机仲裁依赖外部环境，需在受控联系人范围验证。
- 发送结果不确定时先查最近消息，确认未送达后再使用显式重试，避免重复。
