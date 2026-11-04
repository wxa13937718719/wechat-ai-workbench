"""Check staged (or tracked) source without printing any matched credential."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess


PRIVATE_NAMES = {"daemon.json", "siliconflow.json", "state.json", "persona.md", "login-status.json", "login-qr.png", "db_keys.json", "token"}
PRIVATE_PARTS = {".planning", ".local", ".venv", "node_modules", ".ui-test-state"}
SECRET_PATTERNS = [
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{30,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def check_files(root, filenames, read_bytes=None):
    problems = []
    for filename in filenames:
        path = PurePosixPath(filename.replace("\\", "/"))
        name = path.name.lower()
        if (name in PRIVATE_NAMES or PRIVATE_PARTS.intersection(path.parts)
                or name.endswith((".log", ".sqlite", ".sqlite3", ".db", ".pem", ".key", ".pid"))
                or name.startswith(".env") and name != ".env.example"):
            problems.append(f"{filename}: runtime/private file")
            continue
        data = read_bytes(filename) if read_bytes else (Path(root) / filename).read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            problems.append(f"{filename}: credential-like content (value redacted)")
        if len(data) > 2_000_000:
            problems.append(f"{filename}: unexpectedly large file")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracked", action="store_true", help="scan all tracked files (CI)")
    args = parser.parse_args()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    command = ["git", "ls-files", "-z"] if args.tracked else ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    filenames = [item for item in subprocess.check_output(command, cwd=root).decode("utf-8").split("\0") if item]
    reader = None if args.tracked else lambda name: subprocess.check_output(["git", "show", f":{name}"], cwd=root)
    problems = check_files(root, filenames, read_bytes=reader)
    for problem in problems:
        print(problem)
    print(f"Checked {len(filenames)} files; {len(problems)} problems. Credential values are never printed.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
