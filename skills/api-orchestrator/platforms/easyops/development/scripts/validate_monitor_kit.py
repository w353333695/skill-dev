#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 EasyOps 监控套件的包结构与附属资源契约。"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path


class ValidationError(Exception):
    pass


def load_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError("%s 不是合法 JSON: %s" % (label, exc))


def validate_alert(data, label, metric_keys):
    required = ("name", "objectId", "priority", "_rule_name_format", "alertConditionStrategy", "cmdbInstanceStrategy")
    for key in required:
        if key not in data:
            raise ValidationError("%s 缺少字段 %s" % (label, key))
    if not isinstance(data["alertConditionStrategy"], list):
        raise ValidationError("%s.alertConditionStrategy 必须是数组" % label)
    if not isinstance(data["cmdbInstanceStrategy"], list):
        raise ValidationError("%s.cmdbInstanceStrategy 必须是数组，不能是对象" % label)
    for index, strategy in enumerate(data["alertConditionStrategy"]):
        for key in ("name", "instanceId", "objectId", "conditionType", "multiConditions", "upgradeCondition"):
            if key not in strategy or strategy[key] in (None, ""):
                raise ValidationError("%s.alertConditionStrategy[%d] 缺少 %s" % (label, index, key))
        if not isinstance(strategy["multiConditions"], list):
            raise ValidationError("%s.alertConditionStrategy[%d].multiConditions 必须是数组" % (label, index))
        for condition in strategy["multiConditions"]:
            metric = condition.get("metricName")
            if metric and metric not in metric_keys:
                raise ValidationError("%s 引用了未定义指标 %s" % (label, metric))
    for index, strategy in enumerate(data["cmdbInstanceStrategy"]):
        if not isinstance(strategy, dict):
            raise ValidationError("%s.cmdbInstanceStrategy[%d] 必须是对象" % (label, index))
        for key in ("instanceId", "instances", "objectId"):
            if key not in strategy or not strategy[key]:
                raise ValidationError("%s.cmdbInstanceStrategy[%d] 缺少 %s" % (label, index, key))
        instances = strategy["instances"]
        if not isinstance(instances, dict) or not instances.get("objectId") or not instances.get("type"):
            raise ValidationError("%s.cmdbInstanceStrategy[%d].instances 必须包含 objectId/type" % (label, index))


