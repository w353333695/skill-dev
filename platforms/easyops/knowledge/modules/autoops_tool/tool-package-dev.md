---
name: tool-package-dev
kind: module
module: autoops_tool
tags:
- AutoOps
- 工具包
- 工具开发
- tool_service
- 脚本工具
completeness: partial
gaps:
- 工具在平台沙箱/目标机端到端执行未验证（包构造+预检+导入+回查已真机验证，2026-07-29；脚本在目标机实际跑通未测）
- 预装第三方 Python 库版本为平台开发教程摘录（如 psutil 4.3.0 / requests 2.8.1 / PyMySQL 0.7.9），实际运行环境版本未核对
- containerSandbox.image 是否生效取决于目标环境平台配置 containerSandboxConfig.enableCustom，本环境实际配置未核对
- sandbox.service_name / sandbox.exec_user / sandbox.tools / sandbox.ips 等服务端配置项具体取值未核对
- 附录 C 内置变量 EASYOPS_* 在本环境未实际注入验证（取值示例为教程摘录）。⚠️ 2026-07-30 实战反证：`EASYOPS_DEPLOY_REPO_HOST` 在工具执行环境未按预期注入（脚本内引用取不到值），用户手动改为显式 HOST 常量——**内置变量清单不可盲信，新环境首次使用先跑「变量探针版本」**（见 §5 Step 3 注）
- cmdbInstance 参数（type=cmdbInstance 单选）注入脚本的值形态未实测确认：可能是 instanceId / 32位md5(packageId) / 整条实例 dict，三种形态因平台版本而异（2026-07-30 实战按三形态兼容写法规避，见 §2.2.1 注）
scope:
- 构造/手写一个 AutoOps 工具包（.tool.tar.gz）并导入平台
- 理解工具包各文件（._easyPackageConfig.dat / config / script / libs）字段含义与取值规则
- 排查工具包导入失败 / 冲突（改名 newName / 换版本 newVersionName）
- 编写工具脚本时使用内置变量 / 内置函数（PutStr/PutRow）/ 预装库
related:
- registry/autoops_tool（tool_import/tool_export/tool_import_check 等运行态接口）
- concepts/instance-id（toolId/vId 为 32 位 md5）
- concepts/api-calling（tool_service 服务端口 8181）
last_verified: '2026-07-30'
note: 'EasyOps AutoOps 工具包（.tool.tar.gz）开发说明：包结构（._easyPackageConfig.dat/config/script/libs）、
  config 字段白名单与取值、inputs 输入参数结构（枚举型 type:enum+primitive:true，已实测）、导入端处理流程与冲突校验、
  相关 API、手工打造工具包步骤、工具输出（outputDefs/tableDefs + PutStr/PutRow）、沙箱执行（sandboxRun/containerSandbox，
  默认不沙箱——仅 ITSM 前后置/表单脚本必须沙箱）、脚本运行环境（内置变量/函数/预装库）、脚本内调平台 API 完整内联 api-samples.py 的 EasyOpsClient
  内网直连。来源：tool_service 服务源码（import_export 模块）+ tool.import_export.* API + 工具平台开发教程整理；
  包构造/预检/导入/回查已真机验证（2026-07-29~30，工具「文件分发包下载」v1.0.0~v1.0.3 多轮迭代），脚本目标机端到端执行未测。
  切面定位：本知识描述工具包「构造/开发态」（怎么搓一个合法包），registry/autoops_tool 描述「运行态」（导入/导出/执行/列表接口怎么调）--
  同名对象不同切面，互补参照，非重复。开发工具包时先读本知识定结构/字段，再用 registry 卡片调导入接口。'
---
# EasyOps  AutoOps工具包（Tool Package）开发说明

> 面向 LLM 的工具包开发指南。基于 `tool_service` 服务源码（`import_export` 模块）与 `tool.import_export.*` API 整理。
> 目标：掌握工具包（`.tool.tar.gz`）的结构、各文件字段含义与取值规则，并能根据用户需求生成一个合法的工具包。

---

## 1. 工具包整体结构

工具包是一个 **`tar.gz` 压缩包**（支持后缀：`.tar.gz` / `.tgz` / `.tar` / `.war` / `.zip`，导入端通过正则 `\.tar\.gz$|\.tgz$|\.tar$|\.war$|\.zip$` 校验）。

解压后目录结构如下（顶层目录名任意，通常与工具名相同）：

```
<工具名>/
├── ._easyPackageConfig.dat     # 【必需】包元数据文件（JSON）
├── config                      # 【必需】工具配置（JSON，无扩展名）
├── script                      # 【必需】脚本内容（纯文本，无扩展名）
└── libs/                       # 【可选】引用的工具 lib 库
    ├── <lib名>.tar.gz          # lib 制品包（内嵌 repo.tar.gz + <lib名>.json）
    └── ...                     # 每个 lib 一个 .tar.gz
```

**命名示例**：官方导出的包文件名为 `<工具名>.<时间戳>.<兼容策略>.tool.tar.gz`，例如 `pacino_tools.202209131715510.latest.tool.tar.gz`；批量导出为 `tool_batch_export.<时间戳>.tool.tar.gz`。导入时不校验包文件名，只校验压缩格式。

---

## 2. 文件逐一说明

### 2.1 `._easyPackageConfig.dat` —— 包元数据（JSON）

顶层两个 key：`package` 与 `version`。导出时的真实生成逻辑（`convertDatFileContent`）：

```json
{
  "package": {
    "packageId":   "<toolId, 32位md5>",
    "type":        "3",
    "cId":         "1",
    "source":      "none",
    "repoId":      "1",
    "authUsers":   null,
    "installPath": null,
    "platform":    "linux",
    "conf":        null,
    "name":        "<工具名>",
    "category":    "<分类，如 默认>",
    "icon":        "<图标，如 wrench>",
    "style":       "<样式，如 default>",
    "memo":        "<备注>",
    "disable":     false
  },
  "version": {
    "versionId":  "<随机GUID>",
    "name":       "<unix时间戳字符串>",
    "packageId":  "<toolId>",
    "memo":       "none",
    "sign":       "",
    "source":     "",
    "sourceType": "",
    "conf":       ""
  }
}
```

**导入端实际只读取 `package` 部分**，且只取以下字段的映射（`datConvertMap`）：

