---
name: sso-provider
description: 解析 SSO 服务端对接文档，生成 EasyOps SSO Adapter Provider 插件代码（Python 2.7.18）和对接说明文档，支持 OAuth2/CAS/SAML/自定义协议。
---

# SSO Provider 开发

解析 SSO 服务端对接文档，生成 Provider 插件和对接说明文档。

## 强制规则

**必须遵守，无例外：**

1. 生成的代码必须兼容 Python 2.7.18（使用 `print` 语句、`urllib`、`urlparse`、`except Exception, e` 等 Python 2 语法）
2. Provider 类名必须与目录名完全一致（框架动态加载依赖此规则）
3. 配置变量必须抽取到 `setting_custom.py`，并加中文注释说明
4. 每个方法必须有详细的中文注释

## 前置条件

需要用户提供：

- **provider_name**：小写英文标识符，如 `keycloak`、`adfs`、`ldap_auth`
- **SSO 对接文档**：Markdown/纯文本/URL 格式的对接文档
- **login_key**：CMDB USER 模型中用于唯一标识用户的字段名（默认 `name`）

## 意图识别

进入工作流程之前，先判断用户意图：

1. 检查 `output/` 目录下是否已有 `NAME_sso/` 目录或 `NAME_sso.zip`：
   - **不存在** → 直接进入**新建流程**（步骤 1-6）
   - **已存在** → 询问用户意图：
     1. 从零重新生成（覆盖已有产物）→ 进入**新建流程**（步骤 1-6）
     2. 修改已有插件 → 进入**修改流程**

2. 如果选择修改模式，再确认修改范围（单选）：
   1. 修改配置/字段映射
   2. 修改 Provider 代码逻辑
   3. 文档变更后更新生成

## 工作流程

### 新建流程

```
┌──────────────────────────┐
│ 1. 解析 SSO 对接文档      │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ 2. 分析协议类型和认证流程  │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ 3. 生成 Provider 代码     │ ──→ handlers/providers/NAME/NAME.py
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ 4. 生成配置文件           │ ──→ settings/setting_custom.py
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ 5. 生成对接说明文档       │ ──→ NAME_对接说明.md
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ 6. 打包为 NAME_sso.zip   │
└──────────────────────────┘
```

## 步骤 1：解析 SSO 对接文档

- **Markdown/纯文本**：直接使用 Read 工具读取
- **URL**：使用 `mcp__web_reader__webReader` 工具获取网页内容

解析后需要明确以下信息：

| 信息项          | 说明                                   |
| --------------- | -------------------------------------- |
| 协议类型        | OAuth2/OIDC/CAS/SAML/自定义            |
| 登录端点        | 用户认证的 URL                         |
| Token 端点      | 获取访问凭证的 URL（OAuth2 适用）      |
| 用户信息端点    | 获取用户信息的 URL                     |
| 登出端点        | 注销登录的 URL                         |
| 认证参数        | client_id、client_secret 等            |
| 用户唯一标识字段 | 用于映射到 CMDB 的字段                 |
| 特殊认证逻辑    | 加密、签名、自定义请求头等             |

## 步骤 2：分析协议类型

根据文档内容判断协议类型，决定实现策略：

| 协议类型       | 继承关系           | 参考实现               |
| -------------- | ------------------ | ---------------------- |
| OAuth2/OIDC    | 继承 `oauth2` 类   | `handlers/providers/oauth2/oauth2.py` |
| CAS            | 继承 `Provider`    | `handlers/providers/cas/cas.py`       |
| SAML           | 继承 `Provider`    | 自定义实现             |
| 自定义协议     | 继承 `Provider`    | `handlers/providers/eiac/eiac.py`     |

## 步骤 2.5：确认业务扩展需求（必须询问）

在生成代码之前，**必须向用户确认**是否需要以下业务扩展：

> "SSO 认证成功后，是否需要额外的业务处理？常见扩展：
> 1. 自动注册：用户首次 SSO 登录时，自动在 EasyOps 创建账号
> 2. 用户信息同步：每次登录时同步用户属性（邮箱、手机、昵称等）
> 3. 无需扩展，仅标准 SSO 认证"

根据用户选择，在 `authorize_post_deal` 方法中实现对应逻辑。

### 自动注册扩展的实现要点

当用户选择自动注册时，在 provider 中需要：

