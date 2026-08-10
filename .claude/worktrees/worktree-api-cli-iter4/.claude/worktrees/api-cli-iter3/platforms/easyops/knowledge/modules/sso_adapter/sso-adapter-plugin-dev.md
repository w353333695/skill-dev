---
name: sso-adapter-plugin-dev
kind: module
module: sso_adapter
tags:
- SSO
- 单点登录
- sso_adapter
- 插件
- provider
- OAuth2
- CAS
- SAML
- 统一门户
- 移动端
- 单点登出
- CMDB-USER
- 登录回调
- 端口8211
- easy_tornado
- Python2.7
completeness: partial
gaps:
- 基于 sso_adapter 组件源码 + README 归纳，未在真实 sso_adapter 部署环境端到端导入插件包验证（插件加载/接口冒泡/浏览器回跳为源码逻辑推导，非真机实测）
- 内置 oauth2/cas/demo/easy_work 插件源码未直接读取，可复用点与重写方法对照表为源码 README 归纳，方法签名以基类 base_provider.py 契约为准
- redirect_uri 端口补全规则（demo 无端口补 80 / cas 无端口不补）未读到源码实现，两者差异原因未确认
- userinfo 返回字段名（preferred_username/username/sub 等）依 OAuth2 通用约定，三方 SSO 实际返回字段未核对
- APPLICATION 监听配置（listen_port/processes_num）默认值为源码摘录，本环境实际部署配置未核对
scope:
- 对接一个三方 SSO（统一门户/移动端单点登录），交付可在 sso_adapter 部署目录解压即用的插件 zip 包
- 理解 sso_adapter 插件加载机制（目录名=类名=PLUGIN_CONFIG key 三一致）与命名约束（\w+）
- 实现/重写 Provider 基类的 pre_signin/signin/user_info/sign_out 四个必需方法 + 可选钩子
- 编写 setting_custom.py（PLUGIN_CONFIG 注册 + 三方连接参数，jsonschema 校验）
- 排查插件加载失败 / 登录回跳失败 / 用户匹配失败等现场故障
- 现场部署：解压、合并配置、重启、冒烟、端到端验证
related:
- concepts/instance-id（CMDB USER 模型 login_key 字段定位用户）
- concepts/api-calling（sso_adapter 名字服务 logic.sso_adapter，端口 8211；网关路径 /next/api/gateway）
- registry/（sso_adapter 对外 HTTP 接口若需编排可后续建卡片，本知识描述组件/插件「对接开发态」）
last_verified: '2026-07-27'
note: 'EasyOps sso_adapter 统一登录适配服务的三方 SSO 对接开发说明：组件定位与运行模型（端口 8211、easy_tornado、
  Python2.7）、8 个 HTTP 接口路由与调用插件方法映射、登录全流程时序（brick_next→api_gateway→sso_adapter→三方SSO）、
  Provider 插件开发规范（加载机制三一致、基类契约、配置 settings 机制、py2.7/内置库/日志约束）、内置插件参考（oauth2/cas/demo/easy_work）、
  交付物 zip 包结构与现场部署步骤、LLM 开发引导决策流程。来源：sso_adapter 组件源码 + README 整理，未真机端到端实测。
  切面定位：本知识描述 sso_adapter 「对接开发态」（如何新增一个三方 SSO 插件），registry 若有 sso_adapter 接口卡片则描述
  「运行态」（调用 pre-signin/signin 等接口）——同名对象不同切面，互补参照，非重复。'
---

# EasyOps 三方 SSO 对接开发说明（sso_adapter 插件）

> 面向 LLM 的开发指南。基于 `sso_adapter` 组件源码整理。
> 目标：理解 sso_adapter 的产品逻辑与插件机制，能够交付一个 **zip 包**（含 `setting_custom.py` 配置 + provider 插件代码），在客户现场的 `sso_adapter` 部署目录下解压、重启服务即可完成一个三方 SSO（统一门户 / 移动端单点登录）的接入。

## 1. 组件定位与运行模型

