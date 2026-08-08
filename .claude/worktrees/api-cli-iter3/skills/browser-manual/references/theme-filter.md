# 主题过滤判定准则（步骤 4）

读 `<out>/requests.json`（聚合接口组，每组 `{endpoint, observations, merged_schema, sample_statuses, linked_seq}`）+ 用户 `--theme`，逐组判与主题相关性，写：

- `requests.theme.json`：仅相关组（结构同 requests.json 子集，每组加 `relevance_note` 一句话理由）。
- `接口清单.md`：可读清单（method/url_template/字段 schema/与主题关系）。

## 判定准则

1. **强相关（保留）**：`url_template` 或 `merged_schema` 字段语义直接服务于主题。
   - 例：theme=「资产导入」→ 保留 `POST /import`、`POST /upload`、`GET /import/tasks`、含 `assetId/uploadStatus/batch` 字段者。
2. **强无关（丢弃）**：用户菜单/通知/权限/审计/通用分页元接口与主题无关。
   - 例：theme=「资产导入」→ 丢 `GET /user/menu`、`GET /notifications`、`GET /permissions`。
3. **边界（保留并标「待确认」）**：无法仅凭 schema 判断（如通用 `GET /list`、`POST /save`）。
   - 在 `relevance_note` 标注「待确认」，不擅自丢弃——宁多勿少，避免漏掉主题接口。
4. **去第三方/静态**：export 期内置 filter 已排除；此处不重复处理。

## 输出格式

`requests.theme.json` 是数组；元素沿用 requests.json 的组结构，追加 `relevance_note`：

```json
{
  "endpoint": {"method": "POST", "url_template": "/api/assets/import", "param_path": []},
  "observations": 1,
  "merged_schema": {"type": "object", "fields": {"batchId": {"type": "string"}}},
  "relevance_note": "资产导入提交接口，强相关"
}
```

`接口清单.md` 用表格，每行一个保留接口：

```markdown
| 方法 | 接口 | 字段(节选) | 与主题关系 |
| --- | --- | --- | --- |
| POST | /api/assets/import | batchId, file | 强相关：导入提交 |
| GET | /api/import/tasks | status, total | 强相关：导入任务查询 |
| GET | /api/list | id, name | 待确认：通用列表，可能承载导入结果 |
```
