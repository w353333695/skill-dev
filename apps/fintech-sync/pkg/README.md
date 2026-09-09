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
- `_dataSource`（enum：上报/管理/双源/双源(有差异)）+ `_diffDetail`（structs 数组：attr/reportValue/mgmtValue）溯源字段（继承自 CUSTOM@FINTECHDATA）
- `facilityOwnershipAgency` 已统一编号 `A1000141000266`
- 双源合并：脱敏值无效、上报优先；lowVoltage 存在 4 条双写（双侧同实体不同键，既定决策）

## 已知外部依赖

- `softwareRelation@FINTECHDATA` 有一条关系引用平台内置模型 `USER_GROUP`（数据维护组）——目标环境必内置，导入不报错；若目标环境删过该内置模型，去 models 里删掉这条 relation_list 再导。

## 用法

```bash
# 1) 预检模型定义（不落库）
python3 import_all.py --host <IP> --check

# 2) 正式导入（模型 + 全部实例，upsert 幂等可重跑）
python3 import_all.py --host <IP>

# 3) 只导某模型实例
python3 import_all.py --host <IP> --only switches
```

参数：`--port 8079`（默认）、`--org 8888`、`--user easyops`、`--dry-run`。

## 导入语义

- 模型：`POST /v2/object_import`（声明式 upsert：存在更新/不存在建；父模型在列表前部保证先建）
- 实例：`POST /object/{id}/instance/_import`，`keys=[唯一键]`（实体=设施标识符 facilityDescriptor，关系=关系标识符 relationalIdentifier），500 条/批
- 直连后端只需三件 header（Host=admin.easyops.local / org / user），无需 cookie

## 验证记录（源环境 172.30.0.90 已真跑）

- 模型预检：43/43 成功
- 全量 upsert：36/36 模型 update=3314 failed=0
- 幂等回归：insert=0 update=3314 failed=0

## 唯一键映射（与源环境一致）

实体模型用 `facilityDescriptor`；关系模型 + 以下例外：
- `application` → `applySystemIdentifiers`
- `basedSoftware` → `softwareDescriptor`
- `dataCenterSpacing` → `relationalIdentifier`（关系模型）
- 其余关系模型（powerSupplyRelation/networkRelation/applicationRelation/applicationSoftRelation/softwareRelation）→ `relationalIdentifier`

脚本 `import_all.py` 的 `KEY_ATTR` 已内置此映射。
