# form-kit —— ITSM 系统表单合法性校验（前端规则复刻）

form-validator.py：EasyOps ITSM「系统表单」（老表单体系，formId + formDefinition JSON 字符串，
useFormBuilder=false）的合法性校验器。规则 1:1 复刻自前端源码。

- 权威源（两处）：
  · 表单管理页（元信息/标准字段/数据源/版本）：`data/sources/frontend/ITSM/itsc-form-management/2.46.2/bootstrap-mini.b0847bacc23ee16d.json`
    （storyboard 声明式编排：`forms.general-*` 控件 required/pattern/maxLength +
    `meta.functions#validateProviderArgs` + events 重名/调试结果条件校验）
  · 表单设计器保存链（容器/控件/属性面板）：**运行中前端包（已归档）**
    `data/sources/frontend/ITSM/index.e5622707.js`（= bricks/itsc-form-management/1.100.7 编译产物，
    2026-08-15 实拉自 `https://<前端>/next/sa-static/-/bricks/itsc-form-management/1.100.7/dist/index.e5622707.js`）
    · getFormData 三层链：validateSection（容器 12 规则）→ validateField（控件 9 规则，
      跳过 cmdb实例操作容器）→ validateAllForm（属性面板 schema：标题必填/空格/≤20 +
      枚举数据源三项 + numberSetting 数值顺序 + Tab 页签两项）
    · 🔴后端【不拦任何设计器规则】（2026-08-15 探针实测：label>20 / modelField 重复/空 /
      枚举无数据源等 update 全部 code=0 放行）——绕过前端直调 API 的编排必须自跑 E 类校验兜底，
      否则带病数据能落库但前端打不开/保存不了
- 入口：CLI `python3 form-validator.py check-form|check-field|check-datasource|check-debug-result|check-version|check-controls ...`；
  库 `from form_validator import validate_form_meta, validate_field_key, validate_ds_name, validate_ds_unique, validate_provider_args, validate_debug_result, validate_version, validate_designer_form`
- 规则清单（rule_id 与前端挂载点对应，详见文件头注释）：
  · A 表单元信息（新建/编辑弹窗）：A1 名称必填 / A2 名称 ^[\s\S]{1,20}$ / A3 分类必填 /
    A4 表单ID ^[a-zA-Z]\w{0,29}$（已有表单进入只读跳过）/ A5 说明 ≤500
  · B 标准字段：B1 唯一标识必填 / B2 ^[a-zA-Z0-9][.a-zA-Z0-9_-]{0,34}$
  · C 数据源：C1 名称 ^(?!数字)[中文英文数字_]+$ / C2 名称不与 dataList 重名（排除自身 id）/
    C3 provider 参数按 9 种 type 校验（cmdb-detail/count/count-multi/list/group/columndb/olap/http/dynamic）/
    C4 数据转换结果必须是对象或数组
  · D 版本发布：D1 版本号必填 / D2 ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ / D3 说明 ^[^\s]{1,20}$
  · E 设计器保存链（前端包反编译）：
    E-S1~S12 容器：非空/标题必填/标题≤20/id必填/id格式^(?![0-9]+$)[a-zA-Z0-9_@]+$/id唯一/
       事件触发对象/事件脚本/SLA计算字段（条件触发）/table禁多模型/cmdb操作容器模型+展示列
    E-F1~F9 控件：标题必填/标题≤20（用户实测命中）/id必填/id格式（同容器）唯一/
       MODALSELECT事件脚本/脚本必填入参/CMDBSELECT排序至多1个/单排序须选字段
    E-P2~P9 属性面板：Tab页签≥1个/页签标题 ^\S{1,128}$/
       🔴枚举类数据源路径按控件类型严格区分（SELECT/MULTIPLESELECT/CHECKBOX→extraProps.items；
       RADIO/CASCADER/MODALSELECT→extraProps.options——迁移把 RADIO 选项写成 items 会报
       『的数据源未配置，请添加』，2026-08-15 用户实测命中）：
       P4 数据源非空 / P5 每项 label+value trim 非空 / P6 value 无重复 /
       P7~P9 numberSetting 数值顺序（step≥0/min≤default≤max）
- 领域适配点（为何在 platforms 不在 skill）：规则文案 i18n、正则与长度值、数据源 9 种 type
  的必填项语义、前端包版本（1.100.7）——全部是 EasyOps 部署版本相关事实，换版本须重对源。
  归档：data/sources/frontend/ITSM/index.e5622707.js（换版本后重新归档并重对规则）。
- 使用方：编排挡建/改表单（flows/build-form.yaml）后自检；对存量表单做体检。
- 前端包重拉配方（换版本时）：入口 HTML `GET /next/itsc-form-management/main.js`（实为 HTML）
  → 取 UNION_APP_ROOT + BOOTSTRAP_UNION_FILE → 拉 union bootstrap 取 brickPackages.filePath
  → `GET /next/sa-static/-/<filePath>`（带 PHPSESSID cookie）。