| 项       | 值                                                                                                            |
| -------- | ------------------------------------------------------------------------------------------------------------- |
| 组件名   | `sso_adapter`（统一登录适配服务）                                                                           |
| 名字服务 | `logic.sso_adapter`                                                                                         |
| 监听端口 | **8211**                                                                                                |
| 技术栈   | Python 2.7（`/usr/local/easyops/python/bin/python`）+ easy_tornado（Tornado 封装）                          |
| 入口     | `sso_adapter_main.py`                                                                                       |
| 插件目录 | `handlers/providers/<plugin_name>/`                                                                         |
| 配置文件 | `settings/setting.py`（内置默认，勿改）+ `settings/setting_custom.py`（现场覆盖，**交付物改这里**） |

**核心思想**：SSO 对接以**插件（provider）**形式实现。新增一个三方 SSO = 新增一个 `handlers/providers/xxx/` 目录 + 在 `PLUGIN_CONFIG` 注册，**无需修改 api_gateway 和前端 brick_next**。

### 1.1 HTTP 接口（sso_adapter_main.py 路由）

| 路由                                        | 方法 | 调用的插件方法                                             | 用途                                                    |
| ------------------------------------------- | ---- | ---------------------------------------------------------- | ------------------------------------------------------- |
| `/api/v1/pre-signin/<pk>`                 | GET  | `pre_signin(params)`                                     | 获取统一认证平台登录页地址                              |
| `/api/v1/signin/<pk>`                     | GET  | `signin(params)` + `user_info(info)`                   | 用 query 中的登录凭证换用户身份（浏览器重定向回调场景） |
| `/api/v1/sign-auth/<pk>`                  | POST | `signin(params)` + `user_info(info)`                   | 同上，POST 变体（表单回传场景）                         |
| `/api/v1/sso_adapter/auth-post-deal/<pk>` | POST | `authorize_post_deal(query)`                             | 授权后处理（钩子，可选）                                |
| `/api/v1/sign-out/<pk>`                   | POST | `sign_out(params)`                                       | 获取登出重定向地址                                      |
| `/api/v1/global/sign-out`                 | POST | `sso_global_sign_out(params)`（固定走 `default` 插件） | SSO 服务端发起的全局登出回调                            |
| `/api/v1/custom_auth/password`            | POST | `custom_auth(params)`（固定走 `default` 插件）         | 自定义账号密码校验                                      |

`<pk>` 即插件名（protocol），`\w+` 匹配。所有接口统一返回 `{"code":0, "error":"", "data":{...}}`，异常时抛出 4xx/5xx 及中文错误信息。

### 1.2 登录全流程时序

```
浏览器 → brick_next → api_gateway → sso_adapter → 统一认证平台(SSO)
1. 未登录访问 brick_next → 重定向 /next/sso-auth/login
2. brick_next 经 api_gateway 调 sso_adapter: GET /api/v1/pre-signin/<pk>
   → 插件 pre_signin() 返回 SSO 登录页 URL
3. 浏览器重定向到 SSO 登录页，用户输入账号密码
4. SSO 携带凭证(code/ticket)重定向回:
   http://<BRICK_NEXT_HOST>/next/sso-auth/authorize?code=xxx&state=xxx
   （回调地址固定为 /next/sso-auth/authorize，OAuth2 用 redirect_uri 参数指定，
    CAS/SAML 在 SSO 后台配置）
5. brick_next 经 api_gateway 调 sso_adapter: GET /api/v1/signin/<pk>?code=xxx&state=xxx
   → 插件 signin(params) 用凭证换 authorization_info（暂存）
   → 插件 user_info(authorization_info) 返回 (login_key, login_value)
6. api_gateway 用 login_key/login_value 在 CMDB USER 模型匹配用户，完成登录
7. 登出: POST /api/v1/sign-out/<pk> → 插件 sign_out() 返回 SSO 登出 URL
```

**关键约束**：`user_info` 返回的 `(login_key, login_value)` 必须能定位 **CMDB USER 模型**中的唯一用户（login_key 是 USER 模型的字段 ID，如 `name`/`email`；login_value 是该字段的值）。**用户必须已存在于 CMDB**（通常由交付方做定时增量同步；自动建用户未实现）。

---

## 2. Provider 插件开发规范