| dat 中字段（package 下） | 映射到工具字段 | 说明                                                         |
| ------------------------ | -------------- | ------------------------------------------------------------ |
| `name`                 | `name`       | 工具名称（**必填**，为空则判定为非法工具包）           |
| `packageId`            | `toolId`     | 工具 ID（**必填**，32 位 md5；为空则判定为非法工具包） |
| `memo`                 | `memo`       | 工具备注                                                     |
| `icon`                 | `icon`       | 图标名，如`wrench`                                         |
| `category`             | `category`   | 工具分类，如`默认`                                         |
| `style`                | `style`      | 样式，如`default`                                          |
| `disable`              | `disable`    | 是否停用（导出时强制置`false`）                            |

> ⚠️ 注意：`.dat` 文件是历史兼容格式（源自制品库包结构）。**当 `config` 和 `script` 同时存在时**（标准情况），`.dat` 仅提供上述 7 个基础字段，其余全部来自 `config`；只有当 `config`/`script` 缺失时，才会把 `.dat` 整体当作工具定义解析（旧包兼容路径）。
>
> `version` 部分导入时**完全被忽略**，生成时可按上方模板填占位值即可。

### 2.2 `config` —— 工具配置（JSON，无扩展名）

工具定义的主体。导入时逐字段读取，**只有下表列出的字段会被识别**（即源码中带 `export:"config"` 标签的字段），多余字段会被忽略。

#### 基础信息（来自 ToolConfig）

| 字段                               | 类型     | 必填   | 说明 / 取值                                                                           |
| ---------------------------------- | -------- | ------ | ------------------------------------------------------------------------------------- |
| `listVisible`                    | bool     | 建议填 | 是否在工具列表可见。**不传默认为 `true`**（导入端补默认值）                   |
| `readOnly`                       | bool     | 否     | 是否只读                                                                              |
| `systemHide`                     | bool     | 否     | 系统级隐藏                                                                            |
| `templateType`                   | string   | 否     | 模板类型：`MYSQL` / `ORACLE` / `HTTP` / `JAVA`，普通脚本工具填空字符串 `""` |
| `tags`                           | string[] | 否     | 标签列表                                                                              |
| `readAuthorizers`                | string[] | 否     | 可读授权用户/用户组（用户组以`:` 开头）                                             |
| `updateAuthorizers`              | string[] | 否     | 可更新授权                                                                            |
| `deleteAuthorizers`              | string[] | 否     | 可删除授权                                                                            |
| `executeAuthorizers`             | string[] | 否     | 可执行授权                                                                            |
| `rootExecuteAuthorizers`         | string[] | 否     | 可 root 执行授权                                                                      |
| `rootModifyAuthorizers`          | string[] | 否     | 可 root 修改授权                                                                      |
| `readExecutionResultAuthorizers` | string[] | 否     | 可读执行结果授权                                                                      |
| `execTimeWindowConfig`           | object[] | 否     | 执行时间窗配置（ExecTimeWindowConfig 结构）                                           |
| `execPreAuth`                    | object   | 否     | 执行前审批配置（ExecPreAuth 结构）                                                    |

#### 版本信息（来自 ToolVersion）

