"""Card 单一真相源（spec 5.1）。

一张卡片 = 一个 API 操作的可执行描述，22 字段。本模块只做数据建模 + 校验，
不做注册/对齐/网络——后者在 register_cards / execute_dag。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------- 枚举常量（spec 5.1 / 5.2） ----------

VALID_SIDE_EFFECT = {"create", "update", "delete", "read", "action"}
VALID_PATH_SOURCE = {"backend_contract", "gateway_strip", "frontend_raw"}
VALID_CONFIDENCE = {"high", "medium", "low"}


# ---------- dataclass ----------

@dataclass
class FieldSchema:
    """请求/响应字段元信息。"""
    name: str
    type: str = "string"
    desc: str = ""


@dataclass
class OutputAnchor:
    """卡片 outputs 锚点：把响应里的某段 JSON 绑定到 bind 名。

    Attributes:
        name: 锚点名（同 dict key）
        jsonpath: ``$.`` 开头的 JSONPath，**不支持** ``[*]``
        desc: 锚点描述（LLM 补）
    """
    name: str
    jsonpath: str
    desc: str = ""


@dataclass
class RollbackParam:
    """回滚单参数映射：把本步 output 的某锚点值，填进回滚卡片的一个参数。

    一个 step 只有一个 output（单 bind+anchor），故多参数回滚（如 deleteFormVersion
    需 formId+versionId）通常共享一个**对象锚点**，再各自从对象里取不同字段。
    标量锚点场景 ``from_field`` 留空，直接用整个锚点值。

    Attributes:
        param_key: 回滚目标卡片接收值的参数名（目标 path 的占位符名，如
            deleteFormVersion 的 ``formId`` / ``versionId``）
        from_output: 本步 output 的锚点名/bind 名（verify 据此校验引用有效）
        from_field: 从该锚点对象里取的字段名；标量锚点时留空（直接用锚点值）。
            例如锚点 detail=$.data.lastestVersion（对象），from_field=formId 取其
            formId 字段；锚点 instanceId=$.data.instanceId（标量），from_field 留空。
    """
    param_key: str
    from_output: str
    from_field: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "RollbackParam":
        # 新格式：from_output / from_field；旧格式 param_from_output → from_output
        from_output = d.get("from_output") or d.get("param_from_output", "")
        return cls(param_key=d.get("param_key", ""),
                   from_output=from_output,
                   from_field=d.get("from_field", ""))


@dataclass
class Rollback:
    """写卡片失败回滚声明（MVP-1.5，多参数版）。

    回滚目标卡片 path 可能含多个占位符（如 deleteFormVersion 的
    ``/form/{formId}/version/{versionId}``），故用 ``params`` 列表表达"本步 output
    的哪些值 → 回滚卡片的哪些参数"。单参数场景即长度 1 的列表。

    向后兼容：``from_dict`` 接受旧格式（顶层 ``param_key``+``param_from_output``
    单值，或仅 ``param_from_output``），自动迁移为 ``params:[{...}]``，存量 16 张
    单参数卡片读入不中断；``to_yaml_dict`` 统一输出新格式。

    Attributes:
        api: 回滚用的卡片名（registry 内）
        params: list[RollbackParam]，≥1 条；每条把一个 output 值映射到一个回滚参数
    """
    api: str
    params: list  # list[RollbackParam]

    @classmethod
    def from_dict(cls, d: dict) -> "Rollback":
        """从 yaml 字典构造；兼容新旧两种格式。

        - 新格式：``params: [{param_key, from_output, from_field?}, ...]``
        - 旧格式：顶层 ``param_key`` + ``param_from_output``（单值）→ 迁移为单条 params
        - 旧格式（card-schema 示例形态）：仅 ``param_from_output`` → param_key 空
          （validate 会报 param_key 必填，提示补全）
        """
        api = d.get("api", "")
        raw_params = d.get("params")
        if raw_params:  # 新格式
            params = [RollbackParam.from_dict(p) if isinstance(p, dict) else p
                      for p in raw_params]
        else:  # 旧格式：顶层单值迁移
            params = [RollbackParam.from_dict({
                "param_key": d.get("param_key", ""),
                "param_from_output": d.get("param_from_output", ""),
            })]
        return cls(api=api, params=params)


@dataclass
class Card:
    """API 卡片：单一真相源。

    字段对齐 spec 5.1。``request`` 字段在 dataclass 内拆为 ``request_required``
    + ``request_properties``（方便校验/查询），``to_yaml_dict`` 再合并回原结构。
    """
    name: str = ""
    module: str = ""
    method: str = ""
    path: str = ""
    gateway_path: str = ""
    service: str = ""
    side_effect: str = ""
    path_source: str = ""
    path_confidence: str = ""
    tags: list = field(default_factory=list)
    summary: str = ""
    description: str = ""
    request_required: list = field(default_factory=list)
    request_properties: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    requires: list = field(default_factory=list)
    rollback: Optional[Rollback] = None
    examples: list = field(default_factory=list)
    confidence: dict = field(default_factory=dict)
    # 真调端点解析配置（spec 1.5 / 5.1）：
    #   {"contract_ref": "<operation_key>", "mode": "<adapter定义的调用模式>"}
    # contract_ref: adapter.resolve_endpoint 查后端契约用的 key（service|method|path）
    # mode: 提示 adapter 用哪种 resolve 逻辑；空表示用 adapter 默认模式
    endpoint: dict = field(default_factory=dict)
    # 来源追踪（batch-register 增量判断用，spec 复盘"监测录制时间"）：
    #   openapi_file: 来源 openapi 文件名
    #   openapi_hash: openapi 内容 SHA256（变了→需重注）
    #   recorded_at: openapi 录制时间（x-recorded-at 或文件 mtime）
    source: dict = field(default_factory=dict)
    # 本卡片注册时间（commit 时写入）
    registered_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        """从 yaml 字典构造；容忍缺字段。"""
        request = d.get("request") or {}
        outputs = {}
        for name, a in (d.get("outputs") or {}).items():
            if isinstance(a, OutputAnchor):
                outputs[name] = a
            elif isinstance(a, dict):
                outputs[name] = OutputAnchor(
                    name=name,
                    jsonpath=a.get("jsonpath", ""),
                    desc=a.get("desc", ""),
                )
        return cls(
            name=d.get("name", ""),
            module=d.get("module", ""),
            method=d.get("method", ""),
            path=d.get("path", ""),
            gateway_path=d.get("gateway_path", ""),
            service=d.get("service", ""),
            side_effect=d.get("side_effect", ""),
            path_source=d.get("path_source", ""),
            path_confidence=d.get("path_confidence", ""),
            tags=list(d.get("tags") or []),
            summary=d.get("summary", ""),
            description=d.get("description", ""),
            request_required=list(request.get("required") or []),
            request_properties=dict(request.get("properties") or {}),
            outputs=outputs,
            requires=list(d.get("requires") or []),
            rollback=Rollback.from_dict(d["rollback"]) if d.get("rollback") else None,
            examples=list(d.get("examples") or []),
            confidence=dict(d.get("confidence") or {}),
            endpoint=dict(d.get("endpoint") or {}),
            source=dict(d.get("source") or {}),
            registered_at=d.get("registered_at", ""),
        )

    def to_yaml_dict(self) -> dict:
        """序列化回 yaml 字典（对齐 spec 5.1 结构）。"""
        return {
            "name": self.name,
            "module": self.module,
            "method": self.method,
            "path": self.path,
            "gateway_path": self.gateway_path,
            "service": self.service,
            "side_effect": self.side_effect,
            "path_source": self.path_source,
            "path_confidence": self.path_confidence,
            "tags": list(self.tags),
            "summary": self.summary,
            "description": self.description,
            "request": {
                "required": list(self.request_required),
                "properties": dict(self.request_properties),
            },
            "outputs": {
                name: {"jsonpath": a.jsonpath, "desc": a.desc}
                for name, a in self.outputs.items()
            },
            "requires": list(self.requires),
            "rollback": ({"api": self.rollback.api,
                          "params": [{"param_key": p.param_key,
                                      "from_output": p.from_output,
                                      "from_field": p.from_field}
                                     for p in self.rollback.params]}
                         if self.rollback else None),
            "examples": list(self.examples),
            "confidence": dict(self.confidence),
            "endpoint": dict(self.endpoint),
            "source": dict(self.source),
            "registered_at": self.registered_at,
        }

    def validate(self) -> list:
        """返回错误信息列表；空列表表示通过。"""
        errs = []
        # 必填
        for f in ("name", "module", "method", "path"):
            if not getattr(self, f):
                errs.append("必填字段 " + f + " 缺失")
        # 枚举
        if self.side_effect and self.side_effect not in VALID_SIDE_EFFECT:
            errs.append("side_effect 取值非法：" + self.side_effect
                        + "（合法：" + ",".join(sorted(VALID_SIDE_EFFECT)) + "）")
        if self.path_source and self.path_source not in VALID_PATH_SOURCE:
            errs.append("path_source 取值非法：" + self.path_source
                        + "（合法：" + ",".join(sorted(VALID_PATH_SOURCE)) + "）")
        if self.path_confidence and self.path_confidence not in VALID_CONFIDENCE:
            errs.append("path_confidence 取值非法：" + self.path_confidence)
        # 锚点 jsonpath 必须 $. 开头
        for name, a in self.outputs.items():
            if not (a.jsonpath or "").startswith("$."):
                errs.append("outputs." + name + ".jsonpath 必须 $. 开头：" + repr(a.jsonpath))
        # endpoint：若提供，mode 可空（由 adapter.resolve_call_mode 真调时动态决定，
        # 见 adapter_base.BackendAdapter.resolve_call_mode；平台特定，主干不写死）。
        # 想固定 mode 的卡片仍可显式写 endpoint.mode。
        # rollback：若提供则 api + params 必填，每条 param_key/param_from_output 非空（spec MVP-1.5）
        if self.rollback:
            if not self.rollback.api:
                errs.append("rollback.api 不能为空")
            if not self.rollback.params:
                errs.append("rollback.params 不能为空（至少一条参数映射）")
            for i, p in enumerate(self.rollback.params):
                if not p.param_key:
                    errs.append("rollback.params[" + str(i) + "].param_key 不能为空（回滚卡片的参数名）")
                if not p.from_output:
                    errs.append("rollback.params[" + str(i) + "].from_output 不能为空（本步 output 锚点/bind 名）")
        return errs
