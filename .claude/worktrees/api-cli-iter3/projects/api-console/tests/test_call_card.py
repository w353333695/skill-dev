"""call_card CLI 单测：参数解析 / 只读约束 / 必填校验 / 输出格式 / 业务码不报错。

mock 策略：patch call_card 的加载函数（load_cards/load_platform/load_contracts）
注入假数据，patch call_card.invoke_card 注入假请求结果，专注测 CLI 决策与输出。
"""
from __future__ import annotations
import json
import pathlib
from unittest.mock import patch, MagicMock

import pytest
from api_console.schema.card import Card

from api_console import call_card


def _read_card(name, side_effect="read", required=None, method="GET"):
    return Card(name=name, module="m", method=method, path="/p/" + name,
                side_effect=side_effect, request_required=required or [],
                endpoint={"contract_ref": "", "mode": "fake_mode"})


class TestParseParams:
    """--param k=v 解析为字面量 dict。"""

    def test_basic(self):
        assert call_card.parse_params(["Q=test", "page=1"]) == {"Q": "test", "page": "1"}

    def test_value_can_contain_equals(self):
        assert call_card.parse_params(["note=a=b=c"]) == {"note": "a=b=c"}

    def test_invalid_form_exits(self):
        with pytest.raises(SystemExit):
            call_card.parse_params(["no_equals_sign"])


class TestOutput:
    """输出 {meta, data} 结构；业务码非 0 不报错。"""

    def test_success_output(self, capsys):
        card = _read_card("getTicket")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": 0, "message": "ok", "data": {"id": "123"}}
        with patch("api_console.call_card.load_cards", return_value={"getTicket": card}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}), \
             patch("api_console.call_card.invoke_card",
                   return_value=call_card.InvokeResult(resp=resp, url="http://h/x", method="GET")):
            call_card.main(["--platform", "demo", "--card", "getTicket",
                            "--param", "ticketId=123"])
        out = json.loads(capsys.readouterr().out)
        assert out["data"] == {"id": "123"}
        assert out["meta"]["card"] == "getTicket"
        assert out["meta"]["http_status"] == 200
        assert out["meta"]["biz_code"] == 0
        assert out["meta"]["biz_message"] == "ok"
        assert out["meta"]["url"] == "http://h/x"

    def test_nonzero_biz_code_not_raise(self, capsys):
        """业务码非 0：正常输出（meta 带 code/message），exit 0，交 LLM 决策。"""
        card = _read_card("search")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": 1001, "error": "无权限", "data": None}
        with patch("api_console.call_card.load_cards", return_value={"search": card}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}), \
             patch("api_console.call_card.invoke_card",
                   return_value=call_card.InvokeResult(resp=resp, url="http://h/x", method="GET")):
            call_card.main(["--platform", "demo", "--card", "search"])
        out = json.loads(capsys.readouterr().out)
        assert out["meta"]["biz_code"] == 1001
        assert out["meta"]["biz_message"] == "无权限"
        assert out["data"] is None


class TestGuardrails:
    """只读约束 / 必填校验 / 卡片存在性。"""

    def test_write_card_blocked_without_allow_write(self):
        card = _read_card("create", side_effect="create", method="POST")
        with patch("api_console.call_card.load_cards", return_value={"create": card}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}):
            with pytest.raises(SystemExit):
                call_card.main(["--platform", "demo", "--card", "create"])

    def test_write_card_allowed_with_flag(self, capsys):
        """--allow-write 放行 write 卡片，正常调 invoke_card。"""
        card = _read_card("create", side_effect="create", method="POST")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": 0, "data": {"id": "new"}}
        with patch("api_console.call_card.load_cards", return_value={"create": card}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}), \
             patch("api_console.call_card.invoke_card",
                   return_value=call_card.InvokeResult(resp=resp, url="http://h/x", method="POST")) as inv:
            call_card.main(["--platform", "demo", "--card", "create", "--allow-write"])
        assert inv.called

    def test_missing_required_param_exits(self):
        card = _read_card("get", required=["modelId"])
        with patch("api_console.call_card.load_cards", return_value={"get": card}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}):
            with pytest.raises(SystemExit):
                call_card.main(["--platform", "demo", "--card", "get"])

    def test_unknown_card_exits(self):
        with patch("api_console.call_card.load_cards", return_value={}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}):
            with pytest.raises(SystemExit):
                call_card.main(["--platform", "demo", "--card", "nope"])


