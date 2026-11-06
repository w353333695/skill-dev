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
        if not data.get(key):
            raise ValidationError("%s 缺少非空字段 %s" % (label, key))
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
    origin = load_json(root / "origin_metric.json", "origin_metric.json")
    metric_keys = {row.get("key") for row in origin if isinstance(row, dict) and row.get("key")}
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
    return "目录校验通过: %s (version=%s, metrics=%d)" % (name.group(1).strip(), version.group(1), len(metric_keys))


def validate_zip(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        roots = {name.split("/", 1)[0] for name in names if "/" in name}
        if len(roots) != 1:
            raise ValidationError("ZIP 必须只有一个顶层套件目录，实际为 %s" % sorted(roots))
        root_name = next(iter(roots)) + "/"
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
    parser = argparse.ArgumentParser(description="校验 EasyOps 监控套件目录或 ZIP 的结构、告警和资源发现契约")
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
