import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.models import normalize_runtime


class RuntimeConfigContractTests(unittest.TestCase):
    def test_legacy_runtime_gets_human_aware_defaults(self):
        value = normalize_runtime({"paused": False, "reloadToken": 3})

        self.assertEqual(value["reloadToken"], 3)
        self.assertEqual(value["interactionMode"], "vm_human_aware")
        self.assertEqual(value["idleTimeoutSeconds"], 60)
        self.assertFalse(value["hostUnrelatedFileOpsAffectAi"])

    def test_runtime_values_are_clamped_to_safe_ranges(self):
        value = normalize_runtime({"idleTimeoutSeconds": 1, "automationLeaseSeconds": 999})

        self.assertEqual(value["idleTimeoutSeconds"], 15)
        self.assertEqual(value["automationLeaseSeconds"], 120)

    def test_invalid_interaction_mode_falls_back_without_enabling_unknown_behavior(self):
        value = normalize_runtime({"interactionMode": "run-arbitrary-actions"})

        self.assertEqual(value["interactionMode"], "vm_human_aware")

    def test_interaction_enforcement_defaults_to_observe_only_and_accepts_explicit_enforce(self):
        self.assertEqual(normalize_runtime({})["interactionEnforcement"], "observe_only")
        self.assertEqual(normalize_runtime({"interactionEnforcement": "enforce"})["interactionEnforcement"], "enforce")
        self.assertEqual(normalize_runtime({"interactionEnforcement": "unsafe"})["interactionEnforcement"], "observe_only")


if __name__ == "__main__":
    unittest.main()
