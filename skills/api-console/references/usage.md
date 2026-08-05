# 使用说明（usage）

详细使用、FAQ、常见错误排查。

## 前置条件

1. 跑过 `bash skills/api-console/scripts/setup.sh`（装 api-console CLI 到 `~/.local/bin`，一次）
2. **调用前 cd 到用户工作目录**（项目根），产物落该目录的 tmp/、platforms/

## 典型完整流程（首次对接某平台）

```bash
cd <用户工作目录>

# 0. 装依赖（首次）
bash skills/api-console/scripts/setup.sh

# 1. 录制前端（用 browser-recorder，产出 openapi + 登录态）
#    详见 browser-recorder skill

# 2. 归集后端资料到 raw/backend/（用户提供）
mkdir -p platforms/<platform>/sources/raw/backend
cp <后端资料> platforms/<platform>/sources/raw/backend/

# 3. 解析后端资料
api-console parse-backend \
  --platform <platform> \
  --in platforms/<platform>/sources/raw/backend \
  --out platforms/<platform>/sources/backend/parsed/contracts.yaml

# 4. 注册卡片（extract → LLM 补语义 → review → commit）
api-console register-cards extract \
  --platform <platform> \
  --openapi platforms/<platform>/sources/frontend/openapi/<模块>-openapi.yaml \
  --backend-contracts platforms/<platform>/sources/backend/parsed/contracts.yaml \
  --out tmp/orchestrate/register/<module>/_draft.yaml
# （LLM 补语义 + 用户 review _draft.yaml）
api-console register-cards commit \
  --platform <platform> --in tmp/orchestrate/register/<module>/_draft.yaml

# 5. 提取鉴权
api-console extract-auth --platform <platform>

# 6. 编排执行（LLM 读 SKILL.md，LLM 生成 DAG → verify → execute）
#    由 LLM 在对话中驱动，非命令行
```

## FAQ

### Q: cookie 失效怎么办？
执行时报 401/302→login。重跑：
```bash
api-console extract-auth --platform <platform>
```
若 recorder profile 也过期，先用 browser-recorder 重新录制（刷新登录态），再重提 cookie。

### Q: parse_backend 报"不支持的格式"？
adapter detect 置信度 0。检查：
- raw/ 下是否有 adapter 能识别的文件（各平台契约文件命名规则见该平台 adapter）
- adapter 文件是否在 `platforms/<platform>/sources/backend/adapters/`（不是 skill 下）
- adapter 是否有模块级 `Adapter` 实例/类

### Q: 注册的卡片 path_source 都是 frontend_raw/low？
后端 contracts.yaml 未匹配上前端 openapi。检查：
- 前端 openapi 的 gateway_path 能否被 gateway-rules.yaml 剥离
- 后端契约的 service 是否与前端 gateway 里的 service 名一致（如都带 `logic.` 前缀）
- path 参数名差异（{modelId} vs {instanceId}）会导致含参 path 降级（已知限制，不阻塞）

### Q: verify_dag 报"未知卡片"？
DAG 里的 card name 与 registry/_index.yaml 里的 name 不一致。检查卡片是否已 commit 入库。

### Q: execute_dag 报"锚点提取失败"？
卡片 outputs 锚点的 jsonpath 与实际响应不符（卡片过时）。重新 review 卡片，修正 outputs 锚点。

### Q: foreach 报"不是数组"？
foreach 引用的上游 bind 不是数组。检查上游 output.from 锚点是否返回数组（如 list_full 返回 list，但若是 detail 返回单对象则不能 foreach）。

### Q: 表达式被拒"非法表达式形式"？
`${}` 表达式不在 4 种合法形式内。详见 `references/dag-schema.md`。常见错误：
- `${s1}`（缺 bind）→ 改 `${s1.fields}`
- `${s1.a.b.c}`（层级过深）→ 重新设计数据流
- `${join(x)}`（缺 sep）→ 改 `${join(x, ',')}`

## 常见错误定位

| 现象 | 可能原因 | 定位 |
|---|---|---|
| parse_backend 失败 | adapter 未发现 / 格式不支持 | 看 stderr 的 ParseError reason |
| 卡片 path 不对 | path 对齐失败 | 看 card.path_source/path_confidence + contracts.yaml |
| verify 失败 | DAG 结构错 | 看 VerifyReport.errors |
| execute 401 | cookie 失效 | 重提 extract_auth |
| execute 业务码错 | 请求参数错 | 看 execution.json 的 req/resp |
| execute 提取空 | 锚点过时 | 看 card.outputs vs 实际响应 |

## 清理

编排执行产物在 `tmp/orchestrate/<时间戳>/`，执行成功且用户确认结果后可清理。卡片注册草稿在 `tmp/orchestrate/register/`。遵循 recorder 范式：删前确认。