class TestParseParamsAtFile:
    """--param key=@<路径>：从文件读内容为值。"""

    def test_at_prefix_reads_file(self, tmp_path):
        f = tmp_path / "c.txt"
        f.write_text("CONTENT-文本")
        assert call_card.parse_params(["content=@" + str(f)]) == {"content": "CONTENT-文本"}

    def test_no_at_stays_literal(self):
        assert call_card.parse_params(["a=b"]) == {"a": "b"}

    def test_at_file_missing_exits(self):
        with pytest.raises(SystemExit):
            call_card.parse_params(["content=@/nonexistent/x.txt"])


class TestBinaryDownload:
    """非 JSON 响应 → 落盘 + 输出 {meta, file}。"""

    def _bin_resp(self, payload=b"\x1f\x8b tardown"):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/gzip"}
        resp.content = payload
        resp.json.side_effect = ValueError("not json")
        return resp

    def test_binary_default_download_path(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr(call_card, "_download_base", lambda: tmp_path)
        card = _read_card("exportSuite")
        resp = self._bin_resp()
        with patch("api_console.call_card.load_cards", return_value={"exportSuite": card}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}), \
             patch("api_console.call_card.invoke_card",
                   return_value=call_card.InvokeResult(resp=resp, url="http://h/e", method="GET")):
            call_card.main(["--platform", "demo", "--card", "exportSuite",
                            "--param", "pluginId=host"])
        out = json.loads(capsys.readouterr().out)
        saved = pathlib.Path(out["file"]["file_path"])
        assert saved.exists() and saved.read_bytes() == b"\x1f\x8b tardown"
        assert out["file"]["size"] == len(b"\x1f\x8b tardown")
        assert out["file"]["content_type"] == "application/gzip"

    def test_binary_out_path(self, capsys, tmp_path):
        card = _read_card("exportSuite")
        resp = self._bin_resp()
        target = tmp_path / "sub" / "pkg.tar.gz"
        with patch("api_console.call_card.load_cards", return_value={"exportSuite": card}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}), \
             patch("api_console.call_card.invoke_card",
                   return_value=call_card.InvokeResult(resp=resp, url="http://h/e", method="GET")):
            call_card.main(["--platform", "demo", "--card", "exportSuite",
                            "--param", "pluginId=host", "--out", str(target)])
        assert target.exists() and target.read_bytes() == b"\x1f\x8b tardown"
        out = json.loads(capsys.readouterr().out)
        assert out["file"]["file_path"] == str(target)

    def test_json_response_unchanged(self, capsys):
        """回归：JSON 响应仍输出 {meta, data}。"""
        card = _read_card("getTicket")
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/json"}
        resp.json.return_value = {"code": 0, "message": "ok", "data": {"id": "1"}}
        with patch("api_console.call_card.load_cards", return_value={"getTicket": card}), \
             patch("api_console.call_card.load_platform", return_value=(MagicMock(), {})), \
             patch("api_console.call_card.load_contracts", return_value={}), \
             patch("api_console.call_card.invoke_card",
                   return_value=call_card.InvokeResult(resp=resp, url="http://h/x", method="GET")):
            call_card.main(["--platform", "demo", "--card", "getTicket"])
        out = json.loads(capsys.readouterr().out)
        assert out["data"] == {"id": "1"}
        assert "file" not in out