| 字段                         | 类型     | 必填         | 说明 / 取值                                                                                                                                                |
| ---------------------------- | -------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vId`                      | string   | 建议填       | 版本 ID（md5）。**导入时若与已有版本冲突需改名/置空**；新建工具可填任意新 md5                                                                        |
| `vName`                    | string   | **是** | 版本号，如`1.0.0`                                                                                                                                        |
| `vDesc`                    | string   | 否           | 版本描述                                                                                                                                                   |
| `level`                    | int      | 否           | 等级，默认 0                                                                                                                                               |
| `type`                     | string   | **是** | 脚本类型，取值：`shell` / `python` / `perl` / `powershell` / `batch` / `Ansible-PlayBook` / `autoit` / `downloadLibs`                      |
| `inputs`                   | object[] | 否           | 输入参数定义，详见 §2.2.1                                                                                                                                 |
| `timeout`                  | int      | 否           | 超时时间（秒），常用 86400                                                                                                                                 |
| `forceShutdown`            | bool     | 否           | 超时是否强制终止                                                                                                                                           |
| `defaultExecUser`          | string   | 否           | Linux 默认执行用户。**不传默认 `root`**                                                                                                            |
| `windowsDefaultExecUser`   | string   | 否           | Windows 默认执行用户。导出端补默认：`windowsSession=false` → `System`；`true` → `Administrator`；`type=python` 且未设置时导入端默认 `System` |
| `execUser`                 | string   | 否           | 指定执行用户（覆盖默认）                                                                                                                                   |
| `defaultAgents`            | string[] | 否           | 默认执行目标                                                                                                                                               |
| `lockAgents`               | string   | 否           | 锁定执行目标策略：`constant` / `search` / `all`                                                                                                      |
| `sandboxRun`               | bool     | 否           | 是否沙箱运行                                                                                                                                               |
| `containerSandbox`         | object   | 否           | 容器沙箱：`{"enable": bool, "image": string}`                                                                                                            |
| `whiteList`                | string[] | 否           | 白名单                                                                                                                                                     |
| `blackList`                | string[] | 否           | 黑名单                                                                                                                                                     |
| `windowsSession`           | bool     | 否           | 是否使用 Windows 会话                                                                                                                                      |
| `windowsOnlyActiveSession` | bool     | 否           | 仅活动会话执行                                                                                                                                             |
| `outputDefs`               | object[] | 否           | 输出变量定义：`[{"id": "...", "name": "..."}]`                                                                                                           |
| `tableDefs`                | object[] | 否           | 输出表格定义：`[{"id","name","dimensions":[{"id","name"}],"columns":[{"id","name"}]}]`                                                                   |
| `batchStrategy`            | object   | 否           | 分批策略：`{"batchNum":int,"batchInterval":int,"failedStop":bool,"enabled":bool}`                                                                        |
| `functionType`             | string   | 否           | 功能类型：`MYSQL`/`ORACLE`/`HTTP`/`JAVA`/`Ansible-PlayBook`，普通脚本为 `""`                                                                   |
| `envLinux`                 | object[] | 否           | Linux 环境变量（EnvEntry 结构）                                                                                                                            |
| `envWindows`               | object[] | 否           | Windows 环境变量                                                                                                                                           |
| `toolLibs`                 | object[] | 否           | 引用的 lib 库列表，元素为 ToolLib 结构（见 §2.3）。**若填写，需同时在 `libs/` 目录提供对应 `.tar.gz`**                                          |

**不会被导入的字段**（源码中 `export:"-"`，写在 config 里也会被忽略）：`toolId`（由 .dat 提供）、`content`（由 script 文件提供）、`instanceId`、`ctime`/`mtime`/`creator`、`delete_me`、`sourceFrom`、`envType`、`checkInfo`、`notice`、`subscribers`、`approvers`、`versionMark`、`relatedToolId` 等。这些由系统在导入时自动生成。

#### 2.2.1 `inputs[]` 输入参数结构（ToolInput）

```json
{
  "name": "@agents",              // 参数名；@agents 为内置"执行目标"参数
  "type": "cmdbInstances",        // 参数类型，见下表
  "label": "执行目标",             // 展示名
  "memo": "",                     // 说明
  "required": true,               // 是否必填
  "multiple": true,               // 是否多值
  "default": null,                // 默认值
  "enum": [],                     // 枚举候选（type 为枚举类时使用）
  "cascade": false,               // 是否级联
  "primitive": false,             // 是否原始类型
  "path": [],                     // [{"id":"...","type":"..."}] 路径
  "source": "",                   // 来源
  "selector": "",                 // 选择器
  "value": null,                  // 当前值
  "cmdbObjectId": "HOST",         // CMDB 模型 ID（cmdb 类参数）
  "cmdbAttrId": "ip",             // CMDB 属性 ID
  "cmdbAttrType": "",             // CMDB 属性类型
  "cmdbQuery": null,              // CMDB 查询条件（object）
  "cmdbSelector": "",             // CMDB 实例选择器
  "cmdbOptionSetting": {          // 实例下拉展示设置（可选）
    "displayFields": [], "sortFields": [], "sort": "asc"
  },
  "secretName": "",               // 凭据名（secretKey 类参数）
  "secretKey": "",                // 凭据键
  "regex": "",                    // 校验正则
  "hidden": false                 // 是否隐藏
}
```

`type` 常用取值：

| 值                             | 含义                                                                                                                                                                                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cmdbInstance`               | CMDB 单实例选择                                                                                                                                                                                                                        |
| `cmdbInstances`              | CMDB 多实例选择（`@agents` 执行目标即用此类型）                                                                                                                                                                                      |
| `int` / `float`            | 数字                                                                                                                                                                                                                                   |
| `string`（默认）             | 字符串                                                                                                                                                                                                                                 |
| `enum`                       | 枚举下拉。**结构**：`type:"enum"` + `enum:["选项1","选项2",...]` + `primitive:true`；默认值放 `default`（须为 enum 成员之一）。已实测（v1.0.1 枚举样本）——注意**不是** `string+enum`（那样 enum 不渲染成下拉） |
| `cmdbInstance`               | CMDB 单实例选择（注入值形态见下方 ⚠️ 注）                                                                                                                                                                                            |
| `json`                       | JSON（⚠️ 工具库前端参数面板**不支持 json 类型渲染会报错**，需传 JSON 字符串时用 `string` 替代，脚本内自行 `json.loads`）                                                                                                   |
| `encryptedString`            | 加密字符串                                                                                                                                                                                                                             |
| `secretKey` / `secretName` | 凭据引用                                                                                                                                                                                                                               |
| `autofill`                   | 自动填充                                                                                                                                                                                                                               |

**最小可用 inputs**（几乎所有工具都需要执行目标）：

```json
[{
  "name": "@agents", "type": "cmdbInstances", "label": "执行目标",
  "cmdbObjectId": "HOST", "cmdbAttrId": "ip",
  "multiple": true, "required": true,
  "enum": [], "path": [], "cascade": false, "primitive": false
}]
```

> ⚠️ **cmdbInstance 参数实测要点（2026-07-30，「文件分发包下载」v1.0.3 实战）**：
>
> - **已验证可用结构**（cmdbInstance 单选 + CMDB 查询过滤 + 下拉展示字段，前端渲染与导入均正常）：
>
> ```json
> {
>   "name": "package_id", "type": "cmdbInstance", "label": "文件包名",
>   "cmdbObjectId": "_ARTIFACT", "cmdbAttrId": "name", "cmdbAttrType": "str",
>   "multiple": false, "required": true, "primitive": true, "default": [],
>   "enum": [], "path": [], "cascade": false,
>   "selector": "cmdb.range.instance.query",
>   "cmdbQuery": {"defaultInstanceId": "",
>     "query": "{\"$and\":[{\"$or\":[{\"type\":{\"$eq\":\"filepkg\"}}]}]}"},
>   "cmdbOptionSetting": {"displayFields": ["artifactName"], "sortFields": [], "sort": "desc"},
>   "cmdbSelector": "simple-select"
> }
> ```
>
> 要点：`selector:"cmdb.range.instance.query"` + `cmdbQuery.query`（JSON 字符串的 CMDB 查询）做候选过滤；`cmdbOptionSetting.displayFields` 控制下拉展示字段；`primitive:true` + `default:[]`。
>
> - **注入值形态未实测**（gap）：单选注入脚本的值可能是 instanceId / `cmdbAttrId` 对应字段值 / 整条实例 dict，因平台版本而异。**稳妥写法：脚本内做三形态兼容解析**（dict 取字段、32 位 md5 直接用、否则按 instanceId 查 CMDB 取目标字段），参考样本 tmp/file_pkg_download/script 的 `_to_package_id()`。
> - **实例主键与业务 ID 关系（_ARTIFACT 特例，已实测 2026-07-30）**：`_ARTIFACT` 实例的 `name` 字段 == 制品库 packageId（`/package/package/{name}` 直查 200）；`cmdbAttrId:"name"` 选择后拿到的即 packageId。其他模型的对应关系需各自实测，不要类推。

### 2.3 `libs/` —— 工具 lib 库目录（可选）

当 `config` 中声明了 `toolLibs` 且希望随包分发 lib 时，每个 lib 以 **`<lib名>.tar.gz`** 形式放在 `libs/` 下。单个 lib 压缩包内部结构：

```
<lib名>.tar.gz
├── <lib名>_repo.tar.gz   # 实际的制品文件包（上传到制品库的原始压缩包）
└── <lib名>.json          # lib 元数据（ToolLib 序列化 JSON）
```

`<lib名>.json`（ToolLib 结构）关键字段：

