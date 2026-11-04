import json
import ntpath
import os
import signal
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class ConsoleStartError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    executable: str
    command_line: str


@dataclass(frozen=True)
class ProcessStatus:
    url: str
    healthy: bool
    started: bool
    pid: int | None = None


def _normalize_windows_path(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(str(value or "").strip('"')))


def process_matches_command(info: ProcessInfo, command: Sequence[str]) -> bool:
    if len(command) < 2:
        return False
    expected_executable = _normalize_windows_path(command[0])
    expected_script = _normalize_windows_path(command[1])
    actual_executable = _normalize_windows_path(info.executable)
    normalized_line = _normalize_windows_path(info.command_line)
    return actual_executable == expected_executable and expected_script in normalized_line


def windows_process_lookup(pid: int) -> ProcessInfo | None:
    if os.name != "nt" or pid <= 0:
        return None
    command = (
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId = "
        + str(int(pid))
        + "\" -ErrorAction SilentlyContinue; "
        "$p | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    text = result.stdout.strip()
    if result.returncode != 0 or not text:
        return None
    payload = json.loads(text)
    return ProcessInfo(
        pid=int(payload["ProcessId"]),
        executable=str(payload.get("ExecutablePath") or ""),
        command_line=str(payload.get("CommandLine") or ""),
    )


def health_probe(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("status") == "ok"
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def spawn_hidden(command: Sequence[str]):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    return subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )


def stop_process(pid: int) -> None:
    os.kill(int(pid), signal.SIGTERM)


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (FileNotFoundError, TypeError, ValueError):
        return None


def ensure_console(
    url: str,
    command: Sequence[str],
    *,
    pid_path: str | Path,
    timeout_seconds: float = 10,
    poll_interval: float = 0.1,
    probe: Callable[[str], bool] = health_probe,
    spawn: Callable[[Sequence[str]], object] = spawn_hidden,
    process_lookup: Callable[[int], ProcessInfo | None] = windows_process_lookup,
    stop_process: Callable[[int], None] = stop_process,
) -> ProcessStatus:
    pid_file = Path(pid_path)
    if probe(url):
        return ProcessStatus(url=url, healthy=True, started=False, pid=_read_pid(pid_file))

    existing_pid = _read_pid(pid_file)
    if existing_pid is not None:
        info = process_lookup(existing_pid)
        if info is not None and process_matches_command(info, command):
            stop_process(existing_pid)
        pid_file.unlink(missing_ok=True)

    pid_file.parent.mkdir(parents=True, exist_ok=True)
    process = spawn(command)
    pid = int(getattr(process, "pid"))
    pid_file.write_text(str(pid), encoding="ascii")

    deadline = time.monotonic() + max(0, timeout_seconds)
    while True:
        if probe(url):
            return ProcessStatus(url=url, healthy=True, started=True, pid=pid)
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0, poll_interval))

    terminate = getattr(process, "terminate", None)
    if callable(terminate):
        terminate()
    pid_file.unlink(missing_ok=True)
    raise ConsoleStartError(f"console did not become healthy at {url} within {timeout_seconds:g}s")
