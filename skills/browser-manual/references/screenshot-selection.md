# 截图时机判定细则（SKILL.md 截图选用规则的可执行版）

SKILL.md 的表格是速查。本细则给出**从事件流判定每类动作**的精确步骤，按此执行无需猜测。

## 判定输入

对每个 action（按 t_mono 排序）取三类上下文：

1. **后随 nav**：该 action 之后 3s 内同 `target_id` 的 nav 事件（排除 `recovered:true`）
2. **后随业务请求**：该 action 之后 1.5s 内的 `/api/`、`/gateway/` 请求
3. **同表单前驱**：前一个 action 是否同 `element.descriptor.dom_path` 前缀（同一表单容器）

## 判定流程（伪码）

```
for action in actions:
    nav_after     = 后随 nav 非空
    api_after     = 后随业务请求非空
    same_form     = 同表单前驱

    # ---- 状态呈现类：页面没变（能看到原页面），但 before 看不出动作结果 ----
    # 勾选/单选/下拉选中/tab 切换：before 里选项还没选中；输入：before 里框是空的。
    # after 图里原页面仍在、且选中态/已输入内容可见——选 after 才能回答"选对了吗"。
    if action.type == "input":
        选 after                       # 已输入内容可见（值同时写在说明文字里）
    elif action.type == "click" and 元素是 单选/复选/下拉选项 (input[type=radio|checkbox] 或 其容器/li/option):
        选 after                       # 选中态可见
    # ---- 页面改变类：before 才有动作现场（after 页面已变，红框会指空） ----
    elif action.type == "submit" or (action.type=="click" and 元素文本含 提交/保存/确定/登录/删除):
        选 after                       # 展示提交/操作结果页
        若 after.status != ok/stable/timeout: 退回 before + 文字说明结果
    elif action.type == "click" and nav_after:
        选 before                      # 跳转类：before=动作瞬间现场，红框在被点元素上
    elif action.type == "click" and api_after and not nav_after:
        选 before + after 连排          # 局部刷新：点哪/变成什么
    else:
        选 before                      # 默认
```

**判定优先级说明**：状态呈现类（input/勾选）判定在**前**——因为这类动作"无跳转无弹窗、原页面可见"的形态，正是最容易被误配 before 的；页面改变类在后兜底。拿不准某动作属于哪类时，问自己：**after 图里还能看到红框标的位置吗？** 能看到且结果可见 → after；看不到（页面已换）→ before。

## status 过滤与零尺寸处理

- `screenshot.status ∈ {raced, failed}` → **不引用**，该步骤改纯文字（元素描述 + 值）
- `action.element.rect.w == 0 or h == 0` → 截图无红框：引用时在说明里写明“图中无框，元素：<tag>#<id> <text>”
- 找不到截图事件（动作后停止打断）→ 纯文字小节，标注“（本步无截图）”

## 引用格式（逐字一致）

```markdown
![<与### 小节标题相同的动词短语>](screenshots/<seq>-<phase>.png)
```

连排两张时（仅"局部刷新"类）：

```markdown
![<短语>-点击处](screenshots/<seq>-before.png)
![<短语>-效果](screenshots/<seq>-after.png)
```

## 已知边界（如实标注，不装作没有）

- **输入聚合**：同一输入框 1.2s 内的多次击键合成一个 action——before 图是聚合窗末的现场（值已完整）
- **monaco/自绘编辑器**：rect 可能滚出视口（y<0），标注在图外——此类步骤以文字为主
- **launchpad 面板内的输入**（历史缺陷已修，但旧 session 可能存在）：rect 可能落在宿主元素上——引用时以截图实际内容为准，必要时用 nav/文本交叉说明
