# 人行双平台数据统一到 CMDB — 设计 Spec

- 日期：2026-09-09
- 作者：wwh（经 brainstorming 澄清）
- 状态：待审阅
- 交付根：`tmp/fintech-sync/`（脚本/测试/文档/产物全在此）

## 1. 背景与目标

两个平台各持一套人行金融数据（Excel 导出）：

| 源 | 目录 | 规模 |
|---|---|---|
| 人行上报 | `tmp/人行上报/` | 36 文件 / 3312 数据行（含全空「维修信息」sheet） |
| 人行管理 | `tmp/人行管理/` | 34 文件 / 3282 数据行 |

目标：合并写入 EasyOps CMDB 的 `@FINTECHDATA` 模型族，标记数据来源，记录两源差异明细，最终封装为 EasyOps 平台工具（工具化为二阶段，本期只做本地验证）。

## 2. 需求决策记录（澄清结论）

| 决策点 | 结论 |
|---|---|
| 实体合并策略 | 同一实体合并为一条 CMDB 实例，**设施标识符**为唯一键 |
| 关联关系合并 | 一并写入，**关系标识符**为唯一键 |
| 冲突取值 | 管理侧脱敏值（`******` 等）视为无效；有效冲突时**上报优先** |
| 差异记录 | CUSTOM@FINTECHDATA 加两属性：数据来源（enum）+ 差异明细（**struct 数组**） |
| 枚举处理 | **以 CMDB 模型定义为准**（enum 属性合法值在 value.regex 数组，如 `00-设施在用`）；excel 侧值查 ENUM_MAP 归一 |
| 写入范围 | 全量（30+ 实体/关系模型，~3300 行）；upsert 幂等可重跑 |
| 执行形态 | 本地脚本验证通过后封装 EasyOps 工具包（二阶段） |
| 配置形态 | **单脚本 + 纯 Python 变量配置**（dict/list 嵌套，不用 yaml） |

## 3. 调研发现（数据真相）

### 3.1 文件 ↔ 模型映射差异

- 命名差异：`入侵检测与防御设备（IDS_IPS）`↔`入侵检测与防御设备`、`机柜`↔`普通机柜`、`虚拟机资源`↔`虚拟机`、`视频监控类`↔`视频监控系统`
- 仅上报有：数据中心、加湿系统、机柜（多类型归一）
- 实体高度重叠：交换机 407↔407（名称全交集）；防火墙 36↔35（1 条仅上报有）

### 3.2 字段差异（交换机样本）

- 同义不同名：`资产编码`↔`资产编码（可读性标识编码）`、`资产价值(万元)`↔`资产价值`、`设备高度(U)`↔`设备高度`、`板卡数量(个)`↔`板卡数量`
- 上报独有 17 列（运维部门/管理部门/服务提供商/服务开始截止时间/服务级别/数据责任人等）
- 管理独有：`设施信息更新日期`、`设施归属机构名称`
- 审计字段（两边/上报侧的 记录ID/拥有者/创建者/创建时间/最近修改时间/数据校验结果）不进 CMDB

### 3.3 值差异

- 脱敏：管理侧管理IP `******`（交换机 357/407 与上报不同，主因脱敏）
- 枚举形态：上报 `00-设施在用`（=CMDB 合法值直通）；管理 `设施在用`（裸值需映射）；另见 `1-True`/`是` → `True`
- CMDB 枚举定义实测：合法值存于 attr.value.regex 数组（enumList 为空是常态）

### 3.4 关联关系模型端点

供电/网络线路/应用系统等关系模型的端点字段（用电设施/供电设施）在 CMDB 中是 **str 属性**（非 relation 引用）；excel 侧名称/hexID 混合，转换保留原值直写。

## 4. 总体架构

单文件 `tmp/fintech-sync/sync.py`（py3），四阶段顺序执行，支持 `--stage <name>` 单跑：