| 字段            | 说明                                                                          |
| --------------- | ----------------------------------------------------------------------------- |
| `instanceId`  | lib 实例 ID（导入冲突校验用）                                                 |
| `name`        | lib 名称（**导入端以它定位 `<lib名>.json`，必须与压缩包文件名一致**） |
| `packageId`   | 制品包 ID                                                                     |
| `versionId`   | 制品版本 ID                                                                   |
| `description` | 描述                                                                          |
| `scriptType`  | 脚本类型（如`python`）                                                      |

导入行为：lib 名称冲突时默认不覆盖；调用方可在导入接口的 `importLibs` 参数中传入 `{"libName": "...", "sureImportLib": true}` 确认覆盖导入。导入成功后 lib 实例会与新工具版本绑定（`AddToolVersionLibs`）。

---

## 3. 导入端的处理流程与校验规则（决定了你该怎么构造包）

### 3.1 导入主流程（`importTool`）

1. **解压校验**：文件名须匹配 `\.tar\.gz$|\.tgz$|\.tar$|\.war$|\.zip$`；解压后必须存在 `._easyPackageConfig.dat`，否则报错"文件不存在"。
2. **解析**：
   - `config` + `script` 同时存在（标准路径）：script → `content`；.dat 提供 name/toolId/memo/icon/category/style/disable；config 提供其余字段（仅白名单字段）。
   - 否则走旧包兼容：整个 .dat 当作工具定义 JSON 解析。
3. **默认值补齐**（`SetPkgDefault`）：
   - `defaultExecUser` 空 → `root`
   - `type=python` 且未设 `windowsSession` → `false`，`windowsDefaultExecUser` → `System`
   - config 未传 `listVisible` → `true`
4. **合法性**：`name == "" || toolId == ""` → 判定非法工具包，导入失败。
5. **改名/改版本**（导入参数）：传 `newName` → 使用新名并**清空 toolId**（即作为新工具创建）；传 `newVersionName` → 使用新版本名并**清空 vId**。
6. **冲突校验**（`conflictValidator`），冲突则返回 `conflictList`，可能的 key：
   - `toolName`：存在同名（非同 toolId）工具 → 需要改名导入
   - `toolVersionId`：同 toolId 下该 vId 已存在 → 需要换版本
   - `toolVersionName`：同 toolId 下该 vName 已存在 → 需要换版本名
   - 仅 `toolId` 相同不算冲突（视为给已有工具新增版本）
7. **还原归档**：`revertDelete=true` 且工具曾被删除（`delete_me=true`）→ 取消删除标记并更新。
8. **创建/更新**：toolId 在系统中不存在 → `CreateTool`（新建）；存在 → `UpdateToolWithExists`（新增/更新版本）。`sourceFrom` 强制置为 `import`；`creator`/`vCreator` 置为当前用户。
9. **系统导入**：`systemImport=true` → `envType=production`，`checkType=unuseglobalcheck`，跳过版本审批。
10. **libs 导入**：读取包内 `libs/*.tar.gz`，逐个调用 lib 导入，最后与工具版本绑定。

### 3.2 检查结果枚举（批量导入预检接口返回的 `result`）

| 值                               | 含义                  | 处置                     |
| -------------------------------- | --------------------- | ------------------------ |
| `success`                      | 无冲突，可直接导入    | 直接导入                 |
| `nameConflict`                 | 工具名称冲突          | 提供`newName` 改名导入 |
| `versionExist`                 | 版本已存在            | 无需导入                 |
| `verNameConflict`              | 版本名冲突            | 提供`newVersionName`   |
| `nameDifferent`                | toolId 相同但名称不同 | 导入后将以包内名称为准   |
| `nameDifferentVerNameConflict` | 名称不同 + 版本名冲突 | 组合处理                 |
| `nameConflictVerNameConflict`  | 名称冲突 + 版本名冲突 | 组合处理                 |

---

## 4. 相关 API 一览

| 接口                                                             | 方法 & 路径                                         | 用途                                                                                                                        |
| ---------------------------------------------------------------- | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `tool.import_export.export_tool.ExportTool`                    | GET`/tools/:toolId/export`                        | 导出单个工具。参数：`versionId`、`compatibility`（`latest` 或如 `2.32`）、`exportLibs`（是否附带 libs）           |
| `tool.import_export.export_tool_check.ExportToolCheck`         | POST`/tools/:toolId/export/check`                 | 导出前检查 lib 可导出性（结果：`success` / `libNotFound`）                                                              |
| `tool.import_export.import_tool.ImportTool`                    | POST`/tools/import` (multipart)                   | 导入单个工具包。参数：`file`（必）、`newName`、`newVersionName`、`revertDelete`、`systemImport`、`importLibs[]` |
| `tool.import_export.import_tool_check.ImportToolCheck`         | POST`/api/tool_service/v1/batch/import/check`     | 批量导入前检查（按 toolId/versionId/name 元数据检查）                                                                       |
| `tool.import_export.import_tool_pkg_check.ImportToolPkgCheck`  | POST`/api/tool_service/v1/batch/import/pkg/check` | 批量上传压缩包前检查（返回每个工具的冲突结果 + 与现有版本的 diff）                                                          |
| `tool.import_export.export_tool_batch` / `import_tool_batch` | 批量导出/导入                                       | 批量包内每个工具一个`<toolId>_<vId>/` 子目录，结构同单工具包                                                              |
| `tool.lib.export.Export`                                       | GET`/api/tools/v1/libs/export/:instanceId`        | 单独导出 lib 库                                                                                                             |
| `tool.lib.import.ImportLib`                                    | POST`/api/tools/v1/libs/import`                   | 单独导入 lib 库。参数：`name`（必）、`file`（必）、`newName`                                                          |

请求头统一需要：`org`（机构 ID）、`user`（用户名）。

### 4.1 内网直接创建工具（免打包，2026-07-28 实测）

> 若只是把一段脚本注册成工具（如给流程节点 `scriptSettings.scriptIdList` 提供 toolId），**无需手工打包**——`tool.basic.CreateTool` 内网直连（tool_service 8181）直接创建：

