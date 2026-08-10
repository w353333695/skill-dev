s

---
name: sso-enable-ops
kind: module
module: sso_adapter
tags:
- SSO
- 单点登录
- sso_adapter
- api_gateway
- 开启SSO
- conf.yaml
- feature_flags
- sso-enabled
- intercepted-query-strings
- 组件重启
- easyops-restart
- 运维配置
completeness: full
gaps:
- conf.yaml 完整配置项（附录所称"详细配置文件"）未提供，本知识仅覆盖「开启 SSO」所需的最小配置块
- 重启命令 `easyops restart <部署目录>` 的适用范围（是否所有 EasyOps 版本通用）未逐一核对，以现场 easyops 命令行工具为准
scope:
- 三方 SSO 插件对接完成后，在 api_gateway 上「开启 SSO 总开关」的运维配置
- 使「无 session 时默认跳转单点登录授权」生效
- 需要改 api_gateway conf.yaml 并重启 api_gateway / sso_adapter 两组件的现场操作
related:
- modules/sso_adapter/sso-adapter-plugin-dev（前置：三方 SSO 插件如何开发与部署，本知识是其部署完成后的开启步骤）
- concepts/api-calling（api_gateway / sso_adapter 组件定位与访问方式）
last_verified: ''
note: 'EasyOps 平台 SSO 对接完成后「开启 SSO」的运维操作：改 api_gateway conf.yaml（auth.bootstrap.sys_settings 下
  feature_flags.sso-enabled=true + misc.intercepted-query-strings 加 code），再分别重启 api_gateway 与
  sso_adapter 组件。效果：无 session 时默认跳转单点登录授权。切面定位：本知识描述「运维开启态」（部署后配置），
  modules/sso_adapter/sso-adapter-plugin-dev 描述「对接开发态」（如何做三方 SSO 插件）——同一 sso_adapter 模块的
  前后两个环节，先开发部署插件，再按本篇开启。来源：用户提供的平台部署文档（4.3/4.4 节），未在真实环境执行核对。'
---
# EasyOps 开启 SSO（api_gateway 配置 + 组件重启）

> 面向 LLM 与现场运维的操作指南。前置：三方 SSO 插件已按
> `modules/sso_adapter/sso-adapter-plugin-dev` 完成开发与部署。
> 本篇做「开启 SSO」的最后一步——让平台在**无 session 时默认跳转单点登录授权**。

## 1. 修改 api_gateway 配置文件

在 **`/usr/local/easyops/api_gateway/conf`** 目录下修改 **`conf.yaml`** 配置文件（若不存在则新建）。

向 `conf.yaml` 中添加如下配置：

```yaml
auth:
  bootstrap:
    sys_settings:
      feature_flags:
        sso-enabled: true
      misc:
        intercepted-query-strings:
        - code
```

**字段含义**：

| 配置项                                                         | 取值       | 作用                                                                                                          |
| -------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------- |
| `auth.bootstrap.sys_settings.feature_flags.sso-enabled`      | `true`   | SSO 功能总开关，开启后启用单点登录                                                                            |
| `auth.bootstrap.sys_settings.misc.intercepted-query-strings` | `[code]` | 网关需拦截透传的 query 参数；`code` 是三方 SSO（OAuth2 等）授权回调回跳的授权码，必须放行透传给后续登录流程 |

> 说明：完整 `conf.yaml` 配置项以平台部署文档附录为准；此处仅列「开启 SSO」必需的最小配置块。

## 2. 重启 api_gateway 与 sso_adapter 组件

配置改完后，需重启两个组件使配置生效：

```bash
# 1. 重启 api_gateway 组件
easyops restart /usr/local/easyops/api_gateway

# 2. 重启 sso_adapter 组件
easyops restart /usr/local/easyops/sso_adapter
```

> `easyops restart <组件部署目录>` 为 EasyOps 平台服务管理命令，参数是组件的部署目录。

## 3. 效果

完成上述配置并重启后：

- **无 session 时，访问平台默认跳转单点登录授权页**（不再落本地账号密码登录页）；
- 浏览器经三方 SSO 授权后携带 `code` 回跳平台，网关透传该授权码完成登录换 session。

## 4. 操作顺序速查（端到端）

1. 三方 SSO 插件开发 + 部署 → 见 `modules/sso_adapter/sso-adapter-plugin-dev`（§4 现场部署步骤）。
2. 改 api_gateway `conf.yaml` 加 `sso-enabled: true` + `intercepted-query-strings: [code]` → 本篇 §1。
3. 重启 `api_gateway` 与 `sso_adapter` → 本篇 §2。
4. 浏览器端到端验证：退出登录 → 访问平台 → 自动跳三方 SSO → 授权登录 → 回跳平台成功。

## 5. 切面定位与边界

- 本知识描述 sso_adapter 模块的 **「运维开启态」**：三方 SSO 对接部署完成后，如何在 api_gateway 上开启 SSO 使默认跳转生效。
- 前置的 **「对接开发态」**（如何新增一个三方 SSO 插件、交付 zip 包）见 `modules/sso_adapter/sso-adapter-plugin-dev`——先开发部署插件，再按本篇开启，二者是同一模块的前后两个环节，互补参照，非重复。
- api_gateway / sso_adapter 的组件定位与访问方式（名字服务、端口、网关路径）见 `concepts/api-calling`。
- 本篇为确定性运维步骤，来源是平台部署文档；未在真实环境逐条执行核对，现场操作请以实际部署路径与 easyops 命令为准。
