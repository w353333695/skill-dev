# hub.md —— 平台商店（成品资产库：查重 + 回流）

> hub 是 `platforms/<deployment>/hub/` 下的**开发态成品资产库**：开发任务开始前先查重（是否已有
> 可复用成品），成品交付时自动回流。机制通用零耦合——类目语义由各 deployment 的 INDEX.yaml
> 头注释声明，本文件不硬编码任何类目。lint 第 11 段兜底索引一致性。

## 定位（与部署根的关系）

- hub 在 **skill 自带 platforms** 里（开发态资产，随 skill 分发），不是运行时部署根
  （`$PWD/.api-orchestrator/`）——orchestration 模式对 platforms 的只读纪律不变。
- hub 是 **deployment 级可选资产**：任何 deployment 都可有 hub（没有则查重/回流整段跳过，
  lint 不报错）。
- **权限口径**：规划挡「开发交付场景」（产物是可导入/可部署成品）视为开发态延伸——回流是交付
  动作的一部分，不算违反只读纪律。纯查询编排仍禁止写 hub。

## 结构（hub/ = 类目子目录 + INDEX.yaml）

- 一级子目录 = 商品类目（如脚本、工具、模板、交付包……具体语义由本 deployment 的 INDEX.yaml
  头注释声明，类目集合是 deployment 级约定）。
- `INDEX.yaml` = 唯一商品索引（查重载体 + 变更日志），每件商品一条，字段与顺序：

```yaml
# 类目语义: packs=可导入交付包 scripts=可交付脚本 tools=注册工具 ...
#（具体类目集合由本 deployment 自行声明，机制层不硬编码）
items:
  - id: net-device-backup-pack         # 唯一 id，kebab-case
    name: 网络设备配置备份交付包
    category: packs                    # 必须是 hub/ 实际子目录（lint ERR）
    files: [网络设备配置备份_v1.0.14.zip, 网络设备备份_操作参考.md]
    version: "1.0.14"                  # 包内读不出则留空
    history:                           # 版本演进（回流 version 变化时必须追加一行）
      - {ver: "1.0.13", date: 2026-08-29, change: 初版入库}
      - {ver: "1.0.14", date: 2026-09-10, change: 增加国产型号适配；修复定时窗口缺陷}
    based_on: host-backup-pack         # 可选：近似命中改造出新 id 时的衍生谱系
    scenario: 网络设备(多厂商) 配置定时备份与导出   # ★语义查重核心
    notes: 导入后需按配套文档配置定时任务
    added: 2026-08-29
```

- **版本号一律写带引号的字符串**：`version` 与 `history[].ver` 写 `"1.0.13"`，不裸写——裸写会被
  YAML 解析成 float（`1.10` → `1.1`），lint 校验「history 末条与 version 一致」时假报 ERR。
- `scenario` 是语义查重的关键载体（对象 + 场景关键词）；`history` 是二进制包唯一可读的变更日志
  （zip/tar.gz/xlsx 的 git diff 是乱码，看不出改了什么）；`based_on` 记录衍生谱系。
- **命名规范**：`<名称>_v<版本>.<ext>`；新版本回流 → 删旧版文件（git rm），目录只留最新版，
  历史靠 git + INDEX.history 双轨追溯。
- 收录门槛：**仅成品交付物**（可导入/可部署）。中间产物/调试脚本不回流（落 tmp/ 或项目目录）。

## 查重流程（开发前必查，规划挡步 1 后）

触发：需求涉及开发/交付新商品（脚本/工具/交付包等，非纯查询编排）。

1. `Read $PLATFORMS_ROOT/<dep>/hub/INDEX.yaml`（单文件一次读全）。
2. 拿需求的对象/场景关键词对 `scenario` + `name` 语义匹配。
3. 三分支：
   - **命中** → 报告「hub 已有 <name> v<version>（<category>/<file>）」，给复用/改造/重做建议，
     用户选向后再继续；
   - **近似命中**（同类设备不同型号/同域不同对象）→ 报告差异，建议作改造基底（版本 +1 或
     改出独立 id + based_on），用户决定；
   - **未命中** → 正常开发，交付时回流。
4. 结论写 `tmp/<task>/plan.md`（「hub 查重：未命中 / 复用 <id>」），留审计痕。

查重不改变挡位判定（只是规划挡内的前置步骤）；直通/确认挡不触发。

## 回流流程（交付时自动）

触发：规划挡交付，产物含可导入/可部署成品。

1. **归位**：成品落 `hub/<category>/`，命名 `<名称>_v<版本>.<ext>`；旧版文件同目录删除（git rm）。
2. **登记**（INDEX.yaml items 三种分叉）：
   - 新商品 → 追加一条，history 首行 `{ver, date, change: 初版入库}`；
   - 既有商品升级（不满足需求 → 加功能/修 bug 回流）→ version +1、更新 files、history 追加
     一行（change = 用户需求原话或修复要点一句话）、added 不动；
   - 近似命中改出新商品 → 新条目 + `based_on` 指向基底 id。
3. **commit**：回流后立即 commit（防工作区自动提交机制打包垃圾 message）。
4. 配套文档（模板 xlsx/参考 md 等）跟主件同 files 登记，不单独成商品。

## lint 兜底（第 11 段，hub 存在才跑；不存在整段跳过）

8 条规则速查：INDEX 缺失(WARN) / category 合法(ERR) / files 双向一致(ERR) / id 唯一(ERR) /
scenario 非空(WARN) / 版本单份(ERR) / history 末条与 version 一致(ERR) / based_on 闭合(ERR)。

完整校验逻辑见 `scripts/lint-platforms.py` 第 11 段；跑法同 onboarding 步 7：
`scripts/lint-platforms.py <deployment>`，0 ERR 才算索引合格。

## 刻意不做（YAGNI，防止机制膨胀）

- **不做 hub 管理命令**（`hub search/add` 之类脚本）——查重是语义匹配，LLM 读 INDEX 比关键词
  grep 准；加命令引擎与「调度靠 LLM、无代码引擎」的既有范式相悖。
- **不做独立 changelog 文件**——变更历史内联在 INDEX 的 `history`（二进制包 git diff 不可读，
  INDEX 内联是唯一可读变更日志；git 历史仍可追溯旧文件字节）。
- **不建 per-类目 README**——单一 INDEX 已够，分类目读 N 个文件费 token。
- **不设 type/source 等字段**——category 已承载类型，YAGNI。

## 与 onboarding 锁回纪律的差异

hub 是高频回流域：写 hub 前 `chmod -R u+w platforms/<dep>/hub/`，改完**不锁回**（区别于
onboarding 对 platforms 整体的改完锁回）。
