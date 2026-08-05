# EasyOps 平台 API 调用脚本开发指南

> 客户有「平台 API 调用脚本」开发需求时，仿照本目录 `api-samples.py` 开发。
> 该脚本是 EasyOps 三种 API 访问方式的可跑参考实现（已真调验证），覆盖鉴权、URL 拼接、签名、翻页等全部关键点。

## 三种访问方式（与 adapter `endpoint.mode` 一一对应）

EasyOps 同一套后端契约 path，有三种访问方式，URL 拼法与鉴权不同：

| 方式                           | URL 拼法                                                      | 鉴权                                          | 适用场景                                               |
| ------------------------------ | ------------------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------ |
| **内网直连**（默认推荐） | `http://<host>:<port>/<path>`                               | `user`/`org` 请求头（不依赖 cookie/签名） | 在平台内网环境运行的脚本（agent 所在机器、运维跳板机） |
| **网关代理**             | `http://<host>/next/api/gateway/<service><path>`（80 端口） | 前端会话 cookie（`PHPSESSID`）              | 复用浏览器登录态；脚本不宜依赖（cookie 易过期）        |
| **OpenAPI 签名**         | `http://<host>/<app_name>/<path>`                           | AK/SK + HMAC-SHA1 签名                        | 跨网络/第三方系统调用，需向平台申请 AK/SK              |

> 端口与服务（service）的对应关系来自 ENS 路由表，见 `sources/raw/backend/ENS_ROUTING_TABLE.json`。
> 常见：`logic.cmdb.service`→8079、`logic.tool_service`→8181、`logic.flowable_service`→8134。

## 内网直连模式（脚本首选）

最简单稳定，**不依赖 cookie、不需签名**，只要机器能访问平台内网 8xxx 端口：

```python
headers = {
    "user": "defaultUser",          # 内网默认管理员
    "org": "<组织ID>",              # 如 5910；可从 agent 配置自动读
    "Content-Type": "application/json",
}
url = f"http://{host}:{port}/{path.lstrip('/')}"
resp = requests.request(method, url, headers=headers, json=body, timeout=20)
```

- `host`/`org` 留空时，可从 agent 配置 `/usr/local/easyops/agent/conf/conf.yaml`（Windows: `C:\easyOps\agent\conf\conf.yaml`）自动读取：
  - `org = conf['base']['client_id']`
  - `host = conf['command']['server_groups'][0]['hosts'][0]['ip'].split(',')[0]`

## OpenAPI 签名模式（跨网络调用）

需 AK/SK，用 HMAC-SHA1 签名，签名要素（样例 `EasyOpsClient.__signature`）：

1. **URL 参数排序拼接**：`url_param = "".join(f"{k}{params[k]}" for k in sorted(params))`
2. **Content-MD5**（仅 POST/PUT）：请求体 JSON 的 md5 hex
3. **签名字符串**（`\n` 连接 7 段）：
   ```
   method \n uri \n url_param \n content_type \n content_md5 \n request_time \n ak
   ```

   - `uri` 含 app_name 前缀：`/<app_name>/<path>`
   - GET/DELETE 的 `content_type` 为空串
4. **签名**：`hmac.new(sk, string_to_sign, sha1).hexdigest()`
5. **附加 query**：`accesskey`/`signature`/`expires`(=request_time)
6. **端口→app_name 映射**：`PORT_APP_MAP = {8079: "cmdbservice", ...}`，未配置抛错
7. OpenAPI 模式下：GET/DELETE **不发** `Content-Type`；**移除** `org` 头；`Host` 头设 `openapi.easyops-only.com`

## 平台约定（写脚本必知）

- **响应包装**：`{ code, error, message, data }`，`code === 0` 为成功（cmdb.instance 系列字段名略异：`{ code, error, message, data }`）。业务码非 0 不一定 HTTP 报错，需自行判 `code`。
- **翻页**：列表接口返回 `list` + `total` + `page` + `page_size`。样例 `search_instances` 示范自动翻页（`page` 递增直到 `len(items) < page_size`）。
- **count 技巧**：只取总数时 `page_size=1`、`fields=["instanceId"]`，读 `data.total`（见 `count_instances`）。
- **path 参数**：占位符按位置通配，前端 `{modelId}` 与后端 `{instanceId}` 名不同但同位（见 `references/card-schema.md`）。
- **具体 API 方法**：样例把端口直接写在每个方法内（如 `port = 8079`），并注明 `EasyOps API`/`服务`/`端口` 三元组——开发新方法时照此标注，便于追溯。

## 与本 skill 卡片体系的关系

