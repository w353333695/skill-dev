# 产物目录结构（output-format）

## 平台包（platforms/<platform>/）

长期资产，可分发（auth/ 不入库）。

```
platforms/<platform>/
├── manifest.yaml                       # 平台元信息（多环境，gitignore：含凭证不入库）
├── manifest.example.yaml               # 模板（入库，首次接入从此复制）
├── sources/
│   ├── frontend/                       # recorder 抓包产物（归一）
│   │   ├── openapi/<模块>-openapi.yaml
│   │   └── guides/<流程>/              # 操作指引 + _assets
│   └── backend/
│       ├── raw/                        # 原始后端资料（gitignore，体积大）
│       ├── parsed/contracts.yaml       # parse_backend 产出（标准化后端文档）
│       ├── adapters/                   # 平台 adapter（<format>_contract.py 等）
│       └── gateway-rules.yaml          # path 剥离兜底规则
├── registry/                           # 卡片库（register_cards 产出）
│   ├── _index.yaml                     # 全局索引（按 module 分组）
│   └── <module>/<name>.yaml            # 单张卡片
├── knowledge/                          # 领域知识（业务语义，与卡片分离）
│   ├── concepts/                       # 全局概念（instanceId/值类型/CMDB模型）
│   └── modules/<module>/               # 模块内字段细节
└── auth/                               # 旧形态鉴权落盘（gitignore，敏感；新形态写回 manifest）
    ├── cookies.json
    └── meta.json
```

### manifest.yaml（多环境结构）

支持同一平台多套环境（prod / dev / test …），由 `manifest_loader.load_manifest(platform_dir, env)` 统一加载并扁平化成旧形态 dict（adapter / execute_dag / invoke_card 零改动）。`default_env` 指定不传 `--env` 时的默认环境。真实 `manifest.yaml` 含 cookie / aksk 凭证故不入库，仓库只留 `manifest.example.yaml` 模板，首次接入从模板复制并填值。

```yaml
name: <platform>
# 默认环境（未指定 --env 时用）
default_env: prod
environments:
  prod:
    host: <YOUR_HOST>                            # 占位符，用户替换（内网 IP / 域名）
    gateway_base: http://<YOUR_HOST>/<gateway 路径前缀>
    auth:
      session_cookie:
        cookie: "<EXTRACT_VIA_extract_auth>"     # 跑 `extract_auth --env prod` 自动填充（勿手填）
      # 其余鉴权块（如内网 user/org 头、aksk 签名）按平台 adapter 需要补充
    call_policy:
      default_mode: <由 adapter 决定的调用模式字符串>   # 不传时 adapter 用其内置默认
    auth_source: tmp/profiles/<YOUR_HOST>/       # extract_auth 的 cookie profile 来源（recorder 录制的浏览器 profile）
  # 按需加 dev / test 等环境，结构同上
```

> 旧形态（无 `environments`，顶层即扁平 `host` / `auth` / `call_policy` / `auth_source`）仍兼容：`load_manifest` 当单环境直接用，`extract_auth` 落 `auth/cookies.json`（旧行为）。新形态下 cookie 文本级写回 `environments.<env>.auth.session_cookie.cookie`。

### contracts.yaml（parse_backend 产出）

list of BackendContract，每条含 operation_key/method/path/raw_paths/path_source/path_confidence/service/port/request.fields/response.fields/semantic_gaps/source_file。详见 `references/adapter-interface.md`。

### registry/_index.yaml

按 module 分组的卡片索引（LLM 选卡片用它，两层检索）：

```yaml
modules:
  - name: domain_model
    desc: 领域模型管理
    tags: [领域模型]
    cards:
      - {name: searchDomainModel, side_effect: read, method: POST,
         path: /api/flowable_service/v1/domain_model/_search,
         tags: [...], summary: 查询领域模型列表,
         file: domain_model/search.yaml}
      - ...
```

**一致性约束**：_index.yaml 每条 card 的 name/method/path/side_effect 必须与对应卡片文件一致（register_cards commit 时校验）。

### registry/<module>/<name>.yaml

单张卡片，字段详见 `references/card-schema.md`。

## 临时产物（tmp/orchestrate/）

### 编排执行产物

```
tmp/orchestrate/<时间戳>/
├── plan.json          # LLM 生成的 DAG
├── execution.json     # 每步执行记录（req/resp/抽出值/状态/耗时）
└── result.json        # 最终聚合结果
```

### 卡片注册草稿

```
tmp/orchestrate/register/<module>/
└── _draft.yaml        # extract 产出 + LLM 补语义 + 用户 review
```

commit 后该 draft 可清理（卡片已入 registry/）。

## .gitignore 要点

- `tmp/`、`output/`、`platforms/*/auth/`、`platforms/*/sources/raw/`、`platforms/*/manifest.yaml` 不入库
- `platforms/*/manifest.example.yaml` 入库（模板，占位符无凭证）
- `platforms/` 的其他部分（sources/frontend/sources/backend/{parsed,adapters,gateway-rules}/registry）入库（可分发资产）