### 2.1 插件加载机制（必须严格遵守的命名约定）

加载器 `handlers/provider_cache/cache.py::load_plugins` 的规则：

1. 遍历 `PLUGIN_CONFIG` 的每个 key（除 `default`），作为插件名 `plugin_module`；
2. 到目录 `handlers/providers/<plugin_module>/` 下，**遍历该目录所有 `.py` 文件**（除 `__init__.py`），逐个 `imp.load_source` 加载；
3. 在加载出的模块中查找**类名与插件名完全相同**的类（`inspect.isclass`）；
4. 找到则实例化（调用 `__init__`）并缓存；找不到或初始化抛异常 → 该插件加载失败（记 warn 日志，不影响其他插件）；
5. `PLUGIN_CONFIG.default` 必须指向一个已成功加载的插件，否则服务启动失败（`ProviderCache is None` / `PLUGIN_CONFIG.default isn't exist`）。

> ⚠️ 推论（交付时必须保证）：
>
> - **目录名 = 类名 = PLUGIN_CONFIG 的 key**，三者完全一致（`CaseInsensitiveDict`，大小写不敏感，但建议统一小写）；
> - 插件名只能是 `\w+`（字母/数字/下划线），因为路由正则 `(?P<pk>\w+)`；
> - 主类所在的 `.py` 文件名任意（加载器遍历目录全部 py 文件），但建议与目录同名（如 `mysso/mysso.py`），辅助模块（如 `xxx_client.py`）可同目录放置；
> - `__init__.py` 必须存在但**为空**即可（它不会被 load_source，只保证包结构）；
> - 类在 `__init__` 中读取 `PLUGIN_CONFIG.get("<插件名>")` 并用 **jsonschema 校验**，配置缺失/非法要在 `__init__` 直接抛异常——这样现场配置错误能在服务启动/插件加载时立即暴露（日志：`load plugin xxx error`）。

### 2.2 基类与必须实现的方法

`handlers/providers/base_provider.py`：

```python
class Provider:
    def pre_signin(self, params): ...        # 必须实现
    def signin(self, params): ...            # 必须实现
    def user_info(self, authorization_info): ...  # 必须实现
    def authorize_post_deal(self, params): ...    # 可选，默认空实现
    def sign_out(self, authorization_info): ...   # 必须实现（不需要可 return ""）
    def custom_auth(self, params): ...            # 可选（仅在走 /custom_auth/password 时需要）
    def sso_global_sign_out(self, params): ...    # 可选（仅在 SSO 支持全局登出回调时需要）
```

#### 方法契约详解

| 方法                              | 入参                                                                                                               | 返回值                                                      | 说明                                                                                                                                         |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `pre_signin(params)`            | `params: dict`，浏览器侧传来的 query 参数                                                                        | `str`（登录页 URL）**或** `PreSignInRequest` 对象 | 返回统一认证平台登录地址。返回`PreSignInRequest(login_url, method, data)` 可支持 POST 方式跳转（`method="POST"` + `data`=表单参数）    |
| `signin(params)`                | GET 场景：回调 URL 的 query 参数字典（如`{"code":"...","state":"..."}`）；POST 场景（sign-auth）：表单 body 字典 | `authorization_info: dict`（自定义结构）                  | 用登录凭证调 SSO 接口换取用户标识。返回的 dict 会被 api_gateway**暂存**，登出时原样回传给 `sign_out`                                 |
| `user_info(authorization_info)` | `signin` 的返回值                                                                                                | **tuple `(login_key, login_value)`**                | login_key = CMDB USER 模型的唯一字段 ID（`name`/`email`/自定义字段）；login_value = 该字段的值。二者必须能唯一定位一个已存在的 CMDB 用户 |
| `authorize_post_deal(params)`   | POST body 中`query` 字段（dict），含 `username`、`access_token` 等                                           | 无                                                          | 授权成功后的扩展钩子（如同步 token、记录审计），不需要则不重写                                                                               |
| `sign_out(authorization_info)`  | 暂存的`authorization_info`                                                                                       | `str`（登出跳转 URL）**或** `SignOutRequest` 对象 | 返回`""` 表示登出后回到 sso 登录页；某些协议需带 service 参数或用暂存的 ticket                                                             |
| `custom_auth(params)`           | `{"user":..., "password":...}` 等                                                                                | `True`/`False`                                          | 自定义密码校验（如对接 LDAP/第三方校验接口）。**禁止打印 password**                                                                    |
| `sso_global_sign_out(params)`   | SSO 服务端 POST 回调的 form 参数（`urlparse.parse_qs` 结果，值为 list）                                          | `ticket: str`                                             | 解析回调报文，返回要登出的会话票据（CAS 场景为 session_index）。api_gateway 据此注销本地会话                                                 |