def validate_dir(root, require_name_match=False):
    plugin = root / "plugin.yaml"
    if not plugin.exists():
        raise ValidationError("缺少 plugin.yaml")
    text = plugin.read_text(encoding="utf-8")
    name = re.search(r"(?m)^name:\s*(.+?)\s*$", text)
    version = re.search(r"(?m)^version:\s*[\"']?([^\"'\s]+)", text)
    if not name or not name.group(1).strip():
        raise ValidationError("plugin.yaml 缺少 name")
    if not version or not version.group(1).strip():
        raise ValidationError("plugin.yaml 缺少 version")
    if require_name_match and root.name != name.group(1).strip():
        raise ValidationError("ZIP/目录名 %s 与 plugin.yaml.name %s 不一致" % (root.name, name.group(1).strip()))
    source_files = list((root / "src").glob("*.py")) if (root / "src").exists() else []
    for source in source_files:
        orig = source.with_suffix(".orig")
        if not orig.exists() or orig.stat().st_size == 0:
            raise ValidationError("缺少与 %s 对应的 src/%s.orig" % (source.name, source.stem))
        source_text = source.read_text(encoding="utf-8")
        orig_text = orig.read_text(encoding="utf-8")
        if "ensure_ascii=False" in source_text or "ensure_ascii=False" in orig_text:
            raise ValidationError("%s 使用 ensure_ascii=False；Python 2.7遇到非ASCII字节串会UnicodeDecodeError，请使用默认ASCII escape" % source.name)
        if re.search(r"(?m)^\s*from\s+__future__\s+import\b", source_text) or re.search(r"(?m)^\s*from\s+__future__\s+import\b", orig_text):
            raise ValidationError("%s 或对应 .orig 使用 from __future__ import；平台注入参数后 future 导入可能不在文件开头，请在 Python 2 语法下显式实现除法/输出" % source.name)
        if source_text != orig_text:
            raise ValidationError("%s 与对应 .orig 内容不一致" % source.name)
    for forbidden in root.rglob("*"):
        if forbidden.is_file() and ("__pycache__" in forbidden.parts or forbidden.suffix == ".pyc"):
            raise ValidationError("ZIP/目录禁止包含缓存文件: %s" % forbidden.relative_to(root))
    param_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("- {name:")]
    param_names = set()
    for line in param_lines:
        name_match = re.search(r"\{name:\s*([^,}]+)", line)
        if name_match:
            param_names.add(name_match.group(1).strip())
    for line in param_lines:
        name_match = re.search(r"\{name:\s*([^,}]+)", line)
        param_name = name_match.group(1).strip() if name_match else "<unknown>"
        default_match = re.search(r"defaultValue:\s*([^,}]+)", line)
        default = default_match.group(1).strip().strip("'\"") if default_match else ""
        from_secret = bool(re.search(r"isFromSecret:\s*true", line))
        encrypt = bool(re.search(r"isEncrypt:\s*true", line))
        if default.startswith("$.") and (from_secret or encrypt):
            raise ValidationError("paramDefine.%s 使用$.动态取值时 isFromSecret/isEncrypt 必须为false" % param_name)
        if "valueType: password" in line and not default and "optional: false" in line and from_secret and "secretName" not in param_names:
            raise ValidationError("paramDefine.%s 是必填手填password，不能启用isFromSecret；应配置isEncrypt=true且isFromSecret=false" % param_name)
        if "valueType: password" in line and not from_secret and not encrypt:
            raise ValidationError("paramDefine.%s 是password时必须启用isEncrypt" % param_name)
    origin = load_json(root / "origin_metric.json", "origin_metric.json")
    metric_keys = {row.get("key") for row in origin if isinstance(row, dict) and row.get("key")}
    metric_sets = load_json(root / "metric_set.json", "metric_set.json")
    if not isinstance(metric_sets, list) or not metric_sets:
        raise ValidationError("metric_set.json 必须是非空数组")
    metric_set_names = set()
    for index, metric_set in enumerate(metric_sets):
        if not isinstance(metric_set, dict) or not metric_set.get("name"):
            raise ValidationError("metric_set.json[%d] 必须是包含非空 name 的对象，不能是字符串" % index)
        metric_set_names.add(metric_set["name"])
    alias_path = root / "alias_metric.json"
    aliases = load_json(alias_path, "alias_metric.json")
    if not isinstance(aliases, list) or not aliases:
        raise ValidationError("alias_metric.json 必须是非空数组")
    origin_dimensions = {
        row.get("key"): set(row.get("labels") or [])
        for row in origin
        if isinstance(row, dict) and row.get("key")
    }
    for index, alias in enumerate(aliases):
        if not isinstance(alias, dict):
            raise ValidationError("alias_metric.json[%d] 必须是对象" % index)
        for key in ("name", "objectId", "dataType", "type", "dims", "metricSet", "originalMetrics"):
            if key not in alias:
                raise ValidationError("alias_metric.json[%d] 缺少 %s" % (index, key))
        if not isinstance(alias["dims"], list) or not isinstance(alias["metricSet"], list) or not isinstance(alias["originalMetrics"], list):
            raise ValidationError("alias_metric.json[%d] 的 dims/metricSet/originalMetrics 必须是数组" % index)
        unknown_metric_sets = set(alias["metricSet"]) - metric_set_names
        if unknown_metric_sets:
            raise ValidationError("alias_metric.json[%d] 引用了未定义指标集 %s" % (index, sorted(unknown_metric_sets)))
        unknown = set(alias["originalMetrics"]) - metric_keys
        if unknown:
            raise ValidationError("alias_metric.json[%d] 引用了未定义原始指标 %s" % (index, sorted(unknown)))
        alias_dimensions = {row.get("dimName") for row in alias["dims"] if isinstance(row, dict)}
        if len(alias["originalMetrics"]) == 1:
            expected_dimensions = origin_dimensions.get(alias["originalMetrics"][0], set())
            if alias_dimensions != expected_dimensions:
                raise ValidationError("alias_metric.json[%d] 维度 %s 与原始指标标签 %s 不一致" % (index, sorted(alias_dimensions), sorted(expected_dimensions)))
    alert_dir = root / "alertRule"
    if alert_dir.exists():
        for path in alert_dir.glob("*.json"):
            validate_alert(load_json(path, str(path)), str(path), metric_keys)
    discovery = root / "resource_discovery_define.json"
    if discovery.exists():
        data = load_json(discovery, "resource_discovery_define.json")
        if not isinstance(data, list):
            raise ValidationError("resource_discovery_define.json 顶层必须是数组")
        for index, row in enumerate(data):
            if not isinstance(row, dict):
                raise ValidationError("resource_discovery_define.json[%d] 必须是对象" % index)
            for key in ("objectId", "category", "type"):
                if not row.get(key):
                    raise ValidationError("resource_discovery_define.json[%d] 缺少 %s" % (index, key))
    return "目录校验通过: %s (version=%s, metrics=%d, metricSets=%d)" % (name.group(1).strip(), version.group(1), len(metric_keys), len(metric_set_names))


def validate_zip(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        roots = {name.split("/", 1)[0] for name in names if "/" in name}
        if len(roots) != 1:
            raise ValidationError("ZIP 必须只有一个顶层套件目录，实际为 %s" % sorted(roots))
        root_name = next(iter(roots)) + "/"
        directories = {name for name in names if name.endswith("/")}
        for name in names:
            if name.endswith("/"):
                continue
            current = name.rsplit("/", 1)[0]
            missing = []
            while current:
                if current + "/" not in directories:
                    missing.append(current + "/")
                current = current.rsplit("/", 1)[0] if "/" in current else ""
            if missing:
                raise ValidationError("ZIP 文件 %s 缺少显式父目录条目 %s；EasyOps Go解压器不会自动创建父目录" % (name, sorted(missing)))
        temp = Path(".monitor-kit-validation")
        if temp.exists():
            raise ValidationError("临时校验目录已存在，请删除后重试: %s" % temp)
        temp.mkdir()
        try:
            archive.extractall(temp)
            return validate_dir(temp / root_name.rstrip("/"), require_name_match=True)
        finally:
            for child in sorted(temp.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            temp.rmdir()


def main():
    parser = argparse.ArgumentParser(description="校验 EasyOps 监控套件目录或 ZIP 的结构、指标集、告警和资源发现契约")
    parser.add_argument("package", help="套件目录或 ZIP 文件")
    args = parser.parse_args()
    path = Path(args.package)
    try:
        result = validate_zip(path) if path.suffix.lower() == ".zip" else validate_dir(path)
    except ValidationError as exc:
        print("校验失败: %s" % exc, file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