```
POST http://<host>:8181/tools
Header: user, org, Content-Type: application/json
Body:
{
  "name": "<工具名>",
  "type": "python",              # ⚠️ 服务端必填字段是 type（脚本语言），非卡片的 toolType
  "category": "<分类>",
  "content": "<脚本内容字符串>",
  "sandboxRun": true,            # 节点前后置脚本 / 表单事件脚本必须沙箱执行（py_script_runner）
  "summary": "<一句话说明>",
  "desc": "<描述>",
  "public": false
}
```

返回 `{"data": {"toolId": "<32位hex>", "vId": "...", "disable": false}}`。

**字段要点**：

- `type`（非 `toolType`）：脚本语言，如 `python`。卡片 `tool_create` 的 `toolType` 字段服务端不认（400 "必填key type 不存在"）。
- `content`：脚本全文（字符串），等价于工具包 `script/<name>.py` 的内容。
- `sandboxRun: true`：流程/表单脚本必须沙箱执行（form-advanced §3.5 / process_development §4.4）。不设则报"工具未设置沙箱执行"。
- `inputs`/`outputs`：节点脚本入参由流程引擎注入（orderInfo/action/scriptType）、输出用标记协议（print），**不需声明 inputs/outputs**（声明格式错会 400 "json解析失败"）。
- 拿到 `toolId` 后填入 `nodeSettings.scriptSettings.preScript.scriptIdList`（process_development §4.2）。

> 切面对照：本节是「工具开发态」（创建工具拿 toolId）；`registry/autoops_tool` 的 tool_create/tool_import 是「运行态」接口卡片（卡片 toolType 字段与服务端 type 字段名差异，已在 tool_create 卡片 description 标注）。

---

## 5. 手工打造一个工具包的分发步骤（LLM 操作指引）

当用户说"帮我做一个 XX 功能的工具包"，按以下步骤生成：

**Step 1 — 明确需求**：脚本语言（`type`）、脚本内容（`script` 文件）、工具名/版本号、输入参数（至少含 `@agents`）、超时/执行用户等。

**Step 2 — 生成 ID**：

- `toolId`：32 位十六进制字符串（md5 格式）。若是全新工具可随机生成；若要给线上已有工具加版本，必须使用该工具的真实 toolId。
- `vId`：同上，随机生成一个新 md5。

**Step 3 - 写 `script`**：纯文本脚本内容，无扩展名。脚本中可使用：

- **输入参数**：在 config 的 `inputs[]` 中声明的参数（`name`），平台执行时**作为同名变量直接注入**脚本上下文，**直接引用即可**（shell 用 `$参数名`，python 用 `参数名`）。**不要**用 `getenv`/`os.environ`/`argv` 去取--它们不是环境变量，是平台注入的脚本变量。`@agents` 是执行目标参数，不注入脚本（仅用于决定在哪些主机执行）。
- **内置变量**：以 `EASYOPS_` 为前缀，同样是**平台直接注入的脚本变量**（非环境变量），**直接引用即可**（shell `$EASYOPS_LOCAL_IP`、python `EASYOPS_LOCAL_IP`），**不要** `getenv`/`os.environ`。详见附录 C。
- **内置函数**：平台预注入 `PutStr` / `PutRow` 用于结构化输出（详见附录 A），**不要自己拼 base64 标记**。
- **Python 版本**：默认 **Python 2.7**（无特殊说明时）。需 Python 3 时，在脚本顶部用 shebang 指定解释器路径，如 `#!/usr/local/easyops/python/bin/python`。建议写成 2/3 兼容代码（用 `.format` 而非 f-string）。
- **脚本默认规范（用户定的规则，2026-07-30）**：**默认 shebang 用 `#!/usr/local/easyops/python/bin/python`（平台自带 py2.7）**，代码 2/3 兼容；字符串**不加 `u` 前缀**（`# -*- coding: utf-8 -*-` 声明下中文直接写）。用户没明说时按此默认，不要自行用 py3 shebang 或 `u"..."`。
- **依赖库**：平台预装了一批第三方库（含 `psutil`、`requests`、`PyMySQL` 等，详见附录 C），脚本可直接 `import`。
- **脚本内调平台 API**：工具脚本里要调 EasyOps 平台接口时，**完整内联** `knowledge/concepts/api-calling/api-samples.py` 的 `EasyOpsClient` 类（含 `_request`/`__signature`/`__get_host_and_org`），借 `_request` 发请求；内联规则（禁重构骨架、语法兼容改写边界）以 `concepts/api-calling`「交付脚本形态规范」第 1 条为唯一来源，本节不重复。

**Step 4 — 写 `config`**：按下表最小集 + 按需扩展：

```json
{
  "listVisible": true,
  "templateType": "",
  "tags": [],
  "vId": "<新vId>",
  "vName": "1.0.0",
  "vDesc": "",
  "type": "shell",
  "inputs": [ { "@agents 参数" }, { "业务参数..." } ],
  "timeout": 86400,
  "forceShutdown": true,
  "defaultExecUser": "root",
  "windowsDefaultExecUser": "System",
  "outputDefs": [],
  "tableDefs": [],
  "batchStrategy": {"batchNum":0,"batchInterval":0,"failedStop":true,"enabled":false}
}
```

**Step 5 — 写 `._easyPackageConfig.dat`**：按 §2.1 模板，关键是 `package.name` 与 `package.packageId`（=toolId）必须正确。

**Step 6 — （可选）libs**：若脚本依赖公共库，为每个 lib 生成 `<lib名>.tar.gz`（内含 `<lib名>_repo.tar.gz` + `<lib名>.json`），放入 `libs/`，并在 config 的 `toolLibs` 中登记。

**Step 7 - 打包**：把上述文件放进一个目录（目录名建议用工具名），打成 `tar.gz`。

**文件名规则（重要）**：包文件名统一为 **`{tool_name}_{tool_version}.tar.gz`**，其中 `tool_name` 取 config/`.dat` 中的工具名，`tool_version` 取 config 的 `vName`（与 `.dat` 中 `version.name` 无关，导入端忽略 version 段）。

```bash
tar -czf process_info_1.0.0.tar.gz -C <父目录> process_info/
```

