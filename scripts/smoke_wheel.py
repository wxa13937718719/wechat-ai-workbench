"""Install the built wheel away from source and verify its actual usable contents."""
import os
from pathlib import Path
import subprocess
import tempfile
import venv


def main():
    root = Path(__file__).resolve().parents[1]
    wheel = next((root / "dist").glob("*.whl"))
    with tempfile.TemporaryDirectory(prefix="wechat-wheel-") as directory:
        temporary = Path(directory)
        environment = temporary / "env"
        venv.EnvBuilder(with_pip=True).create(environment)
        binary = environment / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        cli = binary / ("wechat-ai.exe" if os.name == "nt" else "wechat-ai")
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], cwd=temporary, check=True)
        subprocess.run([str(cli), "--version"], cwd=temporary, check=True)
        subprocess.run([str(cli), "init", "--state-dir", str(temporary / "state")], cwd=temporary, check=True)
        subprocess.run([str(python), "-c", "from importlib.resources import files; p=files('wechat_ai_control'); assert (p/'web/templates/conversations.html').is_file(); assert (p/'web/static/js/models.js').is_file(); from fastapi.testclient import TestClient; from wechat_ai_control.app import create_app; from wechat_ai_control.models import AppConfig; import sys; client=TestClient(create_app(AppConfig(state_dir=sys.argv[1]))); assert client.get('/api/health').status_code == 200; assert client.get('/conversations').status_code == 200; assert client.get('/static/css/models.css').status_code == 200", str(temporary / "state")], cwd=temporary, check=True)
    print("Built wheel installed and served pages successfully outside source checkout.")


if __name__ == "__main__":
    main()
