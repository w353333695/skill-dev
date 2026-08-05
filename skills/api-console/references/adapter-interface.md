# adapter 接口契约

adapter 让 parse_backend 主干跨平台通用——主干只认 adapter 接口，不耦合任何平台。加新平台 = 加新 adapter 文件，主干不改。

## 设计：主干通用 + adapter 可插拔 + 脚本/LLM 分层

- **主干通用**（`api_console/adapter_base.py` + `api_console/parse_backend.py`）：零平台耦合
- **adapter 耦合各自平台**（合理）：每个 adapter 认识该平台的字段结构
- **脚本抽结构化 + LLM 补语义**：adapter 做确定性结构抽取，LLM 补字段含义等语义

## adapter 接口（Protocol）

每个 adapter 实现 `BackendAdapter` Protocol（`api_console/adapter_base.py`），鸭子类型，**不需要显式继承**：

```python
class BackendAdapter(Protocol):
    name: str

    def detect(self, raw_dir: Path) -> DetectResult:
        """扫描 raw_dir，判断本 adapter 能否处理这批资料。返回置信度。"""
        ...

    def parse(self, raw_dir: Path) -> list[dict]:
        """解析资料，输出 contracts.yaml 片段（list of 单条接口字典）。"""
        ...
```

## Confidence（detect 返回，驱动主干分流）

```python
class Confidence(IntEnum):
    ZERO = 0    # 完全不认识，跳过 adapter
    LOW = 1     # 半结构化（如表格 md），adapter 抽骨架，LLM 补大量语义
    HIGH = 2    # 结构化、字段齐全，adapter 全权处理，LLM 只补 semantic_gaps
```

主干按置信度分流：
- **HIGH**：adapter 全权 parse，LLM 只补 `semantic_gaps`
- **LOW**：MVP-1 报 ParseError（未实现 LLM 回退）
- **ZERO**：跳过 adapter → 若所有 adapter 都 ZERO → 诚实反馈（报告"不支持的格式 + 需提供什么"）

## DetectResult

```python
@dataclass
class DetectResult:
    confidence: Confidence
    reason: str = ""               # 如 "找到 <平台契约文件>.json"
    matched_files: list[str] = None
```

## adapter 放置与发现

**位置**：`platforms/<platform>/sources/backend/adapters/<name>.py`（平台数据，不随 skill 分发）

**发现**：`discover_adapters(adapters_dir)` 扫描目录下所有 `.py`（排除 `__init__.py` / `_` 前缀），用 importlib 加载，找模块级 `Adapter` 实例（或 `Adapter` 类实例化）。

```python
# adapters/<format>.py
class Adapter:
    name = "<format>_contract"
    def detect(self, raw_dir): ...
    def parse(self, raw_dir): ...
```

## parse 输出格式（contracts.yaml 片段）

每条 dict 对齐 `schema/contracts.BackendContract`：

```python
{
    "operation_key": "logic.sys_setting|GET|/api/sys_setting/v1/holiday",  # service|method|normalized_uri 三元组
    "method": "GET",
    "path": "/api/sys_setting/v1/holiday",           # 已归一化（brace style）
    "raw_paths": {"backend": "...", "frontend": "..."},
    "path_source": "backend_contract",
    "path_confidence": "high",
    "service": "logic.sys_setting",
    "port": 8070,                                     # 来自路由表（若有）
    "request": {"fields": [{"name": "st", "type": "string", "desc": "开始时间"}]},
    "response": {"fields": [{"name": "result", "type": "WorkDay[]", "desc": "节假日列表"}]},
    "semantic_gaps": [],                              # 脚本抽不出、需 LLM 补的字段名
    "source_file": "<平台契约文件>.json",
}
```

## 新增 adapter 步骤

1. 在 `platforms/<platform>/sources/backend/adapters/` 新建 `<format>.py`
2. 定义 `class Adapter`，实现 `name` / `detect(raw_dir)` / `parse(raw_dir)`
3. detect 按文件特征（文件名 glob / 内容字段）判断置信度
4. parse 输出上述格式的 list[dict]
5. **主干不改**——discover_adapters 自动发现

### detect 实现要点

- 按文件名 glob 匹配（如 `*CONTRACT*.json` / `*swagger*` / 按平台契约命名约定）
- 大小写双 glob（真实文件名可能大写 `CONTRACT`，样本可能小写）
- 检查关键字段是否存在（按平台契约结构，如 `endpoint`/`serviceName`）

### parse 实现要点

- 无 serviceName / 无 endpoint.uri 的条目跳过（低质量项记入报告，不输出）
- path 经 `path_align.normalize_path` 归一化（colon → brace）
- operation_key 用三元组 `make_operation_key(service, method, normalized_uri)`
- 字段缺 description 的记入 `semantic_gaps`（供 LLM 补）
- ENS/路由表的端口关联：按 service/contract 名匹配

## 参考 adapter

每个已对接平台在其平台包 `platforms/<platform>/sources/backend/adapters/` 下提供自己的契约 adapter 作为该平台的参考实现（具体实现细节见各平台包文档，不在本 skill 主干展开）：
- detect：按平台契约文件特征（如文件名 glob、关键字段）判定，置信度 HIGH
- parse：遍历契约，抽 `endpoint.{method,uri}` / `request.fields` / `response.fields` / `serviceName`，并按平台路由表关联端口
- 低质量条目（无 serviceName / 无 endpoint.uri）跳过并记入报告

## 安全提示

importlib 加载 .py 有代码执行风险。adapter 是平台包内的数据（用户自己放置），可信。但**不要从不受信源拷贝 adapter**。
