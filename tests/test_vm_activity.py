import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.vm_window import VmWindowSnapshot
from wechat_ai_control.vm_activity import VmActivitySource


class FakeWindowAdapter:
    def __init__(self):
        self.snapshot_value = VmWindowSnapshot(
            status="ready",
            window_id="42",
            title="Virtual WeChat - Chat",
            chat_title="Chat",
            bounds={"left": 10, "top": 20, "right": 810, "bottom": 620},
            is_foreground=False,
            logged_in=True,
            automation_ready=True,
            reason="",
            observed_at="2026-09-21T00:00:00+00:00",
        )

    def snapshot(self):
        return self.snapshot_value


class VmActivitySourceTests(unittest.TestCase):
    def make_source(self):
        adapter = FakeWindowAdapter()
        cursor = {"value": (0, 0)}
        input_tick = {"value": 100}
        source = VmActivitySource(
            adapter,
            cursor_reader=lambda: cursor["value"],
            input_tick_reader=lambda: input_tick["value"],
        )
        return adapter, cursor, input_tick, source

    def test_initial_foreground_window_emits_focus_once(self):
        adapter, cursor, _input_tick, source = self.make_source()
        adapter.snapshot_value = VmWindowSnapshot(
            **{**adapter.snapshot_value.__dict__, "is_foreground": True}
        )

        events = source.poll()
        self.assertEqual([event.kind for event in events], ["window_focus"])
        self.assertEqual(source.poll(), [])

    def test_cursor_entry_and_user_input_emit_events(self):
        adapter, cursor, input_tick, source = self.make_source()
        source.poll()
        cursor["value"] = (100, 100)
        self.assertEqual([event.kind for event in source.poll()], ["mouse_enter"])

        adapter.snapshot_value = VmWindowSnapshot(
            **{**adapter.snapshot_value.__dict__, "is_foreground": True}
        )
        input_tick["value"] = 101
        self.assertEqual([event.kind for event in source.poll()], ["window_focus", "user_input"])

    def test_input_outside_target_window_is_ignored(self):
        _adapter, _cursor, input_tick, source = self.make_source()
        source.poll()
        input_tick["value"] = 101
        self.assertEqual(source.poll(), [])

    def test_marked_automation_tick_is_not_reported_as_human_input(self):
        adapter, cursor, input_tick, source = self.make_source()
        source.poll()
        adapter.snapshot_value = VmWindowSnapshot(
            **{**adapter.snapshot_value.__dict__, "is_foreground": True}
        )
        cursor["value"] = (100, 100)
        source.poll()
        source.mark_automation_activity()
        input_tick["value"] = 101
        self.assertEqual([event.kind for event in source.poll()], [])
        input_tick["value"] = 102
        self.assertEqual([event.kind for event in source.poll()], ["user_input"])


if __name__ == "__main__":
    unittest.main()
