---
name: browser-manual
description: This skill should be used when the user asks to "生成操作指引", "输出guide", "分析录制session", "浏览器录制转文档", "session.jsonl转md", "操作手册生成", "录制结果分析", "API逆向", "从录制提取接口", "browser-recorder生成文档", "guide.md", or wants to turn a browser-recorder session (session.jsonl + screenshots) into an illustrated operation guide and/or API analysis report.
---

# browser-manual：录制 session → 图文操作指引 / API 分析报告

把 browser-recorder 录制的 session（`session.jsonl` + `screenshots/`）转成**图文操作指引 guide.md**（+可选 **api-report.md** / **api-calls.json**）。本 skill 只做分析与排版编排，不携带录制能力（录制用 `projects/browser-recorder` CLI）。

## 何时使用

用户拿着一个录制 session 目录（含 `session.jsonl`），说“生成指引/出文档/分析操作/API 逆向/提取接口”。

## 输入识别（先做）

```
<session_dir>/
├── session.jsonl      # 必需。事件流：action/screenshot/nav/request/response/response_body/...
├── screenshots/       # 必需。NNNN-before.png / NNNN-after.png（红框标注）
└── PROMPT.md          # 可能有，忽略（本 skill 的规则更完整，取代它）
```

**先快速统计再动手**（决定文档骨架）：

```bash
python3 -c "
import json,collections
lines=[json.loads(l) for l in open('<session_dir>/session.jsonl')]
print('事件数',len(lines))
print(collections.Counter(l['kind'] for l in lines))
print('tabs', [l.get('tabs') for l in lines if l['kind']=='session_end'])
"
```

## 事件模型（LLM 必读，免探索）

**统一编号**：每个事件有递增 `seq`（全类型共用计数器）与 `t_mono`（单调毫秒时钟）。**排序键 = t_mono**（seq 连续但时间上 request/response_body 可能乱序回填）。

| kind | 含义 | 关键字段 |
|---|---|---|
| `action` | 用户动作 | `type`(click/input/submit)、`element.rect`(视口CSS坐标)、`element.descriptor`(tag/id/text/dom_path)、`value`(输入值,**password已脱敏***)、`target_id`(t0/t1=第几个tab) |
| `screenshot` | 截图登记 | `action_seq`→**关联动作的seq**、`phase`(before/after)、`file`（文件名=动作seq-阶段.png）、`status`(ok/stable/timeout/raced/failed) |
| `nav` | 页面导航 | `url`、`target_id`、`recovered:true`=挂域晚补录 |
| `request`/`response`/`response_body` | 网络 | `request_id` 三者互联；request 带 url/method/headers/post_body；response 带 status；response_body 带 body（body_base64=true 时是base64） |
| `dom_mutations` | DOM 变化脉冲 | `count`（仅用于理解页面活跃度） |
| `note` | 辅助标记 | tab closed 等 |

**动作↔请求归组规则**：request 的 `t_mono` 落在 [动作A.t_mono, 下一动作B.t_mono) 区间 → 归 A。同区间内以 `/api/`、网关路径（`/gateway/`）优先为业务请求；`sa-static`/`.js`/`.css`/图标/`ClickHouseInsertData`(埋点)/公告轮询 一律折叠为噪声。

## 截图选用规则（核心，保证效果）

**每张图 = `文件名前缀(动作seq)` + `-before/after.png`**。按动作效果分三类选图：

| 动作性质 | 选用 | 理由 |
|---|---|---|
| **点击引发跳转/弹层打开**（click 后紧跟 nav 或新 modal 请求） | **before** | before=动作瞬间现场，红框正落在被点元素上；after 页面已变，框会指空 |
| **点击触发状态变化但不离开页面**（勾选、tab 切换、下拉选中项） | **before 为主，after 为辅** | before 标“点哪”，after 展示“变成什么”，两张连排 |
| **输入框填写** | **before**（框住输入框，value 已在事件里，不必看图认字） | after 可能因聚合窗内页面滚动而偏移 |
| **提交后结果确认**（submit / 提交类 click 后页面大变） | **after** | 展示操作效果/成功态 |

**跳过引用**：`status=raced/failed` 的图。**零尺寸元素**（rect.w=0）没有红框，只有元素文字描述——引用时配文字说明位置。

