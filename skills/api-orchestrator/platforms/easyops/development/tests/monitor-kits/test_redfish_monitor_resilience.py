"""验证 Redfish 监控脚本对局部指标失败的隔离行为。"""
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


PACKAGE = Path(__file__).resolve().parents[3] / "hub" / "monitor-kits" / "物理服务器Redfish监控套件_1.0.14.zip"


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
