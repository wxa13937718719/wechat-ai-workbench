# 验证记录 · 2026-11-05

## 本地已执行

| 检查 | 结果 |
| --- | --- |
| 在全新 Python 3.11 虚拟环境 `pip install -e ".[dev]"` | 成功 |
| `python -m pip check` | 无损坏依赖 |
| `python -m unittest discover -s tests -v` | **290 项全部通过** |
| 独立 Python 3.14.3 虚拟环境安装与全量测试 | **另一次 290 项全部通过** |
| `tests/test_bootstrap.ps1` | 隔离 dry-run 通过，无状态/日志写入 |
| `tests/test_task_scripts.ps1` | 启动安装 dry-run 通过，未写注册表 |
| 10 个前端模块及 Playwright 配置的 Node 语法检查 | 11 项通过 |
| `python -m build` | sdist 和 wheel 构建成功 |
| `python scripts/smoke_wheel.py` | 在源码目录外建立另一环境，安装 wheel，CLI 初始化、health、聊天页和模型样式均通过 |
| 产物内容检查 | 包含 8 个模板、21 份静态资源；未带入运行状态和密钥 |
| 待上传文件与本机模型/backend 实际凭据比对 | 零匹配，未打印凭据 |

新环境使用 FastAPI 0.162.0、Starlette 1.10.0、Pydantic 2.14.2、httpx 0.28.1、Uvicorn 0.54.0。Starlette 对测试客户端使用 httpx 发出弃用提示，不影响当前测试；后续升级时需关注 httpx2 迁移。

## 修复的回归

- 通过显式配置目录启动时，缺省路径应跟随该目录，避免串用旧 live 状态。
- 初始化应保留已有配置和密钥，不自动创建聊天队列。
- bootstrap dry-run 不应创建运行状态、日志和心跳。
- 本地模型 key 为空时，守护进程应采用 `SILICONFLOW_API_KEY`。
- 审计记录时间相同时，仍按最近插入优先显示。
- 发布检查应阻止运行状态与疑似凭据进入 Git。

上述行为先通过失败测试复现，再修复。首轮旧版 281 项测试中的两项缺少文档引用问题已改为当前项目文档。

## 未执行

本次没有使用真实账号向联系人发消息，没有重新登录微信，没有调用付费模型，也没有切换旧开机启动或守护进程。未执行历史 Playwright/视觉截图测试。真实收发、云模型连通性和 VM 仲裁需在本人选择启用范围后分别验收。

远端 Windows/Linux、Python 3.11/3.14 验证由仓库 Actions 执行；以对应提交的运行结果为准。首次上传已触发 [Actions 检查](https://github.com/wxa13937718719/wechat-ai-workbench/actions/runs/41878563401)，交付记录更新时仍在等待 GitHub runner，尚无远端测试结论。本次补记仅改文档，不重复触发检查。
