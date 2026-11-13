# 监控套件 DebugCollectorJob 调试契约

## 结论

`POST /next/api/gateway/logic.collector_service/api/v1/debug-collector-job` 是前端“创建采集任务”页的调试入口。它会按套件生成临时 `configId=debug-job` 配置，向指定执行主机推送 sampler，并真实调用采集脚本；它不创建正式监控任务，也不能当作无副作用 dry-run。

契约真源见 `../../../easyops-collector-service.yaml` 的 `debug_collector_job.run`，操作流程见 `../../../flows/activate-and-test-monitor-kit.yaml`。

## 请求语义

| 字段 | 语义 |
|---|---|
| `pluginId` | 监控套件ID；服务读取插件定义、`agentType`、脚本与别名指标。 |
| `job.objectId` | 目标模型ID，例如 `HOST`。 |
| `job.instanceIds` | 固定目标实例过滤；服务端生成 `instanceId: {"$in": [...]}`。 |
| `job.metricSetIds` | 参与调试的指标集ID；服务据此查询别名指标。 |
| `job.collectAgent` | 执行主机Agent UUID或可解析值；easyops插件用它推送 sampler。 |
| `job.timeout` | 临时采集超时秒数。 |
| `job.collectCount` | 执行次数；`0`按1次，超过服务端配置上限会被截断，多次执行之间按服务端配置等待。 |
| `job.params` | 任务参数列表，会转换为临时collector config的`params`。`paramType=cmdb`时可引用实例字段，`const`为常量。 |
| `job.collectorParams` | 采集参数列表，会转换为collector config的`collectorParams`；前端抓包常与`params`重复，重复本身不是脚本必需。 |
| `job.instanceMapping` | 实例级映射，转换到collector config的同名字段。 |

## 响应验收

1. 外层HTTP 200只是传输成功；必须检查业务响应`code=0`。
2. 逐项检查`data.list[].resultList[]`：`error`非空即采集失败。
3. `data`是采集脚本stdout原文；成功路径必须能被JSON反序列化，通常是指标数组。
4. 响应`data.params`是实际合并后的任务参数、实例参数与instance mapping，可能包含凭证，日志和文档必须脱敏。
5. 对监控套件，还应校验`data`覆盖预期指标键和维度；只看到接口返回不等于指标可用。

## 错误解释

- `json unmarshal data failed: invalid character 'C' looking for beginning of value`：脚本stdout以`COLLECT_ERROR:`开头，服务端把错误正文当JSON解析失败。应查看后续traceback定位真实异常，不能只改网关参数。
- Python 2.7 `UnicodeDecodeError: 'ascii' codec can't decode byte ...`：脚本在`json.dumps(..., ensure_ascii=False)`中序列化含中文的字节串。Python 2会先按ASCII解码并失败。修复方式是移除`ensure_ascii=False`，使用默认ASCII escape；JSON中文显示为`\\uXXXX`但语义不变。

## 安全边界

- 调用前确认套件ID、目标实例ID和执行主机均在授权范围内。
- 不把Cookie、AK、SK、加密参数值写入文档、日志或普通临时文件。
- 调试失败时保留脱敏后的真实错误和执行链路；HTTP成功、接口`code=0`、`error`为空、指标数据可解析是四层不同验收。
