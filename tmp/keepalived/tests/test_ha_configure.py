"""配置生成与健康判断测试；网络与系统服务调用均为模拟。"""
import contextlib
import copy
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ha_configure", ROOT / "ha-configure.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".local")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.data = yaml.safe_load((ROOT / "ha.sample.yaml").read_text())

    def load(self, data=None):
        path = self.directory / "ha.yaml"
        path.write_text(yaml.safe_dump(self.data if data is None else data))
        return module.load_config(path, "node-a")

    def health(self, overrides=None):
        spec = {"policy": "all", "round_timeout": 2, "checks": self.load()["health"]["checks"]}
        spec.update(overrides or {})
        namespace = {"__name__": "health_test", "SPEC": spec}
        exec(compile(module.HEALTH_PROGRAM, "health.py", "exec"), namespace)
        return namespace

    def test_nodes_and_nopreempt(self):
        data = self.load()
        config, runtime, name = module.render(data, "node-a", Path("/etc/keepalived"))
        self.assertIn("unicast_src_ip 192.168.10.11", config)
        self.assertIn("        192.168.10.12", config)
        self.assertIn("nopreempt", config)
        self.assertIn("weight 0", config)
        self.assertIn("init_fail", config)
        self.assertIn(name, config)
        compile(runtime, name, "exec")
        backup = module.render(data, "node-b", Path("/etc/keepalived"))[0]
        self.assertIn("priority 100", backup)
        self.assertIn("        192.168.10.11", backup)

    def test_three_nodes_equal_priority(self):
        self.data["nodes"]["node-a"]["priority"] = 100
        self.data["nodes"]["node-c"] = {
            "address": "192.168.10.13", "interface": "eth0", "priority": 100}
        data = self.load()
        for name in data["nodes"]:
            config = module.render(data, name, Path("/etc/keepalived"))[0]
            self.assertIn("    priority 100\n", config)
            for peer_name, peer in data["nodes"].items():
                if peer_name != name:
                    self.assertIn("        " + peer["address"] + "\n", config)

    def test_preempt(self):
        self.data["vrrp"]["preempt"] = True
        self.assertNotIn("    nopreempt\n", module.render(self.load(), "node-a", Path("/etc/keepalived"))[0])

    def test_unknown_field(self):
        self.data["health"]["falls"] = 3
        with self.assertRaises(ValueError):
            self.load()

    def test_duplicate_yaml_keys(self):
        path = self.directory / "duplicate.yaml"
        path.write_text("version: 1\nversion: 1\n")
        with self.assertRaisesRegex(ValueError, "重复"):
            module.load_config(path, "node-a")

    def test_invalid_inputs(self):
        cases = [("priority", 255), ("address", "192.168.10.100"), ("address", "10.0.0.1")]
        for key, value in cases:
            data = copy.deepcopy(self.data)
            data["nodes"]["node-a"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.load(data)
        self.data["health"]["checks"][1]["port"] = 65536
        with self.assertRaises(ValueError):
            self.load()

    def test_quorum_validation(self):
        self.data["health"]["policy"] = "quorum"
        self.data["health"]["min_success"] = 2
        self.assertEqual(self.load()["health"]["min_success"], 2)
        self.data["health"]["min_success"] = 4
        with self.assertRaises(ValueError):
            self.load()

    def test_all_any_quorum(self):
        for policy, threshold, expected in [("all", None, 1), ("any", None, 0), ("quorum", 2, 0), ("quorum", 3, 1)]:
            overrides = {"policy": policy}
            if threshold:
                overrides["min_success"] = threshold
            health = self.health(overrides)
            def fake_worker(check):
                return check["name"], check["type"] != "tcp", "mock"
            health["worker"] = fake_worker
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(health["main"](), expected)

    def test_process_arguments_and_self_exclusion(self):
        health = self.health()
        result = subprocess.CompletedProcess([], 0, stdout="123\n456\n", stderr="")
        with mock.patch("subprocess.run", return_value=result) as call, mock.patch("os.getpid", return_value=123):
            check = {"type": "process", "match": "cmdline", "pattern": "java.*api.jar", "min_count": 2, "timeout": 1}
            self.assertFalse(health["check_one"](check)[0])
            self.assertEqual(call.call_args.args[0], ["pgrep", "-f", "--", "java.*api.jar"])

    def test_tcp_success_and_exception(self):
        health = self.health()
        check = {"name": "port", "type": "tcp", "host": "127.0.0.1", "port": 8080, "timeout": 0.5}
        with mock.patch("socket.create_connection", return_value=mock.MagicMock()) as call:
            self.assertTrue(health["check_one"](check)[0])
            call.assert_called_once_with(("127.0.0.1", 8080), timeout=0.5)
        with mock.patch("socket.create_connection", side_effect=TimeoutError("mock timeout")):
            result = health["worker"](check)
            self.assertFalse(result[1])
            self.assertIn("Traceback", result[2])

    def test_http_status_body_and_proxy(self):
        health = self.health()
        check = {"type": "http", "url": "http://127.0.0.1/ready", "expected_status": [200], "body_contains": "ready", "timeout": 1}
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.code = 200
        response.read.return_value = b"ready"
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch("urllib.request.build_opener", return_value=opener) as build:
            self.assertTrue(health["check_one"](check)[0])
            self.assertEqual(build.call_args.args[0].proxies, {})
            response.read.assert_called_with(65536)
            response.read.return_value = b"not yet"
            self.assertFalse(health["check_one"](check)[0])
            response.code = 503
            self.assertFalse(health["check_one"](check)[0])

    def test_generated_runtime_and_hard_timeout(self):
        # 可控 worker 替身用于验证真实父进程超时逻辑，不访问网络。
        data = self.load()
        data["health"]["round_timeout"] = 1
        runtime = module.render(data, "node-a", Path("/etc/keepalived"))[1]
        runtime = runtime.replace('def main():\n', 'def main():\n    import time\n    time.sleep(4)\n')
        script = self.directory / "check.py"
        script.write_text(runtime)
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        self.assertIn("整轮健康检查超时", result.stderr)

    def test_check_cli_success_and_failure(self):
        # 只调用目录内的 pgrep 替身，验证生成文件的真实执行链路与退出码。
        binary = self.directory / "pgrep"
        binary.write_text("#!/bin/sh\nprintf '424242\\n'\n")
        binary.chmod(0o700)
        data = copy.deepcopy(self.data)
        data["health"]["checks"] = [data["health"]["checks"][0]]
        config_path = self.directory / "cli.yaml"
        config_path.write_text(yaml.safe_dump(data))
        command = [str(ROOT / "setup-keepalived.sh"), "--config", str(config_path),
                   "--node", "node-a", "--check", "--output-dir", str(self.directory / "generated")]
        environment = dict(os.environ, PATH=str(self.directory) + os.pathsep + os.environ.get("PATH", ""))
        passed = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn("[PASS] nginx_process", passed.stdout)
        binary.write_text("#!/bin/sh\nexit 1\n")
        failed = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertIn("[FAIL] nginx_process", failed.stdout)

    def test_custom_apply_directory_rejected(self):
        with self.assertRaisesRegex(ValueError, "默认"):
            module.apply(None, None, self.directory, {})

    def test_apply_rollback(self):
        # 所有系统命令均模拟，所有文件路径映射到测试目录。
        install_dir = self.directory / "installed"
        install_dir.mkdir()
        (install_dir / "keepalived.conf").write_text("old config")
        staged_config = self.directory / "new.conf"
        staged_config.write_text("new config")
        script = self.directory / "ha-check.py"
        script.write_text("pass\n")
        fake_path = mock.Mock(side_effect=lambda value: install_dir if value == "/etc/keepalived" else Path(value))
        calls = []
        def fake_run(command, **kwargs):
            calls.append(command)
            if command[0] == "ip":
                return subprocess.CompletedProcess(command, 0, stdout='[{"addr_info":[{"local":"192.168.10.11"}]}]')
            if command == ["systemctl", "restart", "keepalived"] and calls.count(command) == 1:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(module, "Path", fake_path), mock.patch.object(module, "run", side_effect=fake_run), \
             mock.patch.object(module.shutil, "which", return_value="mock"), \
             mock.patch.object(module.os, "geteuid", return_value=0), \
             mock.patch.object(module, "sys") as fake_sys, \
             mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)), \
             mock.patch.object(type(install_dir), "stat", return_value=mock.Mock(st_uid=0, st_mode=0o755)), \
             contextlib.redirect_stdout(io.StringIO()):
            fake_sys.platform = "linux"
            fake_sys.stderr = io.StringIO()
            with self.assertRaises(subprocess.CalledProcessError):
                module.apply(staged_config, script, install_dir, {"interface": "eth0", "address": "192.168.10.11"})
        self.assertEqual((install_dir / "keepalived.conf").read_text(), "old config")
        self.assertEqual(calls.count(["systemctl", "restart", "keepalived"]), 2)


if __name__ == "__main__":
    unittest.main()
