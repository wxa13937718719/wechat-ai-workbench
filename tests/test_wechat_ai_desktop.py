import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wechat_ai_desktop.py"


def load_module():
    spec = importlib.util.spec_from_file_location("wechat_ai_desktop", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WeChatAiDesktopTests(unittest.TestCase):
    def test_console_command_rejects_non_loopback_host(self):
        desktop = load_module()

        with self.assertRaises(ValueError):
            desktop.console_command(Path("state"), "0.0.0.0", 8765)


if __name__ == "__main__":
    unittest.main()
