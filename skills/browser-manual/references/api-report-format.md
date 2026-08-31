# API 分析输出格式细则

api-report.md（人读）与 api-calls.json（机读）的字段规范与质量标准。

## 业务接口识别

从 request 事件筛选，**噪声清单**（折叠不计入）：

- 静态资源：`.js .css .png .svg .woff .ico .map`、路径含 `sa-static`/`static/`
- 埋点/监控：`ClickHouseInsertData`、`collect`、`/monitor/report`
- 轮询类：`announce`、`site_msg_count`、`_search`（无用户动作触发的定时查询——判定：同 URL 在无动作区间反复出现 ≥3 次）
- 认证保活：`auth/login`（GET 探活）

**判定优先级**：用户动作后 1.5s 内触发 > URL 含 `/api/gateway/` > 含业务名词（kit/plugin/job/instance）。

## api-report.md 每接口七字段（顺序固定）

1. **用途名**（标题）：动词短语，从触发步骤+路径推断，如“创建监控套件”
2. **endpoint**：`METHOD 完整path`——path 从 request.url 原样取（urlsplit 取 scheme外的全部），**禁止截断加 `...`**
3. **触发时机**：`步骤 <编号>「<标题>」` + action seq（回链 guide 小节）
4. **请求体**：JSON 原样 + 行尾 `//` 语义注释；query 参数单独一行列出。敏感值保持 `***`
5. **响应要点**：状态码 + body 的 data 层关键字段（不贴全 body，超 50 行摘 data）
6. **依赖链**：`depends_on: [前置接口用途名]`；说明哪个响应字段是下一个请求的入参
7. **脚本调用建议**：最小 curl 或等效（headers 只列必备项：Cookie/Content-Type/Authorization——值用占位）

## api-calls.json schema

```json
{
  "session": "20260830-175753",
  "generated_at": "2026-08-30T18:30:00+08:00",
  "base_url": "http://172.30.0.90",
  "calls": [{
    "seq": 1,                        // 本报告内序号（非事件 seq）
    "purpose": "创建监控套件",
    "triggered_by_action": 2586,     // 事件 seq（可回查 session.jsonl）
    "step_title": "六、提交保存",
    "method": "POST",
    "path": "/next/api/gateway/...", // 完整不截断
    "query": {"instanceId": "..."},  // 可选
    "request_body": {},              // 原样（脱敏保持）
    "response_body_excerpt": {},     // data 层关键部分
    "depends_on": [0],               // 依赖的 call seq（从 1 计）
    "auth": "cookie",                // cookie|bearer|none（从 headers 键名推断）
    "notes": "字段语义/坑点"
  }],
  "noise_collapsed": ["sa-static/*", "ClickHouseInsertData", "announce 轮询"]
}
```

**json 与 md 的一致性**：md 的每节 = json 的一个 call，purpose/seq 一一对应；json 是 md 的结构化镜像，单边更新视为错误。

## 质量自检（输出前跑一遍）

- [ ] 每个 endpoint 的 path 在 session.jsonl 里 `grep` 得到完整原串
- [ ] depends_on 引用的 seq 存在且在前（无前向依赖）
- [ ] 脱敏字段（`***`）未被任何"推测还原"污染
- [ ] md/json 数量一致、purpose 一致
- [ ] curl 建议里的占位（$COOKIE/$IID 类）都有定义说明
