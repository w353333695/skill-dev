# 增量设计：多 tab 跟随录制（spec §2.6）

- 日期：2026-08-30
- 背景：真实场景（easyops 测试套件创建/删除 21 步）第 7 步"跳转新 tab"，当前单 target 实现丢失其后全部流程。MVP 验收需要多 tab 跟随。
- 原则：通用能力，不过拟合 e2e；遇到 e2e 特有问题做兼容但不降低其他场景覆盖率。

## 设计

### 连接拓扑

```
browser-level ws（/json/version 的 webSocketDebuggerUrl）
  ├── Target.setAutoAttach(autoAttach=True, waitForDebuggerOnStart=True, flatten=True)
  ├── 收 Target.attachedToTarget（每个新 page target，含启动 tab）
  │     → 每个 sessionId 建一条"虚拟子连接"（同一 ws，消息带 sessionId 路由）
  │     → 子连接各自：Network/Page/Runtime.enable + addBinding + 注入
  └── 收 Target.targetDestroyed → 子连接收尾（不再收事件）
```

**flatten session 复用同一条 browser ws**：CDP 扁平会话协议下，命令与事件都带 `sessionId` 字段在同一条 ws 上路由。`CDPClient` 扩展为支持 session 路由，**不为每个 tab 开新 ws**（省连接管理，且 browser ws 天然见到所有 target 生命周期事件）。

### CDPClient 改造（向后兼容）

- `send(method, params, session_id=None)`——非 None 时消息附 `sessionId` 字段
- 事件分发：`_dispatch` 收到带 `sessionId` 的事件时，先派给该 session 的订阅者（`on(event, cb, session_id=...)`），再派给全局订阅者（无 session 语义的事件如 `Target.*`）
- `CDPClient.connect_browser(port)`——连 `/json/version` 的 browser ws（新类方法）

### recorder 改造

- `Page.navigate` 启动 URL 后，browser ws `Target.setAutoAttach`；首个 `attachedToTarget` 即启动 tab 的 session
- 每 session 注册现有全部事件处理（on_req/on_resp/on_nav/on_binding），事件 emit 时 payload 附 `target_id`（短 id，如 "t0"/"t1"，从 targetInfo 取 url 作 `target_url` 便于 LLM 分辨 tab）
- **action 队列多路合流**：action_q 的 payload 带 target_id；action_loop 双截图用该 target 的 session 发 `Page.captureScreenshot`
- **StableState 全局共享**（跨 tab 合计 in-flight + 最近突变）——"页面稳定"语义升级为"所有已打开 tab 都稳定"，符合"操作后等页面稳定"的直觉
- `Target.targetCreated`（非 page 类型或未 attach）→ `note` 事件（启用 spec §3.1 的 note kind）
- browser ws 关闭 = 浏览器关闭（原 `_wait_browser_closed` 改盯 browser client）

### 脱敏/终止不变

- 热键 Ctrl+Shift+F9：任一 tab 触发即全局停止（binding 上报带 target_id，control_stop 不分 tab）
- 所有 kind 的 emit 路径照旧过 writer 脱敏

## 验收（真实场景）

1. 现有 20 测试全绿（单 tab 行为零回归）
2. 新增 e2e：录 `target=_blank` 链接开新 tab 并在新 tab 操作，断言新 tab 的 action/nav/request 均带新 target_id
3. easyops 21 步真实跑通 → guide.md 交付审核
