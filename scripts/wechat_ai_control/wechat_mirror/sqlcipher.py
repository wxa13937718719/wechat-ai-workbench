import json
import os
import subprocess
from pathlib import PurePosixPath
from typing import Callable


CONTAINER = os.environ.get("AGENT_WECHAT_CONTAINER", "agent-wechat")
DATABASE_PATHS = {
    "session.db": "session/session.db",
    "contact.db": "contact/contact.db",
    "message_0.db": "message/message_0.db",
}


class DatabaseUnavailable(RuntimeError):
    pass


class SchemaMismatch(RuntimeError):
    pass


def docker_runner(args, input_text=None):
    hidden = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        hidden = {
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            "startupinfo": startupinfo,
        }
    result = subprocess.run(
        ["docker", "exec"] + list(args),
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        **hidden,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"docker exec failed: {result.returncode}")
    return result.stdout


def _parameter_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _validate_select(sql: str) -> str:
    statement = str(sql or "").strip()
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if not statement.lower().startswith("select "):
        raise ValueError("SQLCipherReader accepts SELECT statements only")
    if ";" in statement:
        raise ValueError("SQLCipherReader accepts one statement at a time")
    return statement


class SqlCipherReader:
    def __init__(self, container: str = CONTAINER, runner: Callable = docker_runner):
        self.container = container
        self.runner = runner
        self.db_dir = None
        self.keys = None

    def _sanitize(self, message: str) -> str:
        safe = str(message or "")
        for key in (self.keys or {}).values():
            safe = safe.replace(str(key), "<redacted>")
        return safe

    def _load_keys(self) -> None:
        if self.db_dir and self.keys:
            return
        try:
            key_file = self.runner([
                self.container,
                "sh",
                "-lc",
                "find /home/wechat/xwechat_files -path '*/db_storage/db_keys.json' | head -1",
            ]).strip()
            if not key_file:
                raise DatabaseUnavailable("WeChat database key file was not found")
            payload = json.loads(self.runner([self.container, "cat", key_file]))
            keys = payload.get("keys") or {}
            self.db_dir = str(PurePosixPath(key_file).parent)
            self.keys = keys
        except DatabaseUnavailable:
            raise
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            raise DatabaseUnavailable(f"WeChat database keys are unavailable: {self._sanitize(exc)}") from exc

    def query(self, db_name: str, sql: str, params: tuple = ()) -> list[dict]:
        if db_name not in DATABASE_PATHS:
            raise ValueError(f"unsupported WeChat database: {db_name}")
        statement = _validate_select(sql)
        self._load_keys()
        key = (self.keys or {}).get(db_name)
        if not key:
            raise DatabaseUnavailable(f"key missing for {db_name}")

        db_path = f"{self.db_dir}/{DATABASE_PATHS[db_name]}"
        parameter_lines = [".parameter init"]
        parameter_lines.extend(
            f".parameter set ?{index} {_parameter_literal(value)}"
            for index, value in enumerate(params, start=1)
        )
        script = "\n".join([
            f'PRAGMA key = "x\'{key}\'";',
            "PRAGMA cipher_compatibility = 4;",
            ".mode json",
            *parameter_lines,
            statement + ";",
            "",
        ])
        try:
            output = self.runner(["-i", self.container, "sqlcipher", db_path], input_text=script)
        except (OSError, RuntimeError) as exc:
            message = self._sanitize(exc)
            if "no such table" in message.lower() or "no such column" in message.lower():
                raise SchemaMismatch(message) from exc
            raise DatabaseUnavailable(f"WeChat database query failed: {message}") from exc

        lowered = output.lower()
        if "no such table" in lowered or "no such column" in lowered:
            raise SchemaMismatch(self._sanitize(output.strip()))
        start = output.find("[")
        if start < 0:
            if output.strip() and "error" in lowered:
                raise DatabaseUnavailable(self._sanitize(output.strip()))
            return []
        try:
            value = json.loads(output[start:])
        except json.JSONDecodeError as exc:
            raise DatabaseUnavailable("WeChat database returned invalid JSON") from exc
        if not isinstance(value, list):
            raise DatabaseUnavailable("WeChat database returned a non-list result")
        return value
