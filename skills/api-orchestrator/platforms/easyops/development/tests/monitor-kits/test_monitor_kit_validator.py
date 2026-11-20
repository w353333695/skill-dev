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
            self.assertIn("缺少配套secretName参数", str(context.exception))

    def test_manual_plaintext_with_encrypt_flag_rejected(self):
        """非Secret引用却 isEncrypt=true（明文直存+加密标志）：下发 decrypt 必炸，校验器阻断。"""
        module = validator()
        with tempfile.TemporaryDirectory(dir=WORKTREE_ROOT / ".local") as temporary:
            root = Path(temporary) / "kit"
            root.mkdir()
            (root / "plugin.yaml").write_text(
                "name: test-kit\nversion: 1.0.0\nparamDefine:\n"
                "    - {name: passwordText, valueType: string, defaultValue: \"\", optional: false, isFromSecret: false, isEncrypt: true}\n",
                encoding="utf-8",
            )
            with self.assertRaises(module.ValidationError) as context:
                module.validate_dir(root)
            self.assertIn("illegal base64 data", str(context.exception))

    def test_manual_credential_plain_string_passes(self):
        """手填凭证唯一口径：string + isFromSecret=false + isEncrypt=false 校验通过。"""
        module = validator()
        with tempfile.TemporaryDirectory(dir=WORKTREE_ROOT / ".local") as temporary:
            root = Path(temporary) / "kit"
            root.mkdir()
            (root / "plugin.yaml").write_text(
                "name: test-kit\nversion: 1.0.0\nparamDefine:\n"
                "    - {name: passwordText, valueType: string, defaultValue: \"\", optional: false, isFromSecret: false, isEncrypt: false}\n",
                encoding="utf-8",
            )
            (root / "origin_metric.json").write_text(json.dumps([{"key": "m", "labels": []}]), encoding="utf-8")
            (root / "metric_set.json").write_text(json.dumps([{"name": "s"}]), encoding="utf-8")
            (root / "alias_metric.json").write_text(json.dumps([
                {"name": "m", "objectId": "HOST", "dataType": "double", "type": "normal",
                 "dims": [], "metricSet": ["s"], "originalMetrics": ["m"]}
            ]), encoding="utf-8")
            self.assertIn("目录校验通过", module.validate_dir(root))

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

    def test_python_source_cannot_use_non_ascii_json_output(self):
        module = validator()
        with tempfile.TemporaryDirectory(dir=WORKTREE_ROOT / ".local") as temporary:
            root = Path(temporary) / "kit"
            root.mkdir()
            (root / "plugin.yaml").write_text("name: test-kit\nversion: 1.0.0\n", encoding="utf-8")
            source = root / "src/collector.py"
            source.parent.mkdir()
            source.write_text("print(json.dumps(data, ensure_ascii=False))\n", encoding="utf-8")
            source.with_suffix(".orig").write_text("print(json.dumps(data, ensure_ascii=False))\n", encoding="utf-8")
            with self.assertRaises(module.ValidationError) as context:
                module.validate_dir(root)
            self.assertIn("ensure_ascii=False", str(context.exception))

    def test_python_source_cannot_use_future_import(self):
        module = validator()
        with tempfile.TemporaryDirectory(dir=WORKTREE_ROOT / ".local") as temporary:
            root = Path(temporary) / "kit"
            root.mkdir()
            (root / "plugin.yaml").write_text("name: test-kit\nversion: 1.0.0\n", encoding="utf-8")
            source = root / "src/collector.py"
            source.parent.mkdir()
            source.write_text("from __future__ import division\n", encoding="utf-8")
            source.with_suffix(".orig").write_text("from __future__ import division\n", encoding="utf-8")
            with self.assertRaises(module.ValidationError) as context:
                module.validate_dir(root)
            self.assertIn("from __future__", str(context.exception))

    def test_alias_dimensions_must_match_origin_labels(self):
        module = validator()
        with tempfile.TemporaryDirectory(dir=WORKTREE_ROOT / ".local") as temporary:
            root = Path(temporary) / "kit"
            root.mkdir()
            (root / "plugin.yaml").write_text("name: test-kit\nversion: 1.0.0\n", encoding="utf-8")
            (root / "origin_metric.json").write_text(json.dumps([{"key": "metric", "labels": ["host", "port"]}]), encoding="utf-8")
            (root / "metric_set.json").write_text(json.dumps([{"name": "基础指标"}]), encoding="utf-8")
            (root / "alias_metric.json").write_text(json.dumps([{
                "name": "metric", "objectId": "HOST", "dataType": "double", "type": "gauge",
                "dims": [{"dimName": "host"}], "metricSet": ["基础指标"], "originalMetrics": ["metric"],
            }]), encoding="utf-8")
            with self.assertRaises(module.ValidationError) as context:
                module.validate_dir(root)
            self.assertIn("维度", str(context.exception))


if __name__ == "__main__":
    unittest.main()