> ⚠️ **更新工具时必须递增版本并同步文件名**：每次修改脚本/配置后，把 config 的 `vName` 递增（如 `1.0.0` -> `1.0.1`），并**重新生成新的 `vId`**（32 位 md5），包文件名同步改为 `{tool_name}_{新vName}.tar.gz`。`toolId`（= `.dat` 的 `packageId`）**保持不变**（同 toolId 视为给已有工具新增版本，不会冲突）。若想作为全新工具导入，则改 `toolName` 并在导入参数传 `newName`。
>
> ⚠️ **隐藏文件注意**：`._easyPackageConfig.dat` 以 `.` 开头，macOS 自带 `tar` 会把 `._` 开头文件当 AppleDouble 元数据吞掉（`tar -t`/`tar -x` 都看不到，但不影响 Linux 导入端 GNU tar）。**打包务必在 Linux 上进行**，或在 macOS 上用 Python `tarfile` 打包、显式加入该文件。

**Step 8 — 导入验证**：

1. 先调 `POST /api/tool_service/v1/batch/import/pkg/check` 预检，看 `result` 与 `diffList`；
2. 无冲突后 `POST /tools/import`（multipart 上传）；有冲突按 §3.2 用 `newName`/`newVersionName` 化解；
3. 跨环境分发且希望免审批上线时，加 `systemImport=true`。

**导入成功后的前端验收**：导入接口返回 `toolId` 后，引导用户去前端工具管理详情页验收（参数渲染/脚本内容/手动执行）：

```
http://<host>/next/tool/management/<toolId>/detail
```

（`<toolId>` 即 .dat 的 `packageId` / 导入返回的 toolId。）**交付工具包时应把这个 URL 拼好给用户**，方便其直接打开验收。

**常见坑**：

- 包内忘了 `._easyPackageConfig.dat` → 直接导入失败；
- `.dat` 里 `packageId` 与 config 想表达的工具身份不一致 → toolId 以 .dat 为准；
- 想"换个名字导入成新工具" → 必须在导入参数传 `newName`（光改包里的 name 会因 toolId 相同被当成已有工具的新版本）；
- `libs/` 下的压缩包文件名（去掉 `.tar.gz`）必须与其内部 `<lib名>.json` 的 `name` 一致；
- config 里写 `content` 是无效的，脚本必须放 `script` 文件。

---

## 附录 A：工具输出（outputDefs / tableDefs）完整说明

工具输出用于把脚本执行结果**结构化**地回传给平台（供流程下游步骤引用、执行历史展示、表格渲染）。分两类：**输出变量**（outputDefs）和**输出表格**（tableDefs）。

> ⚠️ **脚本输出统一用平台内置函数 `PutStr` / `PutRow`，不要自己拼 base64 标记**。平台在脚本执行环境预注入了这两个内置函数，调用即可，无需（也不应）手写 `##PARAMETER_...##` / `##TABLE_ROW_...##` 这类底层标记。下文早期的 base64 标记协议是平台内部实现细节，已废弃作为开发接口。

### A.1 输出变量（outputDefs）- 用 `PutStr`

**config 中定义**：

```json
"outputDefs": [
  {"id": "result_code", "name": "结果码"},
  {"id": "deploy_version", "name": "发布版本"}
]
```

| 字段     | 说明                                                                                     |
| -------- | ---------------------------------------------------------------------------------------- |
| `id`   | 输出变量标识，脚本中用`PutStr(id, value)` 输出，下游流程用 `${步骤.outputs.id}` 引用 |
| `name` | 展示名称                                                                                 |

**内置函数 `PutStr`**：

- 支持 shell / python / powershell；
- 语义：`PutStr(id, value)` 把 `value` 作为名为 `id` 的输出变量回传平台；
- `id` 必须先在 outputDefs 中声明，且与声明完全一致；
- `value` 仅支持**字符串**，非字符串需先转换（如 `str(x)`）；多行字符串安全。

**示例（python）**：

```python
# encoding: utf-8
PutStr("deploy_version", "1.2.3")
PutStr("result_code", "0")
```

**示例（shell）**：

```bash
PutStr "deploy_version" "1.2.3"
PutStr "result_code" "0"
```

**内置输出**（平台配置 `toolConfig.toolInnerOutput=true` 时自动附加，无需在脚本中输出，也无需在 outputDefs 声明）：

| id                             | 含义                         |
| ------------------------------ | ---------------------------- |
| `INTERNAL_TASK_START_TIME`   | 执行开始时间（毫秒时间戳）   |
| `INTERNAL_TASK_END_TIME`     | 执行结束时间（毫秒时间戳）   |
| `INTERNAL_TASK_SUCCESS_LIST` | 执行成功主机列表（逗号分隔） |
| `INTERNAL_TASK_FAILURE_LIST` | 执行失败主机列表（逗号分隔） |

### A.2 输出表格（tableDefs）- 用 `PutRow`

用于在执行历史页渲染**多行多列**的结构化结果表。理解 `dimensions`（维度列，类比数据库**主键**）与 `columns`（输出列，类比**属性列**）是关键：维度列相同的多个 `PutRow` 会被合并成同一行的不同属性。

**config 中定义**：

```json
"tableDefs": [{
  "id": "default",
  "name": "默认",
  "dimensions": [{"id": "ip", "name": "IP"}],
  "columns": [
    {"id": "hostname", "name": "主机名"},
    {"id": "cpu", "name": "CPU"}
  ]
}]
```

| 字段           | 说明                                                                 |
| -------------- | -------------------------------------------------------------------- |
| `id`         | 表格标识；空或`default` 为默认表。**多张表时用不同 id 区分** |
| `name`       | 表格展示名                                                           |
| `dimensions` | 维度列（主键，同维度值的行会合并成一行）                             |
| `columns`    | 输出列（属性列）                                                     |

**内置函数 `PutRow`**：

- 支持 shell / python / powershell；
- 语义：`PutRow(table_key, row_str)`
  - `table_key`：表名称（**预留字段，填空字符串 `""` 即可，不能为 `null`**；多表时可用 config 中 tableDefs 的 `id` 区分，默认表填 `""`）；
  - `row_str`：一条记录，**URL query 风格**字符串 `k1=v1&k2=v2&k3=v3`，键名对齐 dimensions/columns 的 `id`；
- 同维度值的多个 `PutRow` 会按输出列合并到同一行（如下例两行 `ip=127.0.0.1` 合并）。

**示例（python）**，`ip` 是维度列，`hostname`/`cpu`/`memory` 是输出列：

```python
# encoding: utf-8
PutRow("t1", "ip=127.0.0.1&hostname=CentOS-1&cpu=intel-i7")
PutRow("t1", "ip=127.0.0.1&memory=12G")
PutRow("t1", "ip=127.0.0.2&hostname=CentOS-2&cpu=intel-i5&memory=18G")
```