```
sync.py
├── CONFIG 区（顶部集中，纯 dict/list）
│   ├── MODEL_MAP   # excel主名 → {model_id, key, mgmt_alias}
│   ├── FIELD_MAP   # model_id → [(上报列, 管理列|None, cmdb属性id), ...]
│   ├── ENUM_MAP    # cmdb属性id → {excel值 → cmdb合法值}
│   └── RULES       # invalid_values/skip_sheets/skip_columns/date 处理
├── investigate()   # 拉 CMDB schema → 校验/生成配置骨架 → 调研报告
├── transform()     # excel → 统一 json（配置驱动）
├── compare()       # 合并 + 比对 → merged json + 差异报告
└── import_cmdb()   # 生成 body → api-cli 写入 → 对账
└── out/            # 产物（全落盘可审查）
```

数据流：`tmp/人行{上报,管理}/*.xlsx` → transform（各边独立）→ compare（按唯一键合并）→ import（upsert）。

## 5. CONFIG 配置结构

```python
MODEL_MAP = {
  '交换机': {'model_id': 'switches@FINTECHDATA', 'key': '设施标识符'},  # mgmt_alias 缺省=同名
  '入侵检测与防御设备（IDS_IPS）': {'model_id': 'idsIps@FINTECHDATA', 'key': '设施标识符',
                                   'mgmt_alias': '入侵检测与防御设备'},
  '机柜': {'model_id': 'commonCabinet@FINTECHDATA', 'key': '设施标识符', 'mgmt_alias': '普通机柜'},
  '虚拟机资源': {'model_id': 'virtualMachine@FINTECHDATA', 'key': '设施标识符', 'mgmt_alias': '虚拟机'},
  '供电关联关系': {'model_id': 'powerSupplyRelation@FINTECHDATA', 'key': '关系标识符'},
  # …全量见脚本；上报独有模型无 mgmt 侧
}
FIELD_MAP = {
  'switches@FINTECHDATA': [
    ('设施标识符', '设施标识符', 'facilityDescriptor'),
    ('资产编码', '资产编码（可读性标识编码）', 'assetCode'),      # 同义不同名
    ('运维部门', None, 'opsDepartment'),                        # 仅上报
    (None, '设施信息更新日期', 'facilityUpdateDate'),            # 仅管理
  ], # …
}
ENUM_MAP = {
  'facilityUseState': {'设施在用': '00-设施在用', '设施已停用': '01-设施已停用'},
  'supportIpv6': {'是': 'True', '1-True': 'True'},
}
RULES = {
  'invalid_values': ['******'],
  'skip_sheets': ['维修信息'],
  'skip_columns': ['记录ID','拥有者','创建者','创建时间','最近修改时间','数据校验结果'],
}
```

要点：
- investigate 自动拉 schema **生成 FIELD_MAP/ENUM_MAP 骨架**（属性 id/名/类型/regex 枚举），人工只补列名对应
- ENUM_MAP 只列需映射的裸值；与 CMDB 合法值相同的直通
- 三元组 None 语义 = 单边字段，合并天然处理
- 日期统一不需要配置：按 CMDB 属性 value.type=date 自动识别（§7）

## 6. 阶段逻辑

### 6.1 investigate()
1. 逐模型 `object_model detail`（经 api-cli）取 attrList
2. 校验 MODEL_MAP 的 model_id 存在、key 属性存在
3. 生成 FIELD_MAP/ENUM_MAP 骨架 → `out/config-skeleton.py`（供人工补列名）
4. 校验 CUSTOM 两属性（§7）存在且结构一致，缺则自动补建
5. 输出 `out/investigate.md`

### 6.2 transform(side)
- 读 excel 主 sheet（跳过 skip_sheets/skip_columns）→ 按 FIELD_MAP 取 side 对应列 → 属性 id 为键
- 枚举查 ENUM_MAP（值=CMDB 合法值直通；裸值查表；查不到收集错误不中断）
- 清洗：invalid_values→None、日期统一 `YYYY-MM-DD`、strip
- 落盘 `out/transformed/{side}/{model_id}.json`