**辅助类**（`handlers/providers/http_request_info.py`）：

```python
PreSignInRequest(login_url="", method="GET", data=None)  # pre_signin 的结构化返回
SignOutRequest(logout_url="", method="GET", data=None)   # sign_out 的结构化返回
```

### 2.3 配置机制（settings）

- `settings/setting.py`：内置默认值（仓库自带），**末尾调用 `merge_setting(locals(), "settings.setting_custom")`**，即 `setting_custom.py` 中的同名变量会**深合并覆盖** `setting.py`；
- **交付只写 `settings/setting_custom.py`**，结构：

```python
# -*- coding: utf-8 -*-
PLUGIN_CONFIG = {
    "default": "mysso",          # 默认插件：url中不带协议名时走它；必须与下方某个key一致
    "mysso": {                    # 插件配置块，key=插件名
        "login_url": "https://sso.customer.com/login",
        "redirect_uri": "http://easyops.customer.com",
        "client_id": "***",
        "client_secret": "***",
        # ... 插件自定义字段
    },
}
# 可选：覆盖监听配置
# APPLICATION = {"debug": False, "listen_host": "0.0.0.0", "listen_port": 8211, "processes_num": 4, "application": {}}
```

- `redirect_uri` 约定：配置为平台入口地址（如 `http://easyops.xxx.com` 或带端口），插件在 `__init__` 中拼出真实回调 `{address}/next/sso-auth/authorize`（参考 demo/cas 的写法；demo 无端口时补 80，cas 无端口则不补）。

### 2.4 开发约束（源码 README 明确要求）

1. **只能用平台 python 环境已有的依赖库**（`/usr/local/easyops/python` 的 requirements，`requests`、`jsonschema`、`pycrypto` 等常见库已内置）；引入新库需确认无系统级依赖；
2. 关键路径打 `logging.info/error` 日志，生产验证后再精简；日志文件 `./log/server.log`；
3. **敏感信息（password、secret）禁止打印日志**；`custom_auth` 中应先把 `params["password"]` 置空再打日志（见 demo）；
4. Python 2.7 语法（`urlparse`、`urllib.urlencode`、print 语句、`except Exception, e` 均可能出现；写新代码保持 py2 兼容）。

---

## 3. 内置插件参考实现

| 插件          | 目录                                    | 协议/场景                                                            | 可复用点                                                                                                                                                                              |
| ------------- | --------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `demo`      | `handlers/providers/demo/demo.py`     | 教学示例                                                             | 配置校验、PreSignIn 拼装、custom_auth 骨架                                                                                                                                            |
| `oauth2`    | `handlers/providers/oauth2/oauth2.py` | 标准 OAuth2（authorization_code，支持 online/offline refresh）       | **最接近"模板"的实现**：把每个 HTTP 步骤拆成可重写的小方法（`signin_authorization_method/headers/body/params`、`parse_user_info` 等），非标准 OAuth2 只需继承并重写个别方法 |
| `cas`       | `handlers/providers/cas/`             | CAS 协议（含全局登出`sso_global_sign_out` 解析 logoutRequest XML） | `cas_client.py` 封装了 service_validate / logout 报文解析（RSA 验签）                                                                                                               |
| `easy_work` | `handlers/providers/easy_work/`       | 门户免密跳转（token 换用户名）                                       | 演示"非重定向型"接入：`pre_signin` 返回 `""`，`signin` 从自定义参数取 token 调 openapi 验身份，还支持把 `redirect_url` 透传为 `easyops_host` 实现登录后跳回原页面           |

