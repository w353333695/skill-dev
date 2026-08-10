---
name: model-topology
description: 从 CMDB 获取模型及关系数据，按分类自动分层布局（最多 3 级），生成 draw.io 格式拓扑图，支持 YAML/JSON 中间格式导出与手动编辑。
---
# CMDB 模型拓扑图生成器

根据 CMDB 模型及其关系生成可视化拓扑图，支持导出为 draw.io 格式。

## 核心能力

- 从 CMDB 获取模型信息和关系
- 按模型分类自动分层布局（支持最多 3 级分类）
- 生成 draw.io 格式文件，可二次编辑
- 支持导出为通用 YAML/JSON 中间格式

## 使用流程

### 1. 确认模型范围

生成拓扑图前，先确认要包含哪些模型。提供以下选项让用户选择：

**选项 A：指定模型列表**
```
请提供要包含的模型 ID 列表，如：
APP_SYSTEM@ONEMODEL, APPLICATION@ONEMODEL, HOST
```

**选项 B：按分类筛选**
```
请提供要包含的模型分类，如：
- 应用资源
- 基础设施
- 全部分类
```

**选项 C：所有未隐藏模型（默认）**
```
将获取所有未隐藏的模型，可能数量较多。
```

### 2. 获取模型列表

根据用户选择获取模型：

```bash
# 获取所有模型（默认）
python scripts/list_models.py --page-size 500 --host <easyops_host> --org <org_id>

# 按关键字筛选
python scripts/list_models.py --keyword "关键字" --host <easyops_host> --org <org_id>
```

从返回结果中提取模型 ID 列表，过滤掉 `isHidden: true` 的模型。

### 3. 生成拓扑图

```bash
# 从 CMDB 获取并生成 drawio
python scripts/generate_topology_drawio.py \
  --from-cmdb "MODEL1\MODEL2\MODEL3" \
  -o topology.drawio

# 同时导出 YAML 数据（可选）
python scripts/generate_topology_drawio.py \
  --from-cmdb "MODEL1\MODEL2\MODEL3" \
  --export-yaml topology_data.yaml \
  -o topology.drawio
```

### 4. 输出结果

告知用户：
1. 文件保存位置
2. 打开方式（draw.io 桌面版、VS Code 插件、在线版）
3. 如需调整布局，可在 draw.io 中手动编辑

## 命令参数

| 参数 | 说明 |
|------|------|
| `--from-cmdb "MODEL1\MODEL2"` | 从 CMDB 获取指定模型 |
| `--from-yaml file.yaml` | 从 YAML 文件加载数据 |
| `-o output.drawio` | 输出文件路径 |
| `--export-yaml file.yaml` | 同时导出 YAML 数据 |
| `--linear` | 使用线性布局（默认按分类） |

## 布局说明

### 分类层级布局（默认）

按模型的 `category` 字段自动分层：

```
┌─────────────────────────── 一级分类 ───────────────────────────┐
│  ┌─────────────── 二级分类 ───────────────┐                    │
│  │  ┌─── 三级分类 ───┐  ┌─── 三级分类 ───┐│                    │
│  │  │  [模型] [模型] │  │  [模型]        ││                    │
│  │  └────────────────┘  └────────────────┘│                    │
│  └────────────────────────────────────────┘                    │
└────────────────────────────────────────────────────────────────┘
```

分类解析规则：
- `l1` → 一级: l1
- `l1.l2` → 一级: l1, 二级: l2
- `l1.l2.l3.l4` → 一级: l1, 二级: l2, 三级: l3.l4

### 连线说明

- 显示关系名称和数量限制（如 `所属系统 (1:N)`）
- 使用正交连线，自动路由
- 圆弧跨线避免交叉

## 通用数据格式

支持导出/导入 YAML/JSON 格式，便于手动编辑或从其他数据源生成：

```yaml
title: 拓扑图标题
nodes:
  - id: MODEL_ID
    name: 模型名称
    category: 一级分类.二级分类
edges:
  - from: MODEL_A
    to: MODEL_B
    label: 关系名称
    cardinality: "1:N"
```

## 示例对话

**用户**: 帮我生成 CMDB 模型拓扑图

**响应**:
```
生成拓扑图前，请确认要包含哪些模型：

1. 指定模型列表 - 提供具体的模型 ID
2. 按分类筛选 - 指定模型分类（如：应用资源、基础设施）
3. 所有未隐藏模型 - 获取全部可见模型（默认）

请选择或直接提供模型列表：
```

**用户**: 应用资源和基础设施分类的模型

**响应**: 获取指定分类的模型，生成拓扑图...
