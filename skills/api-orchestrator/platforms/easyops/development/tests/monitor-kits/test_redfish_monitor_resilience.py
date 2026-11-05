"""验证 Redfish 监控脚本对局部指标失败的隔离行为。"""
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


PACKAGE = Path(__file__).resolve().parents[3] / "hub" / "monitor-kits" / "物理服务器Redfish监控套件_1.0.17.zip"


def run_fixture(fixture):
    with ZipFile(str(PACKAGE)) as archive:
        script = archive.read("src/物理服务器Redfish监控套件.py").decode("utf-8")
    program = """
import json
namespace = {'__name__': 'fixture'}
exec(compile(%r, 'redfish.py', 'exec'), namespace)
pc = namespace['PHYSICAL'].__new__(namespace['PHYSICAL'])
pc.redfish = {}
pc.loader = []
%s
pc.run()
print(json.dumps(pc.loader))
""" % (script, fixture)
    return subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)


def test_partial_metric_failure_warns_and_continues():
    result = run_fixture(
        "pc.createSession = lambda: None\n"
        "pc.getData = lambda: pc.redfish.update({'Systems': {'PowerState': 'On'}, 'Power': {'Id': 'Power'}})"
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)[0]["vals"]["power_status"] == 0


def test_auth_failure_remains_fatal():
    result = run_fixture(
        "pc.createSession = lambda: (_ for _ in ()).throw(Exception('auth fail'))"
    )
    assert result.returncode != 0


def test_published_script_injects_environment_parameters():
    with ZipFile(str(PACKAGE)) as archive:
        script = archive.read("src/物理服务器Redfish监控套件.py").decode("utf-8")
        original = archive.read("src/物理服务器Redfish监控套件.orig").decode("utf-8")
    namespace = {"__name__": "injection_test"}
    environment = {
        "EASYOPS_COLLECTOR_host": "192.0.2.1",
        "EASYOPS_COLLECTOR_user": "redfish-user",
        "EASYOPS_COLLECTOR_password": "secret",
        "EASYOPS_COLLECTOR_requestsTime": "7",
    }
    previous = dict(os.environ)
    try:
        os.environ.update(environment)
        exec(compile(script, "redfish.py", "exec"), namespace)
    finally:
        os.environ.clear()
        os.environ.update(previous)
    assert namespace["host"] == "192.0.2.1"
    assert namespace["user"] == "redfish-user"
    assert namespace["password"] == "secret"
    assert namespace["requestsTime"] == 7
    assert "EASYOPS_COLLECTOR_host" not in original


def test_top_level_failure_is_visible_on_stdout_and_exits_zero():
    with ZipFile(str(PACKAGE)) as archive:
        script = archive.read("src/物理服务器Redfish监控套件.py").decode("utf-8")
    program = """
namespace = {'__name__': 'fixture'}
exec(compile(%r, 'redfish.py', 'exec'), namespace)
namespace['collect'] = lambda: (_ for _ in ()).throw(Exception('auth fail'))
try:
    namespace['sys'].exit(namespace['main']())
except Exception:
    namespace['sys'].stdout.write('COLLECT_ERROR:\\n')
    namespace['traceback'].print_exc(file=namespace['sys'].stdout)
    namespace['sys'].stdout.flush()
""" % script
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.startswith("COLLECT_ERROR:\n")
    assert "auth fail" in result.stdout
    assert result.stderr == ""


def test_python_headers_precede_environment_injection():
    with ZipFile(str(PACKAGE)) as archive:
        for suffix in ("py", "orig"):
            source = archive.read("src/物理服务器Redfish监控套件." + suffix)
            lines = source.splitlines()
            assert lines[0].startswith(b"#!/")
            assert b"coding: UTF-8" in lines[1]
            compile(source, "redfish." + suffix, "exec")
        script = archive.read("src/物理服务器Redfish监控套件.py")
        assert script.index(b"coding: UTF-8") < script.index(b"EASYOPS_COLLECTOR_host")