**OAuth2 非标准变体的推荐做法**：把 `oauth2.py` 复制为 `handlers/providers/<yoursso>/<yoursso>.py`，类名改为 `<yoursso>`，按需重写：

| 要定制的点                           | 重写的方法                                                     |
| ------------------------------------ | -------------------------------------------------------------- |
| 登录页参数非 RFC6749                 | `pre_signin_required_params`                                 |
| 需要自定义 state                     | `pre_signin_state` / `signin_state`                        |
| 换 token 的请求方式/body/header 特殊 | `signin_authorization_method/body/headers/params`            |
| token 响应非标准 JSON                | `signin_parse_response`                                      |
| userinfo 接口鉴权/报文特殊           | `user_info_endpoint` / `user_info_endpoint_response`       |
| login_key/login_value 提取规则       | `parse_user_info`（默认返回 `("name", user_info["sub"])`） |
| 登出时要吊销 token                   | `sign_out`                                                   |

---

## 4. 交付物：zip 包结构与分发步骤

### 4.1 zip 包目录结构（以插件名 `mysso` 为例）

```
mysso-sso-adapter-plugin.zip
├── handlers/
│   └── providers/
│       └── mysso/
│           ├── __init__.py          # 空文件
│           ├── mysso.py             # 主插件类: class mysso(Provider)
│           └── mysso_client.py      # (可选) SSO接口封装等辅助模块
└── settings/
    └── setting_custom.py            # PLUGIN_CONFIG 注册 + 三方SSO连接参数
```

**硬性检查清单**：

- [ ] 目录名 `mysso` == 类名 `mysso` == `PLUGIN_CONFIG` 的 key `"mysso"`；
- [ ] 插件名只含 `\w`（字母数字下划线）；
- [ ] `__init__.py` 存在且为空；
- [ ] 主类 `__init__` 中：`PLUGIN_CONFIG.get("mysso")` 为 None 时抛异常 + jsonschema 校验配置；
- [ ] 实现 `pre_signin` / `signin` / `user_info` / `sign_out` 四个必需方法；
- [ ] `user_info` 返回的 login_key 对应的 CMDB USER 字段已确认（与客户确认用 `name` 还是 `email` 等），且用户同步方案已落实；
- [ ] `setting_custom.py` 中 `default` 指向 `mysso`（若该平台只接这一个 SSO）；
- [ ] `setting_custom.py` 不含注释掉的测试密钥以外的真实密钥泄露风险项（现场部署时再填真实值，zip 内用 `__CLIENT_SECRET__` 占位亦可）；
- [ ] 仅用平台内置 python 库；py2.7 语法兼容。

### 4.2 现场部署步骤

```bash
# 1. 定位 sso_adapter 部署目录（以实际部署路径为准）
cd /data/easyops/sso_adapter    # 或 /usr/local/easyops/sso_adapter

# 2. 备份现有配置
cp settings/setting_custom.py settings/setting_custom.py.bak.$(date +%F)

# 3. 解压交付包到部署根目录（zip 内路径与部署目录一一对应）
unzip -o mysso-sso-adapter-plugin.zip -d .

# 4. 合并配置：若现场已有 setting_custom.py（已有其他插件），
#    不要直接覆盖！应把 zip 中 PLUGIN_CONFIG 的 "mysso" 块和 default
#    合并进现有文件（merge_setting 是同名字段整体覆盖，同名dict会合并，
#    但 PLUGIN_CONFIG 整个变量以 setting_custom.py 为准）

# 5. 重启服务
#    （具体命令视部署方式: supervisorctl / systemctl / 平台服务管理）
supervisorctl restart sso_adapter   # 示例

# 6. 验证
# 6.1 插件是否加载成功（日志出现 load plugin mysso，无 error）
tail -f ./log/server.log
# 6.2 直接调接口冒烟（应返回 SSO 登录页 URL）
curl 'http://127.0.0.1:8211/api/v1/pre-signin/mysso'
# 期望: {"code":0,"error":"","data":{"method":"GET","redirectURL":"https://sso...","requestArgs":null}}

# 7. 浏览器端到端验证：退出登录 → 访问平台 → 跳转三方SSO → 登录 → 回跳平台成功
```

