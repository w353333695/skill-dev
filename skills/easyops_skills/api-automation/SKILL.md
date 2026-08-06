---
name: api-automation
description: EasyOps 平台自动化操作工具。通过 uwin.py 脚本执行 CMDB 模型/实例管理、API 查询与签名等操作（能力随 uwin.py 动态扩展）；生成独立 API 调用脚本（内网/OpenAPI 双模式）并打包为工具包。
---
# EasyOps 自动化操作

通过 uwin.py 脚本执行 EasyOps CMDB 自动化操作，包括 API 查询、模型管理、实例管理等。

## 动态能力获取

**skill 能力随 uwin.py 脚本自动扩展。** 每次使用前，先获取最新能力列表：

```bash
python scripts/uwin.py --list-func
```

根据返回的函数列表确定可用操作，不要假设固定的函数集。

## 网络连接处理（重要）

uwin.py 默认从 agent 配置自动读取 host 和 org，无需手动指定。

**如果执行时遇到网络错误（连接超时、服务不可达等）：**

1. 立即停止操作
2. 告知用户网络问题
3. 要求用户：
   - 检查网络连接
   - 或提供可达的 host 和 org 参数

## 调用方式

```bash
python scripts/uwin.py -f <函数名> -a '<JSON参数>'
```

**参数说明：**

- `-f`：函数名
- `-a`：JSON 格式的参数字典

**示例：**

```bash
# 查询 API（使用默认 host/org）
python scripts/uwin.py -f get_api_desc -a '{"api_name": "PostSearchV3"}'

# 指定 host 和 org（网络问题时使用）
python scripts/uwin.py -f get_api_desc -a '{"api_name": "PostSearchV3"}' --host 192.168.1.100 --org 12345
```

## 常用方法

```bash
# 查看uwin.py有哪些方法
python scripts/uwin.py --list-func

# 根据名称查询 API
python scripts/uwin.py -f get_api_desc -a '{"api_name": "PostSearchV3"}'1888

# 根据契约全名查看 API，全名中带有符号@
python scripts/uwin.py -f get_api_desc -a '{"fullContractName": "easyops.api.data_exchange.olap@QueryV2"}'


# 根据描述查询 API
python scripts/uwin.py -f get_api_desc -a '{"description": "实例搜索"}'
python scripts/uwin.py -f get_api_desc -a '{"detail": "实例搜索"}' 

# 根据url查询 API
python scripts/uwin.py -f get_api_desc_by_url -a '{"url": "http://....."}'

# 获取服务端口 serviceName 从查询API的结果中找，格式类似：logic.flowable_service
python scripts/uwin.py -f get_service_port -a '{"serviceName": "logic.flowable_service"}'
```

```

```

## 注意事项

1. **网络问题优先处理**：遇到连接错误时，先解决网络问题再继续
2. **危险操作确认**：删除、清理操作前先用 dry_run 预览
3. **批量操作分批**：大量数据使用 batch_size 分批处理
4. **参数格式**：-a 参数必须是有效的 JSON 字符串
5. 各类输出入默认放在项目根目录，不要放在.下任意目录里
6. **API 查询策略**：先在线查询，网络不可达时自动回退离线数据（`data/`）

## 离线模式

支持从本地 JSON 文件查询 API 信息和服务端口，无需在线环境。

### 离线数据位置

```
data/
├── FLOW_BUILDER_API_CONTRACT@EASYOPS.json  # API 契约数据
└── ENS_ROUTING_TABLE.json                   # 服务路由表（端口映射）
```

### 查询策略（先在线后离线）

1. **先尝试在线查询**（默认行为，不加 `--local-data`）
2. **网络不可达时回退离线**：追加 `--local-data data/`

