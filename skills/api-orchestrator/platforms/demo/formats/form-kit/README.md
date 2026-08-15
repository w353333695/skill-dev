# form-kit —— ITSM 系统表单合法性校验（前端规则复刻）

form-validator.py：EasyOps ITSM「系统表单」（老表单体系，formId + formDefinition JSON 字符串，
useFormBuilder=false）的合法性校验器。14 条规则 1:1 复刻自前端源码。

- 权威源：`data/sources/frontend/ITSM/itsc-form-management/2.46.2/bootstrap-mini.b0847bacc23ee16d.json`
  （storyboard 声明式编排：`forms.general-*` 控件 required/pattern/maxLength +
  `meta.functions#validateProviderArgs` + events 重名/调试结果条件校验）
- 入口：CLI `python3 form-validator.py check-form|check-field|check-datasource|check-debug-result|check-version ...`；
  库 `from form_validator import validate_form_meta, validate_field_key, validate_ds_name, validate_ds_unique, validate_provider_args, validate_debug_result, validate_version`
- 规则清单（rule_id 与前端挂载点对应，详见文件头注释）：
  · A 表单元信息（新建/编辑弹窗）：A1 名称必填 / A2 名称 ^[\s\S]{1,20}$ / A3 分类必填 /
    A4 表单ID ^[a-zA-Z]\w{0,29}$（已有表单进入只读跳过）/ A5 说明 ≤500
  · B 标准字段：B1 唯一标识必填 / B2 ^[a-zA-Z0-9][.a-zA-Z0-9_-]{0,34}$
  · C 数据源：C1 名称 ^(?!数字)[中文英文数字_]+$ / C2 名称不与 dataList 重名（排除自身 id）/
    C3 provider 参数按 9 种 type 校验（cmdb-detail/count/count-multi/list/group/columndb/olap/http/dynamic）/
    C4 数据转换结果必须是对象或数组
  · D 版本发布：D1 版本号必填 / D2 ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ / D3 说明 ^[^\s]{1,20}$
- 领域适配点（为何在 platforms 不在 skill）：规则文案 i18n key、正则与 maxLength 值、
  数据源 9 种 type 的必填项语义——全部是 EasyOps 前端版本相关的事实，换部署/换版本须重对源。
- 使用方：编排挡建/改表单（flows/build-form.yaml）后自检；对存量表单做体检。
- 限制：不含「表单设计器画布内部」校验（控件树结构合法性）——那部分在编译后的
  itsm-widgets npm 包里，不在 bootstrap storyboard 中。
