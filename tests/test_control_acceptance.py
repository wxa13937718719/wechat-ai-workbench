import unittest
from pathlib import Path


class AcceptanceContractTests(unittest.TestCase):
    def test_bootstrap_contains_console_launcher(self):
        text = Path("scripts/bootstrap_wechat_ai.ps1").read_text(encoding="utf-8")
        self.assertIn("wechat_ai_console.py", text)

    def test_skill_documents_local_console(self):
        text = Path("SKILL.md").read_text(encoding="utf-8")
        self.assertIn("wechat_ai_console.py", text)
        self.assertIn("127.0.0.1", text)

    def test_manual_send_invariant_is_documented(self):
        text = Path("docs/architecture.md").read_text(encoding="utf-8")
        self.assertIn("手动发送不会解锁联系人", text)

    def test_console_verifier_is_read_only_without_explicit_send_switch(self):
        text = Path("scripts/verify_wechat_console.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$SendTest", text)
        self.assertIn("filehelper", text)
        self.assertIn("if ($SendTest)", text)
        self.assertNotIn("--chat $Chat", text)

    def test_console_verifier_checks_every_runtime_layer(self):
        text = Path("scripts/verify_wechat_console.ps1").read_text(encoding="utf-8")
        for marker in ("docker", "login", "daemon", "/api/health", "/api/capabilities", "/api/chats", "/conversations"):
            self.assertIn(marker, text.lower())


if __name__ == "__main__":
    unittest.main()
