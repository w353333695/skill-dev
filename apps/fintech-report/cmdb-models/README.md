# CMDB 模型与数据快照（2026-09-03 从 172.30.0.232 org 18832008 导出）

| 文件 | 内容 | 条数 |
|---|---|---|
| report-models.json | 上报系统 6 模型定义（CONFIG/OBJ/TASK/ROLLBACK/CLEANUP/INSTANCE） | 6 |
| fintechdata-models.json | 人行金融元数据全部模型定义（@FINTECHDATA 命名空间，含 attrList/枚举/structs） | 71 |
| report-instances.json | 上报系统实例：config(1) / report-rules(65) / cleanup-rules(0) / tasks-recent2d(14，运行产物近2天) | — |

说明：
- 模型定义含完整 attrList（枚举 regex、struct struct_define、required/unique），重建环境时可直接 object_import
- report-rules 的 objectDefine 字段是上报时用的模型定义快照（脚本 _load_report_objects 的数据源）
- tasks 的 dataFile 路径指向 agent /data/fintech-report-data/<日期>/<taskId>.json（转换原文，不在本快照内）
- v3 retrieve.expression 在该 CMDB 不生效（v1.0.21 教训），查询过滤须走 v2 query