### 6.3 compare()
- 按 key 建索引合并：仅上报/仅管理/双源
- 双源逐属性：mv 无效且 rv 有效→rv；rv 无效且 mv 有效→mv；相等→取值；都有效不等→**上报优先 + 记差异**
- 附加 `_dataSource`（上报/管理/双源/双源(有差异)）与 `_diffDetail`（struct 数组：attr/reportValue/mgmtValue）
- 落盘 `out/merged/{model_id}.json` + `out/diff-report.md`（统计+明细）；缺 key 行进 `out/orphan.json` 不写入

### 6.4 import_cmdb()
- 试点先行：交换机 407 条写入 → search 验证 + 抽查 CUSTOM 属性 → 人工确认后全量
- `object_instance import`（keys=[key属性id]，upsert），失败不中断逐模型汇总
- 终验：逐模型 search total 对账 merged 行数

## 7. CUSTOM@FINTECHDATA 属性补充

| 属性 id | 名称 | 类型 | 定义 |
|---|---|---|---|
| _dataSource | 数据来源 | enum | regex: `['上报','管理','双源','双源(有差异)']` |
| _diffDetail | 差异明细 | struct | struct_define: `attr`(str,属性id) / `reportValue`(str) / `mgmtValue`(str)；值为数组 |

经模型继承自动生效到全部子模型（父模型属性子模型可见）。
- 属性 id 带 `_` 前缀是平台「新增属性」识别约定（objects.yaml#cmdb_object），最终落库 id 即 `_dataSource`/`_diffDetail`，merged json 与 FIELD_MAP 引用同此 id。
- 日期统一格式不需要单独配置：按 CMDB 属性 `value.type=date` 自动识别并统一为 `YYYY-MM-DD`。

## 8. 工具化路径（二阶段，本期不实施）

按 `platforms/easyops/flows/develop-tool-package.yaml`：脚本进 `script/`（py2/py3 双兼容、CMDB 地址走 `EASYOPS_CMDB_SERVICE_HOST` header 变量、PutStr/PutRow 输出协议）、CONFIG 进 `config/`、三件套 tar.gz 导入、`tool_execution.run` 真跑调试。

## 9. 测试计划

**单测**（`test_sync.py`，pytest）：
- normalize_row：列映射 / 枚举归一 / 脱敏置空 / 日期统一
- merge：双源相等 / 单边 / 脱敏覆盖 / 真差异记明细

**集成验证**（真数据）：
1. transform 两边全量 0 报错，行数对账（3312 / 3282，扣除空 sheet 与 skip）
2. compare 交换机抽 10 条人工核对差异明细与 excel 原值一致
3. import 试点（交换机）→ total=407 + 抽查 3 条 CUSTOM 属性
4. 全量写入 + 终验对账
5. 回归：重跑全量 update 无 insert（幂等）

## 10. 交付物清单

| 文件 | 内容 |
|---|---|
| `tmp/fintech-sync/sync.py` | 单脚本四阶段 |
| `tmp/fintech-sync/test_sync.py` | 单测 |
| `tmp/fintech-sync/spec.md` | 本文档 |
| `tmp/fintech-sync/out/investigate.md` | 模型 schema 调研报告 |
| `tmp/fintech-sync/out/config-skeleton.py` | FIELD_MAP/ENUM_MAP 骨架 |
| `tmp/fintech-sync/out/diff-report.md` | 两源差异报告 |
| `tmp/fintech-sync/out/transformed/` `out/merged/` | 中间 json |
| `tmp/fintech-sync/out/import-result.json` | 写入对账 |

## 11. 范围外

- 维修信息 sheet（当前全空）
- CMDB 业务模型属性变更（仅加 CUSTOM 两属性）
- 工具包导入与平台执行（二阶段）
- 差异的人工裁决回填（差异只记录不解决）