### 4.3 常见故障速查

| 现象                                          | 排查                                                                                                         |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 日志`load plugin mysso error`               | 插件`__init__` 抛异常：多为 `PLUGIN_CONFIG.mysso` 缺失或 jsonschema 校验失败，按日志提示修配置           |
| 接口报`provider [mysso] is not implemented` | 插件未加载成功（目录名/类名/key 三者不一致；类名拼写；目录下语法错误导致 load_source 失败）                  |
| 启动失败`PLUGIN_CONFIG.default isn't exist` | `default` 指向的插件没加载成功或拼错                                                                       |
| 登录回跳后报"获取用户信息失败"                | `signin`/`user_info` 内调 SSO 接口异常，看 server.log 中堆栈；常见是 redirect_uri 与 SSO 后台登记不一致  |
| 登录成功但提示用户不存在                      | `user_info` 返回的 login_key/login_value 在 CMDB USER 模型中匹配不到：确认字段 ID 是否正确、用户是否已同步 |
| 登出行为不符合预期                            | `sign_out` 返回 `""` 则回 sso 登录页；需跳 SSO 登出端点则返回完整 URL（参考 cas 插件拼 service 参数）    |

---

## 5. LLM 开发引导（根据用户需求生成插件的决策流程）

接到"对接 XX 认证系统"需求时，按以下顺序确认并生成：

**Step 1 — 确认协议类型**：

- 标准 OAuth2/OIDC → 复制 `oauth2` 模板，收集 `login_url / authorization_url / user_info_url / client_id / client_secret / scope / redirect_uri`，非标准点用 §3 的重写表覆盖；
- CAS → 基于 `cas` 插件改 `login_url`（cas server 地址）、`auth_prefix`（默认 `/cas`）、`login_name`（CMDB 字段，默认 `name`）；
- 门户/集成平台免密跳转（URL 带 token） → 基于 `easy_work` 模式：`pre_signin` 返回 `""`，`signin` 解析 token 参数并调对方接口验身份；
- 私有协议 → 基于 `demo` 骨架全新实现四个方法。

**Step 2 — 确认用户身份映射**：三方系统返回的用户唯一标识是什么（工号/邮箱/账号）？映射到 CMDB USER 模型的哪个字段（`name`/`email`/自定义）？用户如何同步进 CMDB？

**Step 3 — 生成插件代码**：遵循 §2 规范（命名三一致、jsonschema 校验、日志、py2.7、仅用内置库）。

**Step 4 — 生成 `setting_custom.py`**：注册插件 + 占位符参数；`default` 按现场是否多 SSO 决定。

**Step 5 — 打 zip**：按 §4.1 结构，附部署说明（§4.2）和验证 curl 命令。

**Step 6 — 回调地址提示**：告知客户在 SSO 后台登记回调地址 `http://<平台域名>/next/sso-auth/authorize`（CAS/SAML），或确认 OAuth2 的 redirect_uri 参数值。

---

## 6. 切面定位与边界

- 本知识描述 sso_adapter 的 **「对接开发态」**：如何新增一个三方 SSO 插件（含统一门户 / 移动端单点登录场景），交付可解压即用的 zip 包。
- 插件部署完成后的 **「运维开启态」**（改 api_gateway `conf.yaml` 开启 `sso-enabled` + 重启 api_gateway/sso_adapter，使无 session 时默认跳单点登录）见同模块 `sso-enable-ops`——先按本篇开发部署插件，再按该篇开启。
- sso_adapter 对外的 8 个 HTTP 接口（`/api/v1/pre-signin/<pk>` 等）若需在 skill 编排中调用，应建 `registry/sso_adapter/` 卡片描述其 **「运行态」**；二者同名对象不同切面，互补参照，非重复。
- 用户身份映射依赖 CMDB USER 模型：login_key 是 USER 模型字段 ID，详见 `concepts/instance-id`、`concepts/cmdb-model`（CMDB 资源建模）。
- sso_adapter 名字服务 `logic.sso_adapter`、端口 8211、网关路径 `/next/api/gateway`，访问方式对照见 `concepts/api-calling`。
