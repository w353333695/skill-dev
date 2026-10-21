# openapi-kit —— EasyOps openapi 网关接入格式包

> 归档说明（2026-10-21 建）：openapi 网关接入是独立能力形态（放行配置/签名/调用），
> 归 openapi-kit，与 alert-kit/dashboard-kit 平级。此前网关知识散在 systems.yaml
> easyops-cmdb.runtime.openapi_gateway_config（命令式配置规则），本包补齐格式与调用样例。

## 一、api_gateway/conf/openapi.yaml（放行配置）

结构（用户 2026-10-19 提供样例 + .24 实测）：

```yaml
app_route:
  - app_name: <网关 app key>            # 后端服务 app（如 cmdbservice/flowable_service/msgsender）
    service_name: logic.<服务名>        # ens 服务名
    api_list:
      - frequency: 120                  # 限频次/分
        method: POST|GET|PUT|DELETE
        uri: /path/{param}              # 路径参数用 {xx} 形态
```

要点：
- 每个 uri 逐条放行；未放行 → nginx 405 或网关 `404 no matched uri`（`get servcie addr error,app:<app>,err:no matched uri`）
- 🔴uri 必须放【对应 app 的 api_list】下（按 uri 的服务归属，不按调用顺序追加）——放错 app 块
  （如 flowable 的 /api/flowable_service/... 放到 msgsender 下）则该 app 匹配不到 uri 依然 404（2026-10-21 用户纠偏实测）
- 改完按网关重启/生效流程
- app key 与前端网关路由名对应（前端 `/next/api/gateway/<app_key>/<uri>`；openapi 网关 `/<app_name>/<uri>`）

## 二、调用（AK/SK HMAC-SHA1 签名）

- 入口：内网网关 IP + `Host: openapi.easyops-only.com`（勿走公网域名入口）
- 签名（与 api-cli easyops_openapi.go / sdk/easyops_client.py 一致）：
  `string_to_sign = method \n path \n sorted(k+v) \n content_type \n content_md5 \n ts \n ak`，
  query 注入 accesskey/signature/expires
- 权限：AK/SK 主体对目标资源有权限（否则 130600 permission denied，后台授权）
- 完整客户端样例：`tmp/openapi-tool/openapi_client_demo.py`（py2/3 stdlib，5 用例：查实例/发工单/查工单详情/通知配置/发通知）

## 三、已验证 uri 清单（.24）

| app_name | uri | 说明 |
|---|---|---|
| cmdbservice | POST /v3/object/{objectId}/instance/_search | CMDB 实例查询 |
| cmdbservice | GET /object/{objectId} | 模型详情 |
| flowable_service | POST /api/flowable_service/v2/process_instance | 发起工单（StartProcessInstanceV2；formData 必须 JSON 字符串） |
| flowable_service | GET /api/flowable_service/v1/ticket/{instanceId} | 工单详情（前端 GetTicketDetail 同款；返回聚合体 ticket/serviceInstance/process/processVersion/progress/allowedOp/userInfoMap） |
| flowable_service | GET /api/flowable_service/v1/service_instance/{instanceId} | 服务详情 |
| msgsender | GET /api/v2/message_sender/configs | 通知配置 |
| msgsender | POST /api/v1/message_sender/send_message | 发送通知（method=config.name） |

注：命令式配置规则全集（405 排查顺序/网关路由机制）仍在 `systems.yaml#easyops-cmdb.runtime.openapi_gateway_config`——本包与它互补（格式样例 + 已验证 uri 注册表 + 调用样例指针）。
