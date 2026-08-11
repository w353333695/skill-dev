# 编排规则（三挡位）

skill 的调度分三挡位，按需求的意图 + 复杂度选挡。

## 读取纪律（所有挡位前置，强制）

调度靠 LLM 推理、**无代码引擎兜底**——platforms 读取须守此纪律，保证一致 + 省 token：

1. **粗筛（必读，第一步）**：读 `systems.yaml` 的 `systems.<system>.capabilities`（resource.verb → 一句话用途），判需求可达性、命中哪个系统哪个 verb。systems.yaml 不大，全量读（含 `runtime` 坑一并看，避免踩雷如 update body flat / run inputs map）。
2. **按需读详情（命中后，禁止全量）**：命中 resource.verb 后，按需读对应段：
   - **精准定位**：先 `grep -n "关键词" platforms/demo/objects.yaml` 拿行号 → `Read --offset=<行号> limit=30` 取该段。一步命中，不读全文。
   - spec `<system>.yaml`：`grep -n "^\s*<verb>:" easyops-*.yaml` 定位 → Read 该 operation 段
   - `objects.yaml`：`grep -n "<对象名>:" objects.yaml` 定位 → Read 该对象的 fields + side_effects 段
   - `entities.yaml`：`grep -n "common_models\|<field>" entities.yaml` → 取速查表 / 锚
   - `flows/<flow>.yaml`：需求匹配某 flow 的 `trigger` 时才读该 flow（单文件不大可全读）
3. **禁止**：跳过 capabilities 直接猜 verb；不读 `runtime` 坑就写操作；`Read` spec/objects 全文（数百行费 token）。

例外：onboarding 模式录资料时全量读写（非调度读取）；systems.yaml 全量（入口 + 不大 + runtime 必看）。

## 直通挡（简单读查询）

触发：读查询、单系统、单步（如"查下有多少主机""列出 X 的实例"）。

流程：
1. 查 `platforms/<dep>/systems.yaml` → 找到目标系统的 spec + resource/verb。
2. 查 `entities.yaml`（如涉及跨字段）确认锚字段。
3. bash 调 api-cli：`api-cli --spec <spec> <resource> <verb> [args] [--format json]`（开发态用 `scripts/run.sh` 等价）。
4. 后处理（jq 数量/抽取字段/格式化）→ 答。

计数场景（"有几个/多少"）：默认读 stderr `_meta.total`（新版 binary），非空结果即输出；
  空结果（0 条）stderr 无 total——exit 0 即代表 0 条（错误走 exit≠0，可读）。
  objectId 速查 `entities.yaml#common_models`，body 最小化 `{fields:[instanceId],page_size:1}`。

无规划、无确认、一轮 bash。

## 确认挡（简单写操作）

触发：单系统写、1-2 步（如"删除 X 的主机""创建一个实例"）。

流程：
1. 查资料（systems + entities）。
2. （若按条件）先 search 拿目标列表。
3. **展示影响面给用户确认**（写闸门）。
4. 确认后 bash 执行写（delete/create/update）。
5. 答。

有确认门。

## 规划挡（复杂：跨系统/多步/build/change）

触发：跨系统、多步依赖、build（从 0 搭建）、change（局部增量改）、插件生命周期。

流程：
1. **解析需求** → 拆成要素（涉及哪些系统/对象/步骤）。
2. **查资料** → entities（实体映射）+ objects（对象关系/副作用）+ flows（流程模板）+ formats（格式包）。
3. **生成 plan** → 步骤序列（DAG 或增量），含数据流（step1 输出 → step2 输入）+ 副作用。写 `tmp/<task>/plan.md`。
4. **展示 plan → 用户确认**（复杂必确认）。
5. **分步执行** → bash 调 api-cli + 生成制品（BPMN/tar.gz）+ jq 数据流接线；中间产物写 `tmp/<task>/state.json`。
6. **校验** → 查 objects/formats 校验一致性。
7. **失败回滚** → 按 state.json 反向调 remove/delete。

多轮 bash，带状态，规划-执行分离。

## 数据流接线（规划挡的关键）

step 间传字段：bash 用 jq 抽上一步 api-cli 输出的字段，按 `entities.yaml` 的映射喂下一步。
```bash
host_id=$(api-cli ... search --format json | jq -r '.data.list[0].instanceId')
api-cli ... delete "$host_id"
```

## 确认门

- 读操作：直通，不确认。
- 写操作：展示影响面（删哪些、改什么），确认。
- 复杂操作：展示 plan，确认。
- 危险操作（批量删/发布）：必须确认 + 可选 `--dry-run` 预览。
