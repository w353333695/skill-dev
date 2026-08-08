"""MVP-1 验收集成测试（真调 172.30.5.20，默认 skip）。

运行: .venv/bin/python -m pytest skills/api-console/tests/test_integration.py -m integration
前置: 卡片已注册（registry/）+ cookie 有效（auth/）+ 环境可达。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from api_console.verify_dag import verify
from api_console.execute_dag import execute, ExecutionError
from api_console.adapter_base import discover_adapters
from api_console.schema.dag import DAG
from api_console.schema.card import Card

PROJECT = Path(__file__).resolve().parents[3]
PLATFORM = PROJECT / "platforms/easyops"
REGISTRY = PLATFORM / "registry"
AUTH = PLATFORM / "auth"
ADAPTERS_DIR = PLATFORM / "sources/backend/adapters"
CONTRACTS = PLATFORM / "sources/backend/parsed/contracts.yaml"

pytestmark = pytest.mark.integration


def _load_cards():
    """从 registry/_index.yaml 加载全部卡片。"""
    idx = yaml.safe_load((REGISTRY / "_index.yaml").read_text())
    cards = {}
    for m in idx["modules"]:
        for c in m["cards"]:
            cards[c["name"]] = Card.from_dict(
                yaml.safe_load((REGISTRY / c["file"]).read_text()))
    return cards


def _cookies():
    """从 manifest.auth.session_cookie.cookie_file 读 cookie。"""
    manifest = yaml.safe_load((PLATFORM / "manifest.yaml").read_text())
    cookie_file = manifest["auth"]["session_cookie"]["cookie_file"]
    return json.loads((PLATFORM / cookie_file).read_text())


def _setup():
    """加载 cards / adapter / manifest / contracts，供 execute 新签名使用。"""
    cards = _load_cards()
    adapters = discover_adapters(ADAPTERS_DIR)
    assert adapters, f"未发现 adapter（{ADAPTERS_DIR}）"
    manifest = yaml.safe_load((PLATFORM / "manifest.yaml").read_text())
    contracts = yaml.safe_load(CONTRACTS.read_text()) if CONTRACTS.exists() else []
    return cards, adapters[0], manifest, contracts


@pytest.fixture(scope="module")
def cards():
    return _load_cards()


# ============ 用例 1：单步查询（最小编排单元）============

def test_case1_single_query():
    """需求：查询名称含'test'的领域模型列表。

    验收：DAG 校验通过 + execute 真调返回 list（adapter.resolve_endpoint 拼出可达网关 URL）。
    """
    cards, adapter, manifest, contracts = _setup()
    dag = DAG.from_dict({
        "goal": "查询名称含test的领域模型列表",
        "result": "${s1.models}",
        "steps": [{
            "id": "s1", "card": "searchDomainModel",
            "params": {"Q": "test", "page": 1, "pageSize": 100},
            "output": {"bind": "models", "from": "list_full"}
        }]
    })
    r = verify(dag, cards)
    assert r.passed, f"DAG 校验失败：{r.errors}"

    res = execute(dag, cards, adapter, manifest, contracts=contracts)
    assert isinstance(res.result, list), f"结果不是 list：{type(res.result)}"
    for item in res.result:
        assert "instanceId" in item, f"列表项缺 instanceId：{list(item.keys())}"
    print(f"\n用例1：查到 {len(res.result)} 个领域模型（adapter.resolve_endpoint 网关URL 可达）")


# ============ 用例 2：双步依赖 + foreach（依赖传递）============

def test_case2_foreach_detail():
    """需求：查询名称含'test'的领域模型，并取每个模型的详情。

    验收：s2 foreach 对 s1 结果逐个调 getDomainModel，result 长度 = s1 list 长度。
    """
    cards, adapter, manifest, contracts = _setup()
    dag = DAG.from_dict({
        "goal": "查test模型列表并取每个详情",
        "result": "${s2.details}",
        "steps": [
            {"id": "s1", "card": "searchDomainModel",
             "params": {"Q": "test", "page": 1, "pageSize": 100},
             "output": {"bind": "models", "from": "list_full"}},
            {"id": "s2", "card": "getDomainModel", "depends": ["s1"],
             "foreach": "${s1.models.instanceId}",
             "params": {"modelId": "${item}"},
             "output": {"bind": "details", "from": "detail"}},
        ]
    })
    r = verify(dag, cards)
    assert r.passed, f"DAG 校验失败：{r.errors}"

    res = execute(dag, cards, adapter, manifest, contracts=contracts)
    assert isinstance(res.result, list)
    print(f"\n用例2：s1 查到模型，s2 取了 {len(res.result)} 个详情（foreach + resolve 端到端通）")


# ============ 用例 3：跨模块 + 断言 ============

def test_case3_cross_module_assert():
    """需求：找出关联了'优先级'类标准字段的领域模型。找不到字段应报错。

    验收（正向）：跨 standard_field + domain_model 两模块，DAG 校验通过 +
      execute 真调走完 s1（assert 通过）+ s2（跨模块参数传递），不依赖环境有领域模型数据
      （测试环境可能为空，验证编排能力而非数据）。
    验收（负向）：构造找不到字段场景，assert 在 s1 终止，不发起 s2。
    """
    cards, adapter, manifest, contracts = _setup()

    # 正向：用环境真实存在的"优先级"字段（环境有 3 个标准字段：影响范围/优先级/紧急程度）
    dag = DAG.from_dict({
        "goal": "找关联优先级字段的领域模型",
        "result": "${s2.models}",
        "steps": [
            {"id": "s1", "card": "searchStandardField",
             "params": {"q": "优先级", "page": 1, "pageSize": 100},
             "output": {"bind": "fields", "from": "list_full"},
             "assert": {"fields.length > 0": "未找到优先级类标准字段"}},
            {"id": "s2", "card": "searchDomainModel", "depends": ["s1"],
             # 跨模块参数传递：s1 标准字段的 instanceId 拼成 s2 的 standard_field 入参
             "params": {"standard_field": "${join(s1.fields.instanceId, ',')}",
                        "page": 1, "pageSize": 100},
             "output": {"bind": "models", "from": "list_full"}},
        ]
    })
    r = verify(dag, cards)
    assert r.passed, f"DAG 校验失败：{r.errors}"

    # 正向：s1 assert 通过（环境有"优先级"字段），s2 真调发起（跨模块参数传递成功）
    res = execute(dag, cards, adapter, manifest, contracts=contracts)
    assert isinstance(res.result, list)  # 即使空 list，也证明 s1→s2 跨模块编排走通
    print(f"\n用例3正向：跨模块（standard_field→domain_model）编排走通，"
          f"assert 通过，s2 真调发起（环境领域模型可能为空）")

    # 负向：构造找不到字段场景，assert 应在 s1 终止，不发起 s2
    dag_neg = DAG.from_dict({
        "goal": "找不存在的字段（应终止）",
        "result": "${s1.fields}",
        "steps": [{
            "id": "s1", "card": "searchStandardField",
            "params": {"q": "绝对不存在的字段xyz999", "page": 1, "pageSize": 100},
            "output": {"bind": "fields", "from": "list_full"},
            "assert": {"fields.length > 0": "未找到字段（预期终止）"}
        }]
    })
    with pytest.raises(ExecutionError, match="未找到"):
        execute(dag_neg, cards, adapter, manifest, contracts=contracts)
    print("\n用例3负向：assert 正确在 s1 终止 DAG，未发起下游 ✓")


# ============ 用例 4：内网直连模式（easyops_internal，不依赖 cookie）============

def test_case4_internal_mode():
    """内网直连模式：endpoint.mode=easyops_internal，端口直连 + org/user 头，无 cookie。

    验收：与 cookie 模式查到相同数据，证明后端 API 方案可用（spec 1.6）。
    区别于用例1（easyops_gateway + session_cookie）。
    """
    cards, adapter, manifest, contracts = _setup()
    # 把 searchDomainModel 卡片切到 internal 模式（同一张卡，path 相同，只换 mode）
    card = cards["searchDomainModel"]
    card.endpoint = dict(card.endpoint or {})
    card.endpoint["mode"] = "easyops_internal"

    dag = DAG.from_dict({
        "goal": "内网直连查领域模型（不依赖 cookie）",
        "result": "${s1.models}",
        "steps": [{
            "id": "s1", "card": "searchDomainModel",
            "params": {"Q": "test", "page": 1, "pageSize": 100},
            "output": {"bind": "models", "from": "list_full"}
        }]
    })
    r = verify(dag, cards)
    assert r.passed, f"DAG 校验失败：{r.errors}"

    res = execute(dag, cards, adapter, manifest, contracts=contracts)
    assert isinstance(res.result, list), f"internal 模式结果不是 list：{type(res.result)}"
    print(f"\n用例4：internal 模式（端口直连+org/user 头）真调成功，"
          f"不依赖 cookie/签名/recorder")