1. **引入 EasyOps API 调用能力**：provider 运行在 sso_adapter 容器内，可直接通过内网调用 EasyOps API（端口 8079/8111）
2. **查询用户是否存在**：调用 `POST /v3/object/USER/instance/_search`（端口 8079）
3. **不存在则注册**：调用 `POST /api/v1/users/register`（端口 8111）
4. **配置项**：将 EasyOps host、org 等参数抽取到 `setting_custom.py`

参考代码见 `references/easyops_user_sync.py`，核心方法：
- `EasyOpsClient.search_instance()` — 查询 CMDB 实例
- `EasyOpsClient.register_user()` — 注册 EasyOps 用户
- `EasyOpsClient._request()` — 内网 HTTP 请求封装

**注意**：reference 代码是 Python 3，适配到 provider 时需要转为 Python 2.7.18 语法：
- `str.format()` 替代 f-string
- `except Exception, e` 替代 `except Exception as e`
- `from urllib import urlencode` 替代 `from urllib.parse import urlencode`
- 去掉 type hints

## 步骤 3-4：生成代码和配置

使用模板生成代码：

```bash
# 在 output 目录下执行生成
.venv/bin/python3 scripts/sso_provider_generator.py \
  --name <provider_name> \
  --doc <文档路径或内容> \
  --output output/
```

### 生成物结构

```
NAME_sso.zip
├── settings/
│   └── setting_custom.py          # 配置文件，变量抽取 + 注释
└── handlers/
    └── providers/
        └── NAME/
            ├── __init__.py         # 空文件
            └── NAME.py             # Provider 主文件，详细注释
```

### Provider 接口规范

所有 Provider 必须实现 `base_provider.Provider` 的以下方法：

| 方法                 | 返回值                    | 说明                     |
| -------------------- | ------------------------- | ------------------------ |
| `pre_signin(params)` | `str` 或 `PreSignInRequest` | 返回登录跳转 URL         |
| `signin(params)`     | `dict`                    | 返回 authorization_info  |
| `user_info(authorization_info)` | `(str, str)`     | 返回 (login_key, login_value) |
| `sign_out(authorization_info)`  | `str` 或 `SignOutRequest` | 返回登出 URL             |
| `authorize_post_deal(params)`   | `None`           | 授权后处理（可选）       |
| `custom_auth(params)`           | `bool`           | 自定义密码校验           |
| `sso_global_sign_out(params)`   | `str`            | 全局登出，返回 ticket    |

## 步骤 5：生成对接说明文档

文档必须包含以下章节：

1. **概述** - SSO 系统简介、协议类型
2. **认证流程** - 登录/登出流程描述
3. **配置说明** - setting_custom.py 中每个配置项的说明
4. **部署步骤** - 如何将 NAME_sso.zip 部署到 sso_adapter
5. **接口映射** - SSO 服务端 API 与 Provider 方法的对应关系
6. **注意事项** - 特殊配置、依赖、已知限制

## 步骤 6：打包

```bash
cd output && zip -r NAME_sso.zip settings/ handlers/
```

## 修改流程

修改流程针对已有产物做增量修改，三种场景各自独立执行。所有强制规则对修改流程同样适用。

### 场景 1：修改配置/字段映射

适用场景：改 URL、改密钥、改字段名等。

1. 读取现有 `output/NAME_sso/settings/setting_custom.py`
2. 读取现有 Provider 代码（`output/NAME_sso/handlers/providers/NAME/NAME.py`）中的字段映射部分
3. 根据用户要求直接编辑修改
4. 重新打包（复用步骤 6 的打包命令）

### 场景 2：修改 Provider 代码逻辑

适用场景：改认证逻辑、加新方法、修 bug 等。

1. 读取现有 Provider 代码全文（`output/NAME_sso/handlers/providers/NAME/NAME.py`）
2. 参照 `references/` 下的接口定义和参考实现
3. 根据用户要求直接编辑修改
4. 重新打包（复用步骤 6 的打包命令）

### 场景 3：文档变更后更新生成

适用场景：SSO 服务端接口变更需要重新适配。

1. 解析新的 SSO 文档（复用步骤 1 的解析逻辑）
2. 读取现有 Provider 代码，对比差异
3. 用 `sso_provider_generator.py` 重新生成（覆盖）
4. 重新打包（复用步骤 6 的打包命令）

## 参考资源

- `references/base_provider.py` - Provider 基类接口定义
- `references/oauth2_provider.py` - OAuth2 标准实现参考
- `references/eiac_provider.py` - 自定义协议实现参考
- `references/cas_provider.py` - CAS 协议实现参考
- `references/easyops_user_sync.py` - EasyOps 用户查询/注册 API 调用参考
