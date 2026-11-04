"""Local state is separate from source code and from the original Codex skill."""
import os
from pathlib import Path


STATE_FILES = {
    "qrImagePath": "login-qr.png",
    "activeWriterPath": "daemon.active",
    "stopFlagPath": "daemon.stop",
    "heartbeatPath": "daemon.heartbeat",
    "logPath": "daemon.log",
    "statePath": "state.json",
    "siliconflowConfigPath": "siliconflow.json",
    "personaPath": "persona.md",
    "controlRuntimePath": "control/runtime.json",
    "controlConfigPath": "control/runtime.json",
    "controlRulesPath": "control/rules.json",
}


def state_dir():
    return Path(os.environ.get("WECHAT_AI_STATE_DIR", str(Path.home() / ".wechat-ai"))).expanduser().resolve()


def state_paths(directory):
    root = Path(directory).expanduser().resolve()
    return {key: str(root / filename) for key, filename in STATE_FILES.items()}