```bash
# 在线查询（默认）
python scripts/uwin.py -f get_api_desc -a '{"api_name": "PostSearchV3"}'

# 在线失败后，使用离线数据回退
python scripts/uwin.py -f get_api_desc -a '{"api_name": "PostSearchV3"}' --local-data data/

# 离线查询服务端口
python scripts/uwin.py -f get_service_port -a '{"serviceName": "logic.flowable_service"}' --local-data data/

# 离线按描述模糊查询
python scripts/uwin.py -f get_api_desc -a '{"description": "实例搜索"}' --local-data data/

# 离线按契约全名精确查询
python scripts/uwin.py -f get_api_desc -a '{"fullContractName": "easyops.api.cmdb.instance@PostSearchV3"}' --local-data data/
```

### 数据文件要求

- 文件命名：`{模型ID}.json`，如 `FLOW_BUILDER_API_CONTRACT@EASYOPS.json`、`ENS_ROUTING_TABLE.json`
- 文件格式：JSON 数组，每个元素为一条 CMDB 实例记录
- 数据来源：可通过在线环境的 `search_instance` 方法导出
- 数据更新：定期从在线环境重新导出以保持数据新鲜度

### 工作机制

- `--local-data` 目录中存在对应模型的 JSON 文件时，直接本地查询
- 本地没有对应文件时，仍走在线 API（需有网络环境）
- 纯离线可用：指定 `--local-data` 后即使无网络配置也可使用查询功能
- 查询语法兼容：支持 `$like`、`$and`、`$or`、`$exists`、嵌套字段（如 `endpoint.uri`）等 CMDB 查询语法

## 新增自动化能力

### 流程

1. 用户提供api的curl信息
2. 根据网址获取api详细信息
3. 根据获取api详细信息的serviceName获取服务的端口
4. 给uwin.py添加类方法，必须有Docstring，参数说明，如果api详细信息里没有说明，则参考curl请求构建

```python
    def list_operation_log(self, start_time: str, end_time: str,
                           page_size: int = 100) -> list:
        """
        查询操作日志（自动翻页返回所有数据）

        EasyOps API: ListOperationLog
        服务: logic.notify

        :param start_time: 开始时间，格式 2006-01-02 15:04:05
        :param end_time: 截止时间
        :param page_size: 每页条数，默认100，最大3000
        :return: 所有符合条件的操作日志列表
        :rtype: list
        """
        port = 8069 # serviceName获取服务的端口
        all_data = []
        page = 1
        # 接口是列表类型的循环获取所有数据
        while True:
            params = {
                "page": page,
                "pageSize": page_size,
                "start_time": start_time,
                "end_time": end_time,
            }
            resp = self._request("GET", "/operation/log", port=port, params=params)
            data = resp.json().get("data", {})
            items = data.get("list", [])
            all_data.extend(items)
            total = data.get("total", 0)
            logger.info(f"已获取 {len(all_data)}/{total} 条操作日志")

            if len(all_data) >= total or not items:
                break
            page += 1

        return all_data
```

5. 验证方法可用性

```shell
python scripts/uwin.py -flist_operation_log -a '{"start_time": "2026-01-01 00:00:00","end_time": "2026-01-02 00:00:00"}'
```

6. 更新openapi.yaml，同一个app的api接口放在对应api_list里，示例：

```yaml
app_route:
  - app_name: cmdbservice # 根据serviceName.replace('.','').replace('logic.','').replace('data.','')
    service_name: logic.cmdb.service # serviceName
    port: 8079 # 服务端口
    api_list:
      # search_instance - 搜索实例
      - frequency: 120
        method: POST
        uri: /v3/object/:objectId/instance/_search
```

## 生成API调用脚本

### 流程

1. 用户提供api名称|描述|url|curl请求获取api信息
2. 先看uwin.py是否已有方法，如有则跳到第4步，否则先根据用户提供的信息获取api详细信息
3. 根据获取api详细信息的serviceName获取服务的端口
4. **判断脚本类型**，选择对应生成模式：
   - **模式A：纯API调用脚本** —— 仅需封装一个或几个API调用，无复杂业务逻辑
   - **模式B：综合自动化脚本** —— 需要结合数据处理、文件读写、多系统调用、流程编排等复杂逻辑
5. **严格** 仿照脚本模版 `examples/api_call_template.py` 生成脚本，不需要支持命令行执行
6. 询问用户是否需要打包工具包，需要则使用 `scripts/pack_tool.py` 打包