- 本 skill 的 `registry/` 卡片 + `execute_dag` 已封装上述三种方式（adapter `easyops_contract.py` 的 `resolve_endpoint`/`build_auth_headers`），**编排调用走卡片/DAG**，不必手写 HTTP。
- 本样例面向**客户自研脚本**（不在 skill 编排体系内的独立程序）：当客户要写一个脱离 skill 的独立调用脚本（如定时汇总、数据导出、外部集成），仿照 `api-samples.py` 即可，三种鉴权按场景选一。

## 样例脚本清单

| 文件               | 说明                                                                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `api-samples.py` | `EasyOpsClient` 完整实现：内网/OpenAPI 双模式、HMAC-SHA1 签名、自动翻页、CMDB 搜索/计数等具体方法。可独立运行（依赖 `requests`/`pyyaml`）。 |
| `offline_pkg_manager.sh` | 离线三方包管理脚本（通用，与具体包无关）：`download`(联网下载含传递依赖，可指定目标平台) / `install`(离线安装+import自检) / `list`。包目录固定为脚本同级 `offline_pkgs/`。交付带三方依赖的脚本且目标环境离线时，用它下载+随脚本分发。 |

> **开发调用脚本时必复用本文件 `EasyOpsClient` 的通用机制（鉴权头/URL拼接/`code`判定/翻页），不要从头重写**（SKILL.md「脚本开发铁律」）。但 **`EasyOpsClient` 是通用基座，只放调用机制，禁止塞业务接口方法**——工具/工单/CMDB 等具体实体的 path、字段语义、版本选择逻辑写在调用脚本里，借客户端发请求，不要给客户端加 `list_xxx`/`export_xxx`。
>
> ⚠️ **依赖与环境对齐（已知缺口）**：本样例用 `requests`，但 api-console 的 plugin 根 `.venv`（`bootstrap.sh` 装的）只有 `httpx`/`pyyaml`，**未装 `requests`**——直接在 plugin venv 里 `import` 会失败。复用前需先 `uv pip install --python <plugin根>/.venv/bin/python requests` 并更新 `requirements.txt`；或把样例传输层迁到 `httpx`（未做，改动需回归验证）。

## 交付脚本形态规范（独立调用脚本必遵）

向用户交付的「独立调用脚本」（脱离 skill DAG 编排、直接发 HTTP 的程序，如导出/汇总/定时集成/清理）须满足：

1. **独立可执行、自包含**：单文件脚本，不 `import` 项目内任何模块（含本目录 `api-samples.py`、`platforms/`、`skills/`）。客户端传输层（鉴权头 / URL 拼接 / `code` 判定 / 翻页骨架）必须**完整内联本目录 `EasyOpsClient` 类**（连同 `_request` / `__signature` / `__get_host_and_org`），代码物理复制进脚本自身，确保可独立分发、任意环境直接跑。
   - **完整内联，禁止重构骨架**（2026-07-30 实战踩坑修正）：只允许两类改动——① py2/py3 语法兼容改写（f-string → `.format`）；② 删减目标环境确定用不到的 `PORT_APP_MAP` 具体端口映射。**不得**丢弃类封装改成散函数、不得丢弃 `_request` 统一出口、不得丢弃 OpenAPI 签名分支、不得自造 `_get_conn`/`_headers` 等替代函数。骨架与基座保持一致，才能持续吃到基座的真调验证结论。
   - 只复用机制，不污染基座：业务逻辑（具体接口 path / 字段语义 / 版本选择）写在脚本函数里，借内联的 `_request` 发请求，不给内联客户端塞 `list_xxx`/`export_xxx` 等业务方法。
   - **适用边界**：本条针对「独立调用脚本」。**AutoOps 工具包脚本同样完整内联本类**（工具脚本本就在平台内运行，内联无分发障碍），仅其脚本写法默认规范（shebang/编码/u 前缀）见 `modules/autoops_tool/tool-package-dev` §5 Step 3，不在此重复。
2. **不动态引用 api_calling**：不得 `import` 或运行时加载 `knowledge/concepts/api-calling/` 下的文件。本目录是「开发参考」，不是脚本运行时依赖。
3. **默认不使用 argparse / 命令行参数**：可调参数（连接配置、筛选条件、运行开关）一律写在 `if __name__ == "__main__":` 下的常量/字典里，用户改文件后运行。理由：此类脚本面向运维一次性执行，参数项固定且少，命令行反而增加使用门槛。（如确需 CLI 复用/定时调度再酌情加 argparse，属例外。）
4. **可扩展配置抽成结构体**：脚本里「会随业务扩充的可变配置」（如多协议探测、多类鉴权、多目标系统）应抽成模块级 `dict` / `list[dict]` 注册表，新增一类只追加一个配置项、不改主流程逻辑。反例：把每类的判定/处理写成 if/elif 硬编码进主流程，扩充时要动主流程。对照样例 `tmp/collect_readiness_check.py` 的 `PROTOCOL_CONFIGS: list[dict]`（每个协议一个 dict，含 auth_field/default_port/checker/prober，新增协议 append 即可）。

