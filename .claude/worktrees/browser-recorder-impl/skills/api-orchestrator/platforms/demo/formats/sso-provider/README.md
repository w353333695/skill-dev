# sso-adapter 标准 provider 实物范本

sso-adapter（logic.sso-adapter:8211, py2）自带的标准协议 provider **完整实现**，作为交付新 provider 的实物参照。
范式说明见 `objects.yaml#sso_provider.api_behavior.two_paradigms`；交付流程见 `flows/build-sso-provider.yaml`。

## ⚠️ 这就是实物——不要再探测 sso-adapter 源码

本目录的 `.py` 是 sso-adapter 标准 provider 的**真实可运行代码**（从 sso-adapter 源码提炼，随 skill 包分发）。
交付新 provider 时，**仿照这里的实现写**，不要去 `find`/读 sso-adapter 安装目录或源码仓库——那些不在 skill 包里，探测是死路。

## 两个范本（对应两范式）

| 范本 | 范式 | 适用 | 文件 |
|---|---|---|---|
| **`oauth2/`** | 范式① 模板方法 | 客户协议是标准/近似 OAuth2-OIDC（code 换 token + user_info 端点） | `oauth2.py`（308 行，基类把流程拆成大量小 hook，非标协议只重写个别 hook） |
| **`cas/`** | 范式② 直白 | 客户协议是 CAS，或私有协议/集成平台跳转（自己管 client） | `cas.py` + `cas_client.py`（721 行，4 必填方法直写） |

## 怎么用

1. 客户给协议 → 按 `build-sso-provider.yaml` step1 判定接近哪个范式。
2. **复制对应范本目录**（`oauth2/` 或 `cas/`）→ 改名 `<新provider名>/`（四位一体约定：目录名=文件名=类名=PLUGIN_CONFIG key）。
3. 改实现：
   - 范式①（oauth2）：多数情况只改 `PLUGIN_CONFIG`（端点/字段映射）；非标处重写个别 hook（如 `parse_user_info` 改用户字段）。
   - 范式②（cas）：仿 `cas.py` + `cas_client.py`，4 必填方法按客户协议直写。
4. 配置写 `setting_custom.py` 的 `PLUGIN_CONFIG.<新provider名>`（优先级最高）。
5. 打包（provider 代码 + 配置片段 + 安装说明）。

## 代码约束（仿写时遵守）

- **py2 兼容**（运行时 `/usr/local/easyops/python/bin/python`）：`urllib`/`urlparse`（非 `urllib.parse`）、`print x`、`except Exception, e`、`unicode` 判定。
- **四位一体**：目录名=文件名=类名=PLUGIN_CONFIG key，全小写。
- **配置走 `PLUGIN_CONFIG`**：`__init__` 里 `self._config = PLUGIN_CONFIG.get("<name>")` + jsonschema 校验，不硬编码。
- **`user_info` 返回的 login_value 必须是 cmdb 唯一用户凭证**（如 name/sub）。
- 依赖：`requests`、`jsonschema`（sso-adapter 运行环境已装）。

完整契约见 `objects.yaml#sso_provider`（7 方法入参/返回/调用时机）+ `#sso_provider_config`（配置项）。
