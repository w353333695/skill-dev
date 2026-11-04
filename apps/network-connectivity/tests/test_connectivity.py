import contextlib
import csv
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import network_connectivity as tool


class ParsingTests(unittest.TestCase):
    def test_ip_shorthand_and_mixed_separators(self):
        self.assertEqual(tool.expand_ips("192.168.0.13/14/29-31\n10.0.0.1,2；3"), [
            "192.168.0.13", "192.168.0.14", "192.168.0.29", "192.168.0.30",
            "192.168.0.31", "10.0.0.1", "10.0.0.2", "10.0.0.3",
        ])

    def test_full_ip_range_and_deduplication(self):
        self.assertEqual(tool.expand_ips("10.0.0.254-10.0.1.1/1"), [
            "10.0.0.254", "10.0.0.255", "10.0.1.0", "10.0.1.1",
        ])

    def test_invalid_ips(self):
        for text in ("14", "192.168.1.300", "192.168.1.5/4-2", "::1", "bad", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                tool.expand_ips(text)

    def test_expansion_limit(self):
        with self.assertRaises(ValueError):
            tool.expand_ips("0.0.0.0-255.255.255.255", limit=10)

    def test_protocol_inheritance(self):
        self.assertEqual(tool.expand_ports("tcp80/443-445/10034\nudp161/162;tcp25"), [
            ("tcp", 80), ("tcp", 443), ("tcp", 444), ("tcp", 445),
            ("tcp", 10034), ("udp", 161), ("udp", 162), ("tcp", 25),
        ])

    def test_invalid_ports(self):
        for text in ("tcp0", "udp65536", "tcp5-2", "icmp80", "tcp", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                tool.expand_ports(text)

    def test_cartesian_product(self):
        tasks = tool.make_tasks("10.0.0.1/2", "192.168.0.1/2", "tcp80/443", 20)
        self.assertEqual(len(tasks), 8)
        self.assertEqual(tasks[0], {
            "source_ip": "10.0.0.1", "target_ip": "192.168.0.1", "protocol": "tcp", "target_port": 80,
        })

    def test_empty_source_means_local(self):
        self.assertEqual(tool.make_tasks("", "192.168.0.1", "80", 10)[0]["source_ip"], "")

    def test_product_limit(self):
        with self.assertRaises(ValueError):
            tool.make_tasks("", "192.168.0.1-10", "80/81", 10)

    def test_csv_multiline_and_chinese_headers(self):
        text = '\ufeff源IP,目标IP,目标端口\n,"192.168.0.1/2\n192.168.1.1","tcp80\nudp161"\n'
        tasks = tool.read_tasks_csv(io.StringIO(text), 100)
        self.assertEqual(len(tasks), 6)
        self.assertEqual(tasks[-1]["protocol"], "udp")

    def test_csv_deduplicates(self):
        tasks = tool.read_tasks_csv(io.StringIO("source_ip,target_ip,target_ports\n,10.0.0.1,80\n,10.0.0.1,80\n"), 10)
        self.assertEqual(len(tasks), 1)

    def test_csv_errors(self):
        for text in (
            "source_ip,target_ip\n,10.0.0.1\n",
            "source_ip,target_ip,target_ports\n,,80\n",
            "source_ip,target_ip,target_ports\n,10.0.0.1,80,extra\n",
            "source_ip,target_ip,target_ports\n",
            "source_ip,source,target_ip,target_ports\n,,10.0.0.1,80\n",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                tool.read_tasks_csv(io.StringIO(text), 10)

    def test_csv_total_limit(self):
        with self.assertRaises(ValueError):
            tool.read_tasks_csv(io.StringIO("target_ip,target_ports\n10.0.0.1,80\n10.0.0.2,80\n"), 1)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.task = tool.make_tasks("", "192.0.2.1", "tcp80", 10)[0]

    @patch.object(socket, "socket")
    def test_tcp_success(self, socket_factory):
        self.assertEqual(tool.probe(self.task, 1, b"")["status"], "REACHABLE")
        socket_factory.return_value.__enter__.return_value.connect.assert_called_once_with(("192.0.2.1", 80))

    @patch.object(socket, "socket")
    def test_tcp_refused(self, socket_factory):
        socket_factory.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError("refused")
        self.assertEqual(tool.probe(self.task, 1, b"")["status"], "REFUSED")

    @patch.object(socket, "socket")
    def test_tcp_timeout(self, socket_factory):
        socket_factory.return_value.__enter__.return_value.connect.side_effect = socket.timeout()
        self.assertEqual(tool.probe(self.task, 1, b"")["status"], "TIMEOUT")

    @patch.object(socket, "socket")
    def test_udp_no_reply_is_unknown(self, socket_factory):
        self.task["protocol"] = "udp"
        socket_factory.return_value.__enter__.return_value.recv.side_effect = socket.timeout()
        self.assertEqual(tool.probe(self.task, 1, b"")["status"], "UNKNOWN")

    @patch.object(socket, "socket")
    def test_udp_reply(self, socket_factory):
        self.task["protocol"] = "udp"
        socket_factory.return_value.__enter__.return_value.recv.return_value = b"reply"
        self.assertEqual(tool.probe(self.task, 1, b"hello")["status"], "REACHABLE")

    @patch.object(socket, "socket")
    def test_os_error_has_traceback(self, socket_factory):
        socket_factory.return_value.__enter__.return_value.connect.side_effect = OSError("route missing")
        result = tool.probe(self.task, 1, b"")
        self.assertEqual(result["status"], "NETWORK_ERROR")
        self.assertIn("Traceback", result["detail"])

    def test_remote_worker_uses_same_probe_without_network(self):
        namespace = {"__name__": "not_main"}
        exec(tool.worker_source(), namespace)
        self.assertIn("probe", namespace)
        self.assertIn("worker_main", namespace)


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tasks = tool.make_tasks("192.0.2.10", "192.0.2.1", "80", 10)
        self.args = tool.parser().parse_args(["-d", "192.0.2.1", "-p", "80"])
        self.args.known_hosts = str(Path(__file__).resolve().parents[1] / ".local" / "test_known_hosts")

    @patch.object(tool.shutil, "which", return_value="/usr/bin/ssh")
    @patch.object(tool.subprocess, "run")
    def test_key_auth_success(self, run, which):
        expected = dict(self.tasks[0], status="REACHABLE", detail="ok", elapsed_ms=1)
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(expected) + "\n", "")
        self.assertEqual(tool.probe_remote(self.tasks, self.args), [expected])
        command = run.call_args.args[0]
        self.assertIn("BatchMode=yes", command)
        self.assertIn("root", command)
        self.assertIn("StrictHostKeyChecking=ask", command)

    @patch.object(tool.sys.stdin, "isatty", return_value=True)
    @patch.object(tool.shutil, "which", return_value="/usr/bin/ssh")
    @patch.object(tool.subprocess, "run")
    def test_password_fallback(self, run, which, isatty):
        expected = dict(self.tasks[0], status="REACHABLE", detail="ok", elapsed_ms=1)
        run.side_effect = [
            subprocess.CompletedProcess([], 255, "", "Permission denied (publickey,password)."),
            subprocess.CompletedProcess([], 0, json.dumps(expected) + "\n", None),
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(tool.probe_remote(self.tasks, self.args), [expected])
        self.assertIn("BatchMode=no", run.call_args.args[0])
        self.assertIsNone(run.call_args.kwargs["stderr"])

    @patch.object(tool.sys.stdin, "isatty", return_value=False)
    @patch.object(tool.shutil, "which", return_value="/usr/bin/ssh")
    @patch.object(tool.subprocess, "run")
    def test_no_password_prompt_without_terminal(self, run, which, isatty):
        run.return_value = subprocess.CompletedProcess([], 255, "", "Permission denied")
        self.assertEqual(tool.probe_remote(self.tasks, self.args)[0]["status"], "SSH_ERROR")
        self.assertEqual(run.call_count, 1)

    @patch.object(tool.shutil, "which", return_value="/usr/bin/ssh")
    @patch.object(tool.subprocess, "run")
    def test_connection_failure_does_not_retry(self, run, which):
        run.return_value = subprocess.CompletedProcess([], 255, "", "Connection refused")
        self.assertEqual(tool.probe_remote(self.tasks, self.args)[0]["status"], "SSH_ERROR")
        self.assertEqual(run.call_count, 1)

    @patch.object(tool.shutil, "which", return_value="/usr/bin/ssh")
    @patch.object(tool.subprocess, "run")
    def test_malformed_worker_output(self, run, which):
        run.return_value = subprocess.CompletedProcess([], 0, "not json", "")
        self.assertEqual(tool.probe_remote(self.tasks, self.args)[0]["status"], "SSH_ERROR")


class CliTests(unittest.TestCase):
    @patch.object(tool, "probe", side_effect=AssertionError("禁止真实探测"))
    @patch.object(tool, "probe_remote", side_effect=AssertionError("禁止 SSH"))
    def test_dry_run_prints_without_network(self, remote, local):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = tool.main(["-s", "192.0.2.10", "-d", "192.0.2.1/2", "-p", "tcp80", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("PLANNED", output.getvalue())

    def test_csv_export_and_bom(self):
        local = Path(__file__).resolve().parents[1] / ".local"
        local.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local) as directory:
            output = Path(directory) / "result.csv"
            with contextlib.redirect_stdout(io.StringIO()):
                code = tool.main(["-d", "192.0.2.1", "-p", "80", "--dry-run", "-o", str(output)])
            self.assertEqual(code, 0)
            self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["status"], "PLANNED")

    def test_reject_nonfinite_timeout(self):
        for value in ("nan", "inf", "0", "-1"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    tool.main(["-d", "192.0.2.1", "-p", "80", "-t", value, "--dry-run"])
                self.assertEqual(raised.exception.code, 2)

    def test_reject_mixed_modes(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tool.main(["--csv", "tasks.csv", "-d", "192.0.2.1", "--dry-run"])


class AdditionalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.local = Path(__file__).resolve().parents[1] / ".local"
        self.local.mkdir(exist_ok=True)

    @patch.object(tool.shutil, "which", return_value=None)
    def test_missing_ssh_is_error_not_probe(self, which):
        tasks = tool.make_tasks("192.0.2.10", "192.0.2.1", "80", 10)
        args = tool.parser().parse_args([])
        self.assertEqual(tool.probe_remote(tasks, args)[0]["status"], "SSH_ERROR")

    def test_worker_roundtrip_without_network(self):
        namespace = {"__name__": "not_main"}
        exec(tool.worker_source(), namespace)
        task = tool.make_tasks("192.0.2.10", "192.0.2.1", "80", 10)[0]
        expected = dict(task, status="REACHABLE", elapsed_ms=1, detail="模拟连接")
        mocked_probe = MagicMock(return_value=expected)
        namespace["probe"] = mocked_probe
        request = io.StringIO(json.dumps({"tasks": [task], "timeout": 1, "udp_payload_hex": "aabb"}))
        response = io.StringIO()
        with patch.object(tool.sys, "stdin", request), contextlib.redirect_stdout(response):
            namespace["worker_main"]()
        self.assertEqual(json.loads(response.getvalue()), expected)
        mocked_probe.assert_called_once_with(task, 1, b"\xaa\xbb")

    @patch.object(tool, "probe_remote")
    def test_failed_source_does_not_skip_other_source(self, remote):
        def error_results(tasks, args):
            return tool.ssh_errors(tasks, "模拟认证失败")
        remote.side_effect = error_results
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = tool.main(["-s", "192.0.2.10/11", "-d", "192.0.2.1", "-p", "80"])
        self.assertEqual(result, 1)
        self.assertEqual(remote.call_count, 2)

    def test_hardlinked_input_output_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.local) as directory:
            source = Path(directory) / "tasks.csv"
            destination = Path(directory) / "result.csv"
            source.write_text("target_ip,target_ports\n192.0.2.1,80\n")
            os.link(source, destination)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                tool.main(["--csv", str(source), "-o", str(destination), "--dry-run"])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("target_ip", source.read_text())

    @patch.object(tool, "probe")
    def test_ctrl_c_preserves_finished_csv_rows(self, probe_mock):
        task = tool.make_tasks("", "192.0.2.1", "80", 10)[0]
        probe_mock.side_effect = [dict(task, status="REACHABLE", elapsed_ms=1, detail="mock"), KeyboardInterrupt]
        with tempfile.TemporaryDirectory(dir=self.local) as directory:
            output = Path(directory) / "results.csv"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = tool.main(["-d", "192.0.2.1/2", "-p", "80", "-o", str(output)])
            self.assertEqual(code, 130)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)


if __name__ == "__main__":
    unittest.main()
