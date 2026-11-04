import argparse
import ctypes
import os
import sys
from pathlib import Path

from wechat_ai_paths import state_dir

from wechat_ai_control.process_supervisor import ConsoleStartError, ensure_console


ERROR_ALREADY_EXISTS = 183


def pythonw_executable() -> Path:
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        candidate = executable.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return executable


def acquire_single_instance(name: str):
    if os.name != "nt":
        return object()
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise OSError("unable to create desktop instance mutex")
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def release_single_instance(handle) -> None:
    if os.name == "nt" and handle:
        ctypes.windll.kernel32.ReleaseMutex(handle)
        ctypes.windll.kernel32.CloseHandle(handle)


def console_command(state_dir: Path, host: str, port: int) -> list[str]:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("desktop console must use a loopback host")
    script = Path(__file__).resolve().with_name("wechat_ai_console.py")
    return [
        str(pythonw_executable()),
        str(script),
        "--state-dir",
        str(state_dir),
        "--host",
        host,
        "--port",
        str(port),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", default=str(state_dir()))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    handle = acquire_single_instance("Local\\WeChatAiDesktop")
    if handle is None:
        return 0
    try:
        state_dir = Path(args.state_dir).expanduser().resolve()
        health_url = f"http://{args.host}:{args.port}/api/health"
        ensure_console(
            health_url,
            console_command(state_dir, args.host, args.port),
            pid_path=state_dir / "console.pid",
            timeout_seconds=15,
        )

        import webview

        webview.create_window(
            "微信",
            f"http://{args.host}:{args.port}/conversations?desktop=1",
            width=1280,
            height=800,
            min_size=(960, 640),
            confirm_close=False,
        )
        webview.start(debug=False)
        return 0
    except ConsoleStartError as exc:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, str(exc), "微信启动失败", 0x10)
        return 1
    finally:
        release_single_instance(handle)


if __name__ == "__main__":
    raise SystemExit(main())
