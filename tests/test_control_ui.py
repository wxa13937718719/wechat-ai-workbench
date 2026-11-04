import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.app import create_app
from wechat_ai_control.models import AppConfig


class ControlUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(AppConfig(state_dir=Path(self.tmp.name))))

    def tearDown(self):
        self.tmp.cleanup()

    def test_conversations_page_has_semantic_workspace_regions(self):
        response = self.client.get("/conversations")
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-region="navigation-rail"', response.text)
        self.assertIn('data-region="conversation-sidebar"', response.text)
        self.assertIn('data-region="message-list"', response.text)
        self.assertIn('data-region="composer"', response.text)
        self.assertIn('data-region="ai-drawer"', response.text)
        self.assertIn('aria-hidden="true"', response.text)

    def test_search_add_and_ai_controls_are_accessible_buttons(self):
        response = self.client.get("/conversations")

        self.assertIn('aria-label="搜索会话"', response.text)
        self.assertIn('aria-label="发起会话"', response.text)
        self.assertIn('aria-label="打开 AI 控制"', response.text)
        self.assertNotIn("💬", response.text)
        self.assertNotIn("⚙", response.text)

    def test_ai_drawer_exposes_manual_authorization_controls(self):
        response = self.client.get("/conversations")

        self.assertIn('id="ai-grant-chat"', response.text)
        self.assertIn('id="ai-revoke-chat"', response.text)
        self.assertIn("手动授权", response.text)
        self.assertIn("对方关键词", response.text)

    def test_frontend_uses_es_modules_and_local_lucide_asset(self):
        response = self.client.get("/conversations")

        self.assertIn('src="/static/js/vendor/lucide.min.js', response.text)
        self.assertIn('type="module" src="/static/js/app.js', response.text)
        self.assertNotIn('/static/app.js', response.text)
        self.assertNotIn('/static/app.css', response.text)

    def test_visual_tokens_match_desktop_wechat_geometry(self):
        tokens = self.client.get("/static/css/tokens.css").text
        shell = self.client.get("/static/css/shell.css").text

        self.assertIn("--rail-width: 60px", tokens)
        self.assertIn("--sidebar-width: 212px", tokens)
        self.assertIn("--conversation-row-height: 68px", tokens)
        self.assertIn("--chat-header-height: 68px", tokens)
        self.assertIn("@media (max-width: 959px)", shell)
        self.assertIn(".unsupported-viewport", shell)

    def test_store_tracks_scoped_conversation_state(self):
        store = self.client.get("/static/js/store.js").text

        for state_name in ["selectedChatId", "chatPages", "messagePages", "drafts", "scrollPositions", "capabilities", "updateCursor"]:
            self.assertIn(state_name, store)
        self.assertIn("subscribe", store)
        self.assertIn("notify", store)

    def test_navigation_has_confirmed_pages(self):
        response = self.client.get("/")
        for label in ["总览", "会话", "规则", "模型", "指令", "审计", "设置"]:
            self.assertIn(label, response.text)

    def test_control_pages_are_not_placeholders(self):
        pages = {
            "/models": ["provider-form", "route-form", "provider-list"],
            "/rules": ["global-rule-form", "rule-list"],
            "/commands": ["command-form", "command-preview"],
            "/settings": ["runtime-form", "runtime-paused"],
            "/audit": ["audit-list", "reload-audit"],
        }
        for path, markers in pages.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(all(marker in response.text for marker in markers))
                self.assertNotIn("页面。", response.text)


if __name__ == "__main__":
    unittest.main()
