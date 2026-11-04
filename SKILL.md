---
name: wechat-ai-workbench
description: Operate this local WeChat AI workbench using its standalone CLI and isolated container backend.
---

# WeChat AI Workbench

This repository is independently installable. Read README.md and docs/operations.md.

Use `wechat-ai init`, `wechat-ai doctor`, and `wechat-ai console` for setup. The legacy console entry is `python scripts/wechat_ai_console.py --state-dir <directory> --host 127.0.0.1`.

- Default state is `~/.wechat-ai`; never silently switch to a live legacy directory.
- Do not send messages unless the user explicitly authorizes the send or enables auto-reply for the selected scope.
- All AI-authored sends use the helper and retain `——该内容由AI生成`.
- Manual sends never grant AI access. Contact keyword unlock and explicit owner authorization are separate audited actions.
- Use `send` without `--send` to preview. `poll --no-send-confirmation` suppresses unlock acknowledgments.
- Never commit local credentials, chat state, databases, screenshots or persona.
- Use the isolated Linux container, never the host WeChat window. Follow the user's current GUI automation rules for any desktop/browser interaction.