> 对照样例：`tmp/clean_cmdb_model.py`（CMDB 模型清理脚本）即按本规范交付——内联 `EasyOpsClient`、无项目内 import、参数在 `__main__` 下。

## 交付工作流：离线三方包确认（放最后一步，先问用户）

交付脚本若引入了**第三方依赖**（非标准库，如 `openpyxl`/`pysnmp`/`pandas`），且目标运行环境**可能离线**（客户内网、无外网 PyPI），**在交付收尾时主动询问用户是否需要下载离线依赖包**，不要默认下载（多数脚本随环境 pip 装即可，无需离线包）。

**触发条件**：脚本 `import` 了三方库 **且** 脚本将分发到无法联网装依赖的环境。
**执行方式**：问用户「是否下载 X/Y 的离线安装包？」用户确认后再下载，未确认不下载。

**下载+安装方法（确认后，统一用本目录 `offline_pkg_manager.sh`）**：
```bash
# 联网机：下载(含传递依赖)到脚本同级 offline_pkgs/
bash offline_pkg_manager.sh download openpyxl pysnmp
#   含 C 扩展的包(numpy/pandas/cryptography)需按目标平台逐个下：
PKG_PLATFORM=manylinux_2_17_x86_64 PKG_PYVERSION=3.10 \
    bash offline_pkg_manager.sh download numpy pandas
# 把本脚本 + offline_pkgs/ 拷到离线机，安装+自检：
bash offline_pkg_manager.sh install                 # 默认 python3
bash offline_pkg_manager.sh install /path/to/python # 指定解释器
bash offline_pkg_manager.sh list                    # 查看已下载包
```
- 纯 Python 包（无 C 扩展，如 `pysnmp`、`pyasn1`）：下纯 wheel(`py3-none-any`) 即跨平台通用，一份即可。
- **含 C 扩展的包没有"全平台通用"的单一离线包**——wheel 按 `平台(OS)+架构(arm64/x86_64)+Python版本` 编译，必须**按目标平台逐个下载**（用 `PKG_PLATFORM`/`PKG_PYVERSION`）。
- 常用 `PKG_PLATFORM` 标签（pip `--platform` 接受 PEP 600 格式）：`manylinux_2_17_x86_64`(linux x64)、`manylinux_2_17_aarch64`(linux arm)、`macosx_11_0_arm64`(mac arm)、`win_amd64`(win x64)。**注意是 `manylinux_2_17_x86_64` 不是 `x86_64-manylinux2014`**（后者无效，已实测报错）。
- 底层等价命令（脚本内部即这么做）：下载 `pip download <pkg> -d offline_pkgs/ [-i 源] [--only-binary=:all: --platform X --python-version Y]`；安装 `pip install --no-index --find-links=offline_pkgs/ <所有包>`（`--find-links` 把目录当本地索引，依赖自动解析+排序）。
- ⚠️ 若目标平台不确定，与其盲目下多平台，不如**先在目标机 `python3 -c "import sys,platform;print(sys.version_info,platform.machine(),platform.system())"` 探明**再精确下载。
- ⚠️ **三方库 API 必须实测验证，不能凭记忆写**（已踩坑）：`pysnmp` 7.1.x 移除了旧同步 hlapi（`getCmd`），仅提供 asyncio 协程 API（`pysnmp.hlapi.asyncio.get_cmd`，且 `UdpTransportTarget` 需 `await ...create()`）——按 5.x 记忆写的 `from pysnmp.hlapi import getCmd` 在 7.1 必 ImportError。凡探测/调用第三方库的代码，写完立即在目标版本上真跑一遍验证，别只看 import 成功（import 库成功 ≠ 用到的子模块/函数存在）。



## 验证状态

- 样例源自平台真实交付脚本，鉴权与签名算法经 adapter 实现交叉印证（`easyops_contract.py` 三分支与之一致）。
- 内网模式已在本 skill 真调验证（`tool_list`/`tool_lib_search` 走 5.20:8181/8079 返回 200）。
- OpenAPI 签名模式**未持有 AK/SK 实测**（与 adapter `easyops_aksk` 同状态），仿照时建议先用平台提供的 AK/SK 跑通一个简单 GET 再铺开。
