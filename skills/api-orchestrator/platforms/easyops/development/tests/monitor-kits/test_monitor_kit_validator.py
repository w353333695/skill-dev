import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[3]
VALIDATOR = PLATFORM / "development/scripts/validate_monitor_kit.py"
WORKTREE_ROOT = Path(__file__).resolve().parents[7]


def validator():
    spec = importlib.util.spec_from_file_location("validate_monitor_kit_test", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MonitorKitValidatorTests(unittest.TestCase):
    def test_required_manual_password_cannot_use_secret_reference(self):
        module = validator()
        with tempfile.TemporaryDirectory(dir=WORKTREE_ROOT / ".local") as temporary:
            root = Path(temporary) / "kit"
            root.mkdir()
            (root / "plugin.yaml").write_text(
                "name: test-kit\nversion: 1.0.0\nparamDefine:\n"
                "    - {name: accessKey, valueType: password, defaultValue: \"\", optional: false, isFromSecret: true, isEncrypt: true}\n",
                encoding="utf-8",
            )
            with self.assertRaises(module.ValidationError) as context:
                module.validate_dir(root)
            self.assertIn("不能启用isFromSecret", str(context.exception))

    def test_metric_set_must_be_object_array(self):
        module = validator()
        with tempfile.TemporaryDirectory(dir=WORKTREE_ROOT / ".local") as temporary:
            root = Path(temporary) / "kit"
            root.mkdir()
            (root / "plugin.yaml").write_text("name: test-kit\nversion: 1.0.0\n", encoding="utf-8")
            (root / "origin_metric.json").write_text(json.dumps([{"key": "metric"}]), encoding="utf-8")
            (root / "metric_set.json").write_text(json.dumps(["基础指标"]), encoding="utf-8")
            (root / "alias_metric.json").write_text(json.dumps([{
                "name": "metric", "objectId": "HOST", "dataType": "double", "type": "gauge",
                "dims": [], "metricSet": ["基础指标"], "originalMetrics": ["metric"],
            }]), encoding="utf-8")
            with self.assertRaises(module.ValidationError) as context:
                module.validate_dir(root)
            self.assertIn("metric_set.json[0] 必须是包含非空 name 的对象", str(context.exception))


if __name__ == "__main__":
    unittest.main()