### 核心设计原则

**`EasyOpsClient` 只做一件事：HTTP 请求封装。**

- ✅ 应该放在 `EasyOpsClient` 中的：`_request`、签名、具体的 API 方法（如 `get_model_info`、`import_instance`）
- ❌ 不应该放在 `EasyOpsClient` 中的：数据处理、文件读写、条件判断、流程编排、其他系统调用

业务逻辑（数据处理、流程编排等）一律写在 `main()` 或自定义函数中，通过 `client.xxx()` 调用 API。

### ⚠️ 模板遵从规则（必须严格遵守）

**必须完全复制模板中的以下代码，不得自行改写或简化：**

1. **`__init__` 方法**: 参数签名 `(host, org, user, ak, sk)`，从 agent 配置读取 host/org 的逻辑
2. **`__get_host_and_org` 方法**: 从 agent 配置文件读取 host/org 的完整实现
3. **`__signature` 方法**: OpenAPI HMAC-SHA1 签名的完整实现
4. **`_request` 方法**: 参数签名 `(method, path, port, **kwargs)`，支持内网/OpenAPI 双模式的完整实现

**允许且应该扩展的部分：**

- 在 `EasyOpsClient` 的 `_request` 方法之后添加具体的 API 方法（带完整 Docstring）
- 在 `main()` 函数中编写业务逻辑
- 在 `main()` 之外添加自定义的数据处理函数、工具函数
- 引入标准库或第三方库（如 `pandas`、`csv`、`datetime` 等）

**两种模式的代码结构：**

**模式A（纯API调用）—— 最简结构：**

```python
class EasyOpsClient:
    # ... 保持模板中的核心方法不变 ...

    def new_api_method(self, ...):
        """新API方法"""
        port = 8080
        ...


def main():
    client = EasyOpsClient()
    result = client.new_api_method(...)
    print(result)


if __name__ == "__main__":
    main()
```

**模式B（综合自动化）—— 分层结构：**

```python
import csv
from datetime import datetime

class EasyOpsClient:
    # ... 保持模板中的核心方法不变 ...

    def search_instances(self, object_id: str, query: dict) -> list:
        """查询实例"""
        port = 8079
        ...

    def import_instances(self, object_id: str, data_list: list, keys: list) -> dict:
        """批量导入实例"""
        port = 8079
        ...


def read_source_data(file_path: str) -> list:
    """读取源数据（CSV/Excel/数据库等）"""
    ...


def transform_data(raw_data: list) -> list:
    """数据清洗、转换、映射"""
    ...


def validate_data(data: list) -> tuple[list, list]:
    """数据校验，返回（合法数据, 非法数据）"""
    ...


def write_report(results: dict, output_path: str):
    """写入执行报告"""
    ...


def main():
    """编排完整自动化流程"""
    client = EasyOpsClient()

    # 1. 读取数据
    raw = read_source_data("input.csv")

    # 2. 转换
    transformed = transform_data(raw)

    # 3. 校验
    valid, invalid = validate_data(transformed)

    # 4. 调用 EasyOps API
    result = client.import_instances("HOST", valid, keys=["hostname"])

    # 5. 输出报告
    write_report(result, "report.json")


if __name__ == "__main__":
    main()
```

**禁止事项：**

- ❌ 不得使用 `EnvManager` 或其他自定义环境管理类
- ❌ 不得自行编写 `_request`、签名等核心方法
- ❌ 不得修改 `__init__` 参数签名
- ❌ 不得省略 OpenAPI 签名支持
- ❌ 不得把数据处理、流程编排等业务逻辑塞进 `EasyOpsClient`

## 参考资源

- `references/openapi-signature.md` - OpenAPI 签名算法
- `examples/api_call_template.py` - 脚本模板（类结构 + main() 入口）
- `examples/integrated_automation_example.py` - 综合自动化脚本示例（API + 数据处理 + 文件读写）

### 工具脚本

- **`scripts/pack_tool.py`** - 工具包打包脚本
- **`scripts/uwin.py`** - easyops自动化相关工具
