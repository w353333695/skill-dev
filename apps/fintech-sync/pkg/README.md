# fintech-cmdb-import 包说明

人行金融数据 CMDB 导入包（模型 + 实例，自包含，纯 py3 stdlib）。

## 内容

| 路径 | 内容 |
|---|---|
| `import_all.py` | 导入脚本（见下方用法） |
| `models/_all.json` | 43 个模型完整定义 = 7 抽象父模型（CUSTOM/cabinetAsset/netAsset/powerSupplyAsset/powerUsedAsset/serverAsset/storageAsset）+ 36 数据模型，父引用闭包完整 |
| `models/<name>.json` | 逐模型拆存（便于查看，导入不用） |
| `instances/<name>.json` | 36 模型实例数据（共 3314 行，**与 CMDB 兼容的最终写入形态**：structs=list[dict]、enums=list[str]） |

实例数据特性：
- **本包为「管理端覆盖上报端」版**（MERGE_PRIORITY=mgmt）：双源冲突取管理值；管理值无效（脱敏/空）回落上报值；差异仍记 _diffDetail
- `_dataSource`（enum：上报/管理/双源/双源(有差异)）+ `_diffDetail`（structs 数组：attr/reportValue/mgmtValue）溯源字段（继承自 CUSTOM@FINTECHDATA）
- `facilityOwnershipAgency` 已统一编号 `A1000141000266`
- lowVoltage 存在 4 条双写（双侧同实体不同键，既定决策）

## 已知外部依赖

- `softwareRelation@FINTECHDATA` 有一条关系引用平台内置模型 `USER_GROUP`（数据维护组）——目标环境必内置，导入不报错；若目标环境删过该内置模型，去 models 里删掉这条 relation_list 再导。

## 用法

```bash
# 1) 预检模型定义（不落库）
python3 import_all.py --host <IP> --check

# 2) 正式导入（模型 + 全部实例，upsert 幂等可重跑）
python3 import_all.py --host <IP>

# 3) 冲突环境清理导入（目标环境已有旧模型/定义冲突时）
#    删36模型全部实例 → 删36数据模型(forceDelete) → 导模型 → 导实例
python3 import_all.py --host <IP> --clean

# 4) 只导某模型实例
python3 import_all.py --host <IP> --only switches
```

参数：`--port 8079`（默认）、`--org 8888`、`--user easyops`、`--clean`、`--dry-run`。

## --clean 清理链语义（实测归纳）

- **删实例**：逐模型 search 取 instanceId（500/页）→ `instance_batch` 删（500/批）；模型不存在视为已清空
- **删模型**：仅 36 个数据模型，`DELETE /object/{id}?forceDelete=true`（force 连实例/关系强删）；模型不存在（133114）跳过
- **抽象父模型（CUSTOM/cabinetAsset/netAsset/powerSupplyAsset/powerUsedAsset/serverAsset/storageAsset 共 7 个）平台禁删**（130302 Can not drop abstract object）——不删，由导入 upsert 覆盖定义
- 顺序：清实例 → 清模型 → 导模型（父模型在列表前部）→ 导实例
- ⚠️ `--clean` 对目标环境同名模型是**破坏性操作**（旧实例全删），确认目标环境无他人数据后再用

## 导入语义

- 模型：`POST /v2/object_import`（声明式 upsert：存在更新/不存在建；父模型在列表前部保证先建）
- 实例：`POST /object/{id}/instance/_import`，`keys=[唯一键]`（实体=设施标识符 facilityDescriptor，关系=关系标识符 relationalIdentifier），500 条/批
- 直连后端只需三件 header（Host=admin.easyops.local / org / user），无需 cookie

## 验证记录（源环境 172.30.0.90 已真跑）

- 模型预检：43/43 成功
- 全量 upsert：36/36 模型 update=3314 failed=0；幂等回归 insert=0
- `--clean` 全链：清实例 3314 → 清模型 36/36 → 导模型 43/43 → 导实例 insert=3314 failed=0；重建后抽查 `_dataSource`/`switches_deployment`(structs)/`networkSecurityCapability`(enums)/机构编号 全部正确
- **mgmt 覆盖版**（本包）：全量 update=3314 failed=0；与 report 版数据面差异 = 2 条真差异行取管理侧值（powerSupplyRelation 端点/dataCenterSpacing 机房）+ 3 机构口径豁免属性取向管理侧
- **上报错误修复版**（2026-09-10，现行）：①引用字段（deployDb/所属机柜/宿主机/关系端点/软件设施）统一换库内 32 位设施标识符 ②编码保真（developmentLanguage/domainCharacteristics/softwareCategory 取编码形态侧）③机构字段（含 softwareOwnershipAgency）统一 A1000141000266 ④空值填充中文「未知」（CPU品牌属地沿用顶层）——预期上报错误 2942→~470；悬空引用 434 处清单见 `out/unresolved-references.json`（保留原值照旧上报，用户决策）

## 唯一键映射（与源环境一致）

实体模型用 `facilityDescriptor`；关系模型 + 以下例外：
- `application` → `applySystemIdentifiers`
- `basedSoftware` → `softwareDescriptor`
- `dataCenterSpacing` → `relationalIdentifier`（关系模型）
- 其余关系模型（powerSupplyRelation/networkRelation/applicationRelation/applicationSoftRelation/softwareRelation）→ `relationalIdentifier`

脚本 `import_all.py` 的 `KEY_ATTR` 已内置此映射。