渲染结果：

| ip        | hostname | cpu      | memory |
| --------- | -------- | -------- | ------ |
| 127.0.0.1 | CentOS-1 | intel-i7 | 12G    |
| 127.0.0.2 | CentOS-2 | intel-i5 | 18G    |

**row_str 构造规则**：

- 以 `&` 分隔 kv，`=` 分隔键值；value 中的 `&`/`=`/`%` 等特殊字符建议 URL 编码（如 `%` -> `%25`），平台侧会做 URL decode（失败则用原值）；
- `arr[]=v1&arr[]=v2` 会被解析为数组；
- 平台自动给每行附加 `_E_AGENT`（执行机）、`_E_TABLE`（表 id）两个内部字段，脚本不用管；
- 多主机执行时，脚本在每台机器上各跑一次、各自 `PutRow`，平台按 dimensions 合并展示（建议把主机 IP 等纳入 dimensions，避免跨主机同维度值误合并）。

### A.3 输出的消费位置

| 位置                 | 内容                                                           |
| -------------------- | -------------------------------------------------------------- |
| 执行历史 -> 输出变量 | `outputs.<agent>.<id>` = `PutStr` 的 value                 |
| 执行历史 -> 输出表格 | 按 tableDefs 的 dimensions/columns 渲染，多 agent 数据合并展示 |
| 流程下游步骤         | 通过输出变量 id 引用上游工具的输出                             |

**兼容说明**：老格式 `toolOutputs`（单表结构）在导入时会自动转换为 `tableDefs`（id=`default`）+ `outputDefs`（由 columns 生成），新包请直接使用 `outputDefs`/`tableDefs`。

---

## 附录 B：沙箱执行（sandboxRun / containerSandbox）

平台提供两种隔离执行机制，均定义在工具版本上（config 文件字段）：

### B.1 沙箱机执行 —— `sandboxRun`

```json
"sandboxRun": true
```

| 项             | 说明                                                                                                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 语义           | 该工具**不在用户指定的目标机上执行**，而是固定路由到平台部署的**沙箱机**执行                                                                                      |
| 执行目标       | 执行时忽略`@agents` 入参，由服务端通过名字服务 `sandbox.service_name`（tool_service 配置）解析出沙箱机 IP，作为唯一 target（`loadSandboxHost`）                         |
| 权限影响       | 沙箱工具**只校验"工具执行"权限**（`ToolExecuteAction`），即使执行用户是 root 也**不校验 root 执行权限**；`CheckExecUserPermission` 直接放行（不校验黑白名单） |
| 典型用途       | 敏感/高危操作收敛到一台受控机器执行；多应用发布、pipeline 等系统内部调用的工具                                                                                                |
| 配套服务端配置 | tool_service 配置`sandbox.service_name`（沙箱服务名）、`sandbox.exec_user`、`sandbox.tools`/`sandbox.ips`（免校验白名单组合）、`sandbox.ignorePermission`           |

**另一类隐式沙箱**（`isSandboxRequest`）：即使工具本身 `sandboxRun=false`，当执行请求满足"**单个目标** 且 toolId ∈ 配置 `sandbox.tools` 且 目标 IP ∈ 配置 `sandbox.ips`"时，也按沙箱请求对待（免 root 权限校验、免执行用户黑白名单校验）。这是给 pipeline 等内部系统预留的通道，工具包开发者无需关心。

### B.2 容器沙箱执行 —— `containerSandbox`

```json
"containerSandbox": {
  "enable": true,
  "image": "registry.example.com/easyops/tool-sandbox:py3.11"
}
```

| 字段       | 说明                                                                        |
| ---------- | --------------------------------------------------------------------------- |
| `enable` | 是否启用容器沙箱。`true` 时 `IsSandboxRun()` 同样成立（权限规则同 B.1） |
| `image`  | 执行容器的镜像地址                                                          |

**镜像生效逻辑**（`assembleAction`）：

| 平台配置`containerSandboxConfig.enableCustom` | 实际使用镜像                                                                           |
| ----------------------------------------------- | -------------------------------------------------------------------------------------- |
| `true`                                        | 工具包中声明的`containerSandbox.image`（允许工具自定义镜像）                         |
| `false`（默认）                               | **忽略工具声明的 image**，统一用平台配置 `containerSandboxConfig.defaultImage` |

> ⚠️ 开发注意：你写在 config 里的 `image` 是否真正生效取决于目标环境的平台配置。跨环境分发工具包时，若依赖特定镜像，需先确认目标环境 `enableCustom=true`，否则脚本会被平台默认镜像执行。

### B.3 两种沙箱的对比与选择

| 维度     | `sandboxRun`                         | `containerSandbox`                  |
| -------- | -------------------------------------- | ------------------------------------- |
| 隔离级别 | 专用沙箱机（整机隔离）                 | 容器级隔离（可在任意 agent 上起容器） |
| 目标机   | 固定沙箱机，忽略 @agents               | 仍在 @agents 目标上，但以容器方式运行 |
| 镜像定制 | 不涉及                                 | 支持（受平台开关约束）                |
| 权限     | 均免 root 执行权限校验、免黑白名单校验 | 同左                                  |
| 适用场景 | 高危操作收敛、内部系统工具             | 依赖特定运行时/依赖环境的脚本         |

**打包建议**：

- **沙箱默认策略（用户定的规则，2026-07-29）**：**默认不设沙箱**（`sandboxRun` 省略或 `false`、`containerSandbox` 为 null），让工具在用户指定的 `@agents` 目标机上执行；**仅 ITSM 流程节点前后置脚本 / 表单生命周期脚本必须 `sandboxRun: true`**（走 py_script_runner，见 §4.1 与 form-advanced §3.5）。用户没明说时按默认（非沙箱）做，不要自行加 `sandboxRun: true`。
- 两者都属**版本级**字段（ToolVersion），直接写进 config 即可随包分发；
- 设置 `sandboxRun=true` 的工具，`inputs` 中即使保留 `@agents`，执行时也会被忽略，建议在 `memo` 中注明"沙箱执行，无需选择目标"；
- 设置容器沙箱时，建议同时在 `envLinux` 中声明脚本依赖的环境变量，避免不同镜像环境差异导致执行失败。

---

## 附录 C：脚本运行环境（内置变量 / 内置函数 / 预装库）

