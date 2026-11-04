import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublishGuardTests(unittest.TestCase):
    def scan(self, filename, content):
        path = ROOT / "scripts/check_publish.py"
        self.assertTrue(path.exists(), "publish guard must exist")
        spec = importlib.util.spec_from_file_location("publish_guard", path)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return guard.check_files(Path(directory), [filename])

    def test_live_state_cannot_be_published(self):
        self.assertTrue(self.scan("state.json", '{"pending": {}}'))

    def test_token_in_source_cannot_be_published(self):
        self.assertTrue(self.scan("demo.py", 'key = "' + 'sk-' + 'x' * 32 + '"'))

    def test_placeholder_config_is_publishable(self):
        self.assertEqual(self.scan("config/model.example.json", '{"apiKey":""}'), [])


if __name__ == "__main__":
    unittest.main()