## 输出物与排版（固定模板，保证一致性）

输出目录 = `<session_dir>/../guide-output/<文档名>/`（**自动命名**：用户指定名优先；否则从 nav URL 主题+核心动作提炼，如 `监控套件创建与删除`）。只**拷贝被引用的截图**到输出目录（session 原目录不动）。

### guide.md 固定骨架

````markdown
# <主题> · 图文操作指引
> 由 browser-recorder session `<目录名>` 生成（N 动作 / M 截图 / K 事件）。
> 红框=操作位置；`t0/t1`=主/新标签页。

## 一、<阶段名：登录>            ← 阶段=nav 大节点切分
### 1.1 <动词短语步骤名>
<一句话：在哪点什么/输什么（值来自 action.value）>
![步骤名](screenshots/<选用图>.png)
...（每小节 = 1 个动作，格式严格一致：标题/说明/图）

## 二、<阶段名：主流程>
...

---

# 附录：本录制涉及页面与接口概览   ← 仅概览表；详析在 api-report（若启用）
| 步骤 | 接口 | 说明 |
````

**排版硬规则**：①每步骤小节三要素（标题动词短语/一句操作说明/一张图）不增删；②连续 input 到同一表单合并为一小节（每字段一行）；③图注格式统一 `![<步骤名>](screenshots/<file>)`；④password 显示 `***`（保持脱敏，禁止还原）；⑤只用实际存在的事件，禁止臆测。

**排版一致性机制**：上面的骨架是速览——**`references/guide-template.md` 是唯一排版真源**（文档级模板 + 3 种小节模板块 + 逐条自查硬规则 + 格式基准示例）。生成 = 填 «占位符» + 复制模板块，禁止自创结构。API 报告用 `references/api-report-format.md` 的七字段模板。

### api-report.md（可选，用户要求时）

每接口一节，固定字段序：

````markdown
# API 分析报告 · <主题>
> 源 session 同上。业务接口 N 个（噪声已折叠），按出现序排列。

## 1. <推断的接口用途名>（如：创建监控套件）
- **endpoint**: `POST /完整路径`（url 从 request 事件原样取，超长不截断）
- **触发时机**: 步骤 6「提交」之后（关联 action seq=2586）
- **请求体**（实测值→字段语义标注）:
```json
{ ...原样 body，每个字段行尾 // 注释语义... }
```
- **响应要点**: `{"code":0,...}` → data.instanceId 即新建资源 ID
- **脚本调用建议**: 必备头（Cookie/Content-Type）/ 依赖链（需先登录拿会话；A 的响应字段是 B 的入参）

## 2. ...
````

### api-calls.json（可选，机器可读，供脚本/编排消费）

```json
{
  "session": "<目录名>",
  "generated_at": "<ISO时间>",
  "base_url": "http://...",
  "calls": [
    {
      "seq": 1,
      "purpose": "创建监控套件",
      "triggered_by_action": 2586,
      "step_title": "六、提交保存",
      "method": "POST",
      "path": "/next/api/gateway/...",
      "request_body": {},
      "response_body_excerpt": {},
      "depends_on": [],
      "notes": "category 传显示名；instanceId 供删除用"
    }
  ]
}
```

## 工作流

1. **统计 session**（上面的识别命令）→ 确定动作数/tab 数/是否有登录
2. **提取动作骨架**：action 事件按 t_mono 排列，对照 nav 切阶段
3. **按截图选用规则**给每个动作定图；`raced/failed` 剔除
4. **建输出目录**，拷贝选用截图到 `输出/screenshots/`
5. **按固定骨架写 guide.md**（引用相对路径 `screenshots/...`）
6. 用户要求 API 分析 → 追加 api-report.md（+api-calls.json）
7. **自检**：引用的图都存在？每小节三要素齐？password 全 `***`？URL 未截断？

## 硬约束

- 只用 session.jsonl 实际事件；URL/body 原样拷贝**不截断**
- 脱敏字段保持 `***`；敏感参数（token= 等）在报告中原样保留 `***` 形态
- 输出目录独立于 session（`guide-output/<名>/`），session 原目录只读
- 用户指定文档名 > 自动命名；自动名从内容提炼，禁止"未命名文档"类占位