> 本节是脚本开发的核心参考，源自工具平台开发教程。脚本在目标机（或沙箱机）执行时，平台会预注入下列变量与函数。

### C.1 默认规则

- 工具执行**成功/失败由脚本返回码决定**：`0` 为成功，非 `0` 为失败（脚本最后用 `sys.exit(0)` / `exit 0`）。
- 输出参数（`PutStr`/`PutRow` 的 value）**只支持字符串**，非字符串需先转换。
- Linux 支持 Shell 和 Python；Windows 主机支持 Python 和 PowerShell。

### C.2 内置变量

以 `EASYOPS_` 为前缀，**由平台直接注入为脚本变量（非环境变量）**，直接引用即可，**不要**用 `getenv`/`os.environ` 读取。**Shell** 用 `$EASYOPS_SCRIPT_TYPE`；**Python** 用 `EASYOPS_SCRIPT_TYPE`（无 `$`）；**PowerShell** 用 `$EASYOPS_SCRIPT_TYPE`。

> ⚠️ **本清单为教程摘录，未全量实测；已反证一项**：`EASYOPS_DEPLOY_REPO_HOST` 在 2026-07-30 实战中未按预期注入。引用任一变量前先按 §5 Step 3 的「变量探针版本」确认，或改用显式 HOST 常量。

| 名称                         | 说明                                | 例子                                    |
| ---------------------------- | ----------------------------------- | --------------------------------------- |
| `EASYOPS_SCRIPT_TYPE`      | 脚本类型                            | `shell` / `python` / `powershell` |
| `EASYOPS_PARSER`           | 解释器                              | `bash` / `python`                   |
| `EASYOPS_EXEC_USER`        | 执行用户                            | `root`                                |
| `EASYOPS_AGENTS`           | 需执行该命令的所有主机 IP，逗号分隔 | `192.168.100.13,192.168.100.53`       |
| `EASYOPS_TOOL_ID`          | 工具 ID                             | `b5b17f43d9127f265dc297216758fc04`    |
| `EASYOPS_TOOL_NAME`        | 工具名                              | `test`                                |
| `EASYOPS_NEED_NOTIFY`      | 是否需要通知                        | `1`                                   |
| `EASYOPS_LOCAL_IP`         | 当前主机 IP                         | `192.168.100.13`                      |
| `EASYOPS_ORG`              | 机构 ID                             | `8888`                                |
| `EASYOPS_USER`             | 登录用户                            | `easyops`                             |
| `EASYOPS_DEPLOY_HOST`      | DEPLOY IP                           | `172.30.10.35:8176`                   |
| `EASYOPS_CMDB_HOST`        | CMDB IP                             | `172.30.10.34:8113`                   |
| `EASYOPS_DEPLOY_REPO_HOST` | DEPLOY REPO IP                      | `172.30.10.47:10082`                  |
| `EASYOPS_OPEN_API_ACCESS`  | open api access                     | `b58e0318d612d773f6ba4e3d`            |
| `EASYOPS_OPEN_API_SECRET`  | open api secret                     | `16a389eba9...`                       |
| `EASYOPS_OPEN_API_HOST`    | open api host ip                    | `172.30.10.35:80`                     |
| `EASYOPS_EASYFLOW_HOST`    | easyFlow host ip                    | `172.30.10.34:8061`                   |

> 💡 取当前主机 IP 优先用 `EASYOPS_LOCAL_IP`，比 `socket.gethostname()` 更准确。

### C.3 内置函数

| 名称                       | 支持语言                    | 说明                                                                                                                                                       |
| -------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PutStr`                 | shell / powershell / python | 输出**输出变量**（对应 outputDefs）。`PutStr(id, value)`，`id` 须先在输出定义中声明。详见附录 A.1                                                |
| `PutRow`                 | shell / powershell / python | 输出**表格行**（对应 tableDefs）。`PutRow(table_key, row_str)`，`table_key` 预留字段填 `""`，`row_str` 为 `k1=v1&k2=v2` 记录。详见附录 A.2 |
| `AutoDiscoveryJson`      | python                      | 【自动发现专用】接受 dict 组成的 list，转换为自动发现格式输出到 stdout。`None` 值转为 `NULL`                                                           |
| `AutoDiscoverySetKey`    | shell                       | 【自动发现专用】接受空格分隔的字符串，设置 key 顺序，需与`AutoDiscoverySetValue`/`AutoDiscoveryPrintData` 配合                                         |
| `AutoDiscoverySetValue`  | shell                       | 【自动发现专用】按`AutoDiscoverySetKey` 的 key 顺序设置值                                                                                                |
| `AutoDiscoveryPrintData` | shell                       | 【自动发现专用】输出已格式化的自动发现数据                                                                                                                 |

### C.4 预装第三方 Python 库

平台预装（`==` 后为版本），脚本可直接 `import`：

| -                         | -                         | -                          | -                               | -                   |
| ------------------------- | ------------------------- | -------------------------- | ------------------------------- | ------------------- |
| `beautifulsoup4==4.6.0` | `bs4==0.0.1`            | `chardet==2.3.0`         | `ConcurrentLogHandler==0.9.1` | `Cython==0.25.2`  |
| `dpkt==1.8.8`           | `gevent==1.1.0`         | `greenlet==0.4.9`        | `Jinja2==2.9.6`               | `MarkupSafe==1.0` |
| `netifaces==0.10.5`     | `nmap==0.0.1`           | `pexpect==4.2.1`         | `protobuf==2.6.1`             | `psutil==4.3.0`   |
| `ptyprocess==0.5.1`     | `py-cpuinfo==0.1.8`     | `pyaml==15.8.2`          | `pycrypto==2.6.1`             | `pymongo==3.0.3`  |
| `PyMySQL==0.7.9`        | `python-crontab==2.1.1` | `python-dateutil==2.6.0` | `python-memcached==1.58`      | `pytz==2017.2`    |
| `redis==2.10.5`         | `requests==2.8.1`       | `setproctitle==1.1.9`    | `simplejson==3.10.0`          | `six==1.10.0`     |

> 💡 `psutil` 已预装，进程/系统信息采集可直接使用。注意版本较老（4.3.0），避免使用新版独有 API。

---

如需要，我可以继续补充：`envLinux/envWindows`（EnvEntry）结构、`execTimeWindowConfig`、`execPreAuth`、或 `notice`（通知配置）的字段细节。
