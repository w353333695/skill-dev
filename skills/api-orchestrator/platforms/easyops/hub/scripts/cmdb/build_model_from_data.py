#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_model_from_data.py —— 从 list[dict] 数据反推 CMDB 模型设计并写入目标环境

功能：
    1. 读入一份 list[dict] 数据（样例数据/全量数据皆可）
    2. 逐字段推断 CMDB 属性类型（int/float/bool/str/ip/date/datetime/enum/enums/
       arr/struct/structs/json），支持开关控制推断深度
    3. 生成 CmdbObject 设计 JSON（属性 id/name/分类 tag、view.attr_order 排序、
       attr_category_order 分组顺序、show_key 显示键、required 必填）
    4. 落盘到脚本同级目录/<objectId 主名小写>.json（本地留档，可人工审后再导）
    5. 写入目标环境：先 /v2/object_import_check 预检（可关），再 /v2/object_import（upsert）
    6. 可选（CREATE_INSTANCES=True）：把同一份数据作为实例批量 upsert 进新模型

使用：
    改下方「配置区」变量（数据、模型元信息、环境地址），直接 python 运行：
        python3 build_model_from_data.py
    不支持命令行参数——按需改配置区变量即可（约定如此设计）。

运行环境：Python 3.9+，仅标准库，无第三方依赖。

离线兼容：
    无任何第三方依赖、无公网访问；目标环境地址从配置区 / EASYOPS_* 环境变量读取，
    内网直连 CMDB 后端（org/user header 鉴权，免 cookie）。

类型推断规则（自洽）：
    对每个字段收集全部行的值，按固定优先级链逐一尝试，命中即定：
      bool → int → float → ip → datetime → date → time(归 datetime) →
      enum → structs → struct → enums(同质文本列表) → arr → str
    每个候选类型的判定条件都是「该字段全部非空值满足该形态」——只要有一个值
    不满足就落到更宽松的候选，最终兜底 str。因此推断出的类型一定装得下全部
    样例值（写入实例不会被类型校验拒绝；枚举 regex 除外——新值需先更新模型）。

局限性（重要，使用前必读）：
    1. 枚举判定是启发式：低基数（≤enum_threshold）≠ 真枚举——自由文本恰好样本少
       时会被误判为 enum，之后写入新文本值会被 regex 校验拒绝。生产建议枚举推断
       只做初稿、人工核对 value.regex，或 TYPE_CONFIG.enum=False 关掉、或把字段
       加入 enum_exempt 例外名单。
    2. 日期/时间识别基于固定格式清单（DATE_FORMATS/DATETIME_FORMATS/TIME_FORMATS），
       无法识别 "2026年9月1日"、"Sep 1st 2026"、毫秒时间戳数字等——会退化成
       str/int。CMDB 无独立 time 类型：纯时刻（HH:MM[:SS]）默认判 str（TYPE_CONFIG.time
       ="str"，值原样可写回）；设为 "datetime" 强归 datetime 时，纯时刻值写实例
       会被后端拒绝（实测 133503）；设为 "off" 则按通用规则落到 enum/str。
       "02:00:00-06:00:00" 这类区间串不识别为时间。
    3. int/float 判定只认 Python 原生数值类型；"01"、"1.5" 这类数字样式字符串
       一律保真判 str（避免前导零丢失/隐式转换语义错位），不猜强转。
    4. struct/structs 要求所有 dict 的 key 集合完全一致，不一致退化为 json/arr；
       struct_define 不支持嵌套 struct——子字段里的 dict 退化为 json。
    5. 类型以「本次给的数据」推断：数据不全时字段形态可能漏（某字段偶发 null
       会被跳过不参与判定；样例外的新形态写入时会报类型错误）。数据越全推断越准。
    6. 枚举值列表取自样例去重；之后写入含新枚举值的实例需先更新模型 regex。
    7. 不建关系（relation_list）：平铺 dict 推不出模型间关联，关系需人工设计。
    8. 字段名须自身合法（字母数字下划线）；含特殊字符的字段请先在数据侧改名为
       snake_case 再喂给本脚本（CMDB 属性 id 惯例如此）。
    9. 【实测】属性类型落库后不可变更（133113 cannot change property`s type）：
       重复跑本脚本且推断类型与已固化模型不一致时，import 对该属性报错、
       实例写入也失败。处置：确认新推断正确后删模型重建（forceDelete=true），
       或把 TYPE_CONFIG 调回与线上一致的推断再跑。
"""
import json
import logging
import os
import re
import ssl
import sys
from datetime import datetime
from urllib.parse import quote as urlquote
from urllib.request import Request, urlopen

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger('build_model')

# =============================================================================
# 配置区（按需修改，直接运行）
# =============================================================================

# ---- 1. 待分析数据（list[dict]；或指向 JSON 文件的路径 str）----
SAMPLE_DATA = [
    {"name": "web-01", "ip": "192.168.1.10", "cpu_cores": 8, "mem_gb": 32.5,
     "os_type": "centos", "env": "prod", "is_virtual": True,
     "created_at": "2026-08-01 10:00:00", "maintain_window": "02:00:00",
     "labels": ["front", "cache"], "nic": {"name": "eth0", "mtu": 1500, "speed_gbps": 10},
     "disks": [{"slot": 1, "size_gb": 960, "type": "ssd"}, {"slot": 2, "size_gb": 1920, "type": "hdd"}],
     "remark": None},
    {"name": "db-01", "ip": "10.0.0.5", "cpu_cores": 16, "mem_gb": 128,
     "os_type": "ubuntu", "env": "prod", "is_virtual": False,
     "created_at": "2026-08-02 11:30:00", "maintain_window": "03:30:00",
     "labels": ["db"], "nic": {"name": "bond0", "mtu": 9000, "speed_gbps": 25},
     "disks": [{"slot": 1, "size_gb": 3840, "type": "nvme"}],
     "remark": "核心库"},
]  # type: list

# ---- 2. 模型元信息（无法从数据推导，人工给定）----
OBJECT_ID = "DEMO_SERVER@EASYOPS"   # 模型 ID，约定 NAME@NAMESPACE
OBJECT_NAME = "演示服务器"           # 模型中文名
CATEGORY = "应用资源.服务器"         # 点分多级分类
ICON = "fa fa-server"               # 图标 class（空串=不设）
MEMO = "由 build_model_from_data.py 自动生成"

# ---- 3. 属性命名 / 分组 / 排序 ----
# 属性 id → 中文名；未登记的字段用字段名本身。
FIELD_NAME_MAP = {
    "name": "名称", "ip": "IP 地址", "cpu_cores": "CPU 核数", "mem_gb": "内存(GB)",
    "os_type": "操作系统", "env": "环境", "is_virtual": "是否虚拟机",
    "created_at": "创建时间", "maintain_window": "维护时间点",
    "labels": "标签", "nic": "网卡", "disks": "磁盘列表", "remark": "备注",
}
# 属性分类（分组 tag）：未登记的字段归入 DEFAULT_TAG。
FIELD_TAG_MAP = {
    "name": "基本信息", "ip": "基本信息", "env": "基本信息",
    "cpu_cores": "规格", "mem_gb": "规格", "nic": "规格", "disks": "规格",
    "os_type": "系统", "created_at": "系统", "maintain_window": "系统",
    "is_virtual": "其他", "labels": "其他", "remark": "其他",
}
DEFAULT_TAG = "其他"                # 未登记分组的字段归这里
# 分组展示顺序（view.attr_category_order）——决定表单里分组出现的先后；未列出的排最后。
TAG_ORDER = ["基本信息", "规格", "系统", "其他"]
# 属性展示顺序（view.attr_order）：数据字段名列表；未列出的按数据首次出现顺序缀后。
ATTR_ORDER = ["name", "ip", "env", "cpu_cores", "mem_gb", "os_type",
              "is_virtual", "labels", "nic", "disks", "created_at", "maintain_window", "remark"]
# 实例列表显示键（view.show_key）。
SHOW_KEY = ["name", "ip"]
# 必填属性（数据字段名列表，写入 model.attrList[].required）。
REQUIRED_FIELDS = ["name"]

# ---- 4. 类型推断开关（True=启用该项推断；False=该项不识别、退化为更宽松类型）----
TYPE_CONFIG = {
    "ip": True,            # IPv4 字符串 → type=ip
    "date": True,          # YYYY-MM-DD 等 → type=date
    "datetime": True,      # YYYY-MM-DD HH:MM:SS（含 ISO8601/T 分隔）→ type=datetime
    # time（HH:MM[:SS] 纯时刻）三态开关——CMDB 无独立 time 类型，且实测后端
    # datetime 字段拒绝纯时刻值（133503 属性值不符合定义）：
    #   "off"       不特殊处理，落到 enum/str 按通用规则判
    #   "str"       【默认】判 str：值原样可写回（保真、自洽）
    #   "datetime"  强归 datetime：仅当你的数据后续都会补全成完整日期时间才用，
    #               纯时刻值写实例时会被后端拒绝
    "time": "str",
    "enum": True,          # 低基数字符串 → type=enum（单选）
    "enums": True,         # 低基数同质文本列表 → type=enums（多选）
    "struct": True,        # key 集合一致的 dict → type=struct（单结构体）
    "structs": True,       # 元素 key 集合一致的 dict 列表 → type=structs（结构体数组）
    "int": True,           # 整数 → type=int
    "float": True,         # 浮点 → type=float
    "field_prefix": "",    # 新属性 id 统一加的前缀（如 "_"；空=不加。建新模型通常留空）
    "enum_threshold": 8,   # 枚举判定阈值：去重值数 2..该值 才判 enum/enums
    # 例外名单：这些字段永远不判 enum（即使低基数）——name 类标识字段几乎必然
    # 持续新增值，判 enum 会让后续实例写入全被 regex 拒绝。
    "enum_exempt": ["name"],
}

# ---- 5. 目标环境（离线内网直连；也可用环境变量覆盖）----
EASYOPS_ORG = os.environ.get("EASYOPS_ORG", "8888")
EASYOPS_USER = os.environ.get("EASYOPS_USER", "easyops")
CMDB_BACKEND_URL = os.environ.get("EASYOPS_CMDB_BACKEND_URL", "http://172.30.0.148:8079")
VERIFY_TLS = False                  # 内网自签证书不校验
REQUEST_TIMEOUT = 30                # 秒

# ---- 6. 行为开关 ----
DRY_RUN = False                     # True=只分析+落盘 JSON，不调任何写接口
WRITE_MODEL = True                  # False=不写模型（仅分析落盘）
IMPORT_CHECK = True                 # True=写前先调 /v2/object_import_check 预检
CREATE_INSTANCES = False            # True=建模型后把 SAMPLE_DATA 作为实例写入（默认关）
INSTANCE_KEY_FIELDS = ["name"]      # 实例 upsert 唯一键（模型普通属性 id，不加 prefix 写法）
JSON_OUTPUT_DIR = None              # None=脚本同级目录；或指定绝对路径

# =============================================================================
# 以下为实现，一般无需修改
# =============================================================================

IPV4_RE = re.compile(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$')

# 时间/日期格式（strptime 格式串）。time 只认「单点时刻」，区间串(02:00-06:00)不认。
TIME_FORMATS = ['%H:%M:%S', '%H:%M']
DATE_FORMATS = ['%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d']
DATETIME_FORMATS = [
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M',
    '%Y/%m/%d %H:%M:%S', '%Y/%m/%d %H:%M',
]

# struct 子字段推断配置：关闭 enum/struct 递归——struct_define.type 不支持嵌套
# struct，子字段上枚举证据也更弱（每 key 值少），保 str/基础类型更稳。
SUB_TYPE_CONFIG = dict(
    TYPE_CONFIG,
    enum=False, enums=False, struct=False, structs=False,
)


def _try_strptime(value, fmts):
    """value 是否匹配 fmts 中任一格式。非 str / 空串 / 不匹配一律 False。"""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return False
    for f in fmts:
        try:
            datetime.strptime(v, f)
            return True
        except ValueError:
            continue
    return False


def _is_ipv4(value):
    """IPv4 合法性：四段 0..255。非 str 一律 False。"""
    if not isinstance(value, str):
        return False
    m = IPV4_RE.match(value.strip())
    if not m:
        return False
    try:
        return all(0 <= int(g) <= 255 for g in m.groups())
    except ValueError:
        return False


def _to_str(value):
    """值 → 文本：str 原样返回，bytes 按 utf-8 解码（urllib 原始字节场景的防御）。"""
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return str(value)


def _all_of(values, pred):
    """全部值都满足 pred（values 非空才可能 True；空列表 False——无证据不定型）。"""
    if not values:
        return False
    return all(pred(v) for v in values)


def _unique_ordered(values):
    """去重保序（first-seen order）。"""
    seen = set()
    out = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def infer_field_type(field, values, cfg):
    """对一个字段的值集合推断 CMDB 类型。

    返回 {'type': ...}，enum/enums 附 'regex'（值数组），struct/structs 附
    'struct_define'，datetime 若由 time 推断而来附 '_note'='time-only'。
    决策链与自洽性说明见模块 docstring「类型推断规则」。
    """
    nonnull = [v for v in values if v is not None]

    # --- bool（Python bool 是 int 子类，必须先于 int 判）---
    if _all_of(nonnull, lambda v: isinstance(v, bool)):
        return {'type': 'bool'}

    # --- int（cfg.int=False 时跳过、落到 float/str）---
    if cfg.get('int', True) and _all_of(
            nonnull, lambda v: isinstance(v, int) and not isinstance(v, bool)):
        return {'type': 'int'}

    # --- float（int+float 混合也归 float；cfg.float=False 落到后面按字符串判）---
    if cfg.get('float', True) and _all_of(
            nonnull, lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)):
        return {'type': 'float'}

    # --- 纯字符串形态 ---
    texts = [v for v in nonnull if isinstance(v, (str, bytes))]
    if texts and len(texts) == len(nonnull):
        sv = [_to_str(v) for v in texts if _to_str(v).strip() != '']
        if sv and len(sv) == len(texts):
            if cfg.get('ip') and _all_of(sv, _is_ipv4):
                return {'type': 'ip'}
            if cfg.get('datetime') and _all_of(sv, lambda x: _try_strptime(x, DATETIME_FORMATS)):
                return {'type': 'datetime'}
            if cfg.get('date') and _all_of(sv, lambda x: _try_strptime(x, DATE_FORMATS)):
                return {'type': 'date'}
            time_cfg = cfg.get('time', 'str')
            if time_cfg == 'datetime' and _all_of(sv, lambda x: _try_strptime(x, TIME_FORMATS)):
                # 强归 datetime：纯时刻值写实例会被后端拒（实测 133503），慎用
                return {'type': 'datetime', '_note': 'time-only（注意：纯时刻值写实例会被后端拒绝）'}
            if cfg.get('enum') and field not in cfg.get('enum_exempt', []):
                uniq = _unique_ordered(sv)
                if 2 <= len(uniq) <= cfg.get('enum_threshold', 8):
                    return {'type': 'enum', 'regex': uniq}
            # 数字样式字符串不猜强转、保真判 str（局限性 3）
            return {'type': 'str'}

    # --- 列表 ---
    lists = [v for v in nonnull if isinstance(v, list)]
    if lists and len(lists) == len(nonnull):
        flat_items = [item for lst in lists for item in lst]
        # structs：元素全是 dict 且 key 集合一致
        if cfg.get('structs') and flat_items and _all_of(flat_items, lambda x: isinstance(x, dict)):
            key_sets = [frozenset(item.keys()) for item in flat_items]
            if all(ks == key_sets[0] for ks in key_sets):
                return {'type': 'structs',
                        'struct_define': _struct_define(flat_items)}
            # key 不齐 → arr（CMDB arr 可存任意，不设 regex）
            return {'type': 'arr', '_note': 'structs-keys-mismatch'}
        # enums：元素全是非空文本且低基数
        if cfg.get('enums') and flat_items and _all_of(
                flat_items, lambda x: isinstance(x, (str, bytes)) and _to_str(x).strip() != ''):
            elem = [_to_str(x) for x in flat_items]
            uniq = _unique_ordered(elem)
            if len(uniq) == 1 or 2 <= len(uniq) <= cfg.get('enum_threshold', 8):
                return {'type': 'enums', 'regex': uniq}
        # 其余列表（数字列表/混合/空元素列表）→ arr
        return {'type': 'arr'}

    # --- dict（单结构体）---
    dicts = [v for v in nonnull if isinstance(v, dict)]
    if dicts and len(dicts) == len(nonnull):
        if cfg.get('struct'):
            key_sets = [frozenset(d.keys()) for d in dicts]
            if all(ks == key_sets[0] for ks in key_sets):
                return {'type': 'struct', 'struct_define': _struct_define(dicts)}
        # key 不齐 → json（自由结构）
        return {'type': 'json'}

    # --- 混合形态（int+str、str+list 等）→ str 兜底 ---
    return {'type': 'str'}


def _struct_define(dicts):
    """从 dict 样本生成 struct_define（子字段按首次出现顺序，类型递归推断一层）。"""
    key_order = []
    for d in dicts:
        for k in d.keys():
            if k not in key_order:
                key_order.append(k)
    define = []
    for key in key_order:
        sub_values = [d.get(key) for d in dicts if key in d]
        sub = infer_field_type(key, sub_values, SUB_TYPE_CONFIG)
        entry = {'id': key, 'name': FIELD_NAME_MAP.get(key, key), 'type': sub['type']}
        if sub['type'] in ('enum', 'enums') and sub.get('regex'):
            entry['regex'] = sub['regex']
        define.append(entry)
    return define


# ---- 模型设计生成 ----
def build_cmdb_object(data, object_id, object_name, category):
    """从 list[dict] 数据生成完整 CmdbObject 设计 dict（结构对齐 /v2/object_import）。"""
    if not data:
        raise ValueError('SAMPLE_DATA 为空，无从推断')

    # 字段首次出现顺序 + 每字段的全行值收集（不同行字段不齐时，缺失按 None=跳过）
    field_order = []
    columns = {}
    for row in data:
        if not isinstance(row, dict):
            raise ValueError('数据元素必须是 dict，收到: %r' % (row,))
        for k in row:
            if k not in columns:
                columns[k] = []
                field_order.append(k)
    for row in data:
        for k in columns:
            columns[k].append(row.get(k))

    prefix = TYPE_CONFIG.get('field_prefix', '')
    attr_list = []
    for field in field_order:
        inferred = infer_field_type(field, columns[field], TYPE_CONFIG)
        value = {'type': inferred['type']}
        if inferred['type'] in ('enum', 'enums') and inferred.get('regex'):
            value['regex'] = inferred['regex']
        if inferred['type'] in ('struct', 'structs') and inferred.get('struct_define'):
            value['struct_define'] = inferred['struct_define']
        attr = {
            'id': prefix + field,
            'name': FIELD_NAME_MAP.get(field, field),
            'required': 'true' if field in REQUIRED_FIELDS else 'false',
            'tag': [FIELD_TAG_MAP.get(field, DEFAULT_TAG)],
            'value': value,
        }
        if inferred.get('_note'):
            # 推断备注（仅摘要展示用，序列化/导入前会剥离，不进模型 schema）
            attr['_note'] = inferred['_note']
        attr_list.append(attr)

    # 属性排序：ATTR_ORDER 列出的按列出顺序，未列出的按数据首次出现顺序缀后
    ordered = [f for f in ATTR_ORDER if f in columns]
    rest = [f for f in field_order if f not in ATTR_ORDER]
    attr_order_ids = [prefix + f for f in ordered + rest]

    # 分组顺序：TAG_ORDER 列出的在前，未列出的分组按首次出现缀后
    seen_tags = []
    for f in field_order:
        t = FIELD_TAG_MAP.get(f, DEFAULT_TAG)
        if t not in seen_tags:
            seen_tags.append(t)
    tag_seq = ([t for t in TAG_ORDER if t in seen_tags]
               + [t for t in seen_tags if t not in TAG_ORDER])

    obj = {
        'objectId': object_id,
        'name': object_name,
        'category': category,
        'attrList': attr_list,
        'view': {
            'attr_category_order': tag_seq,
            'attr_order': attr_order_ids,
            'show_key': SHOW_KEY,
            'visible': True,
        },
    }
    if ICON:
        obj['icon'] = ICON
    if MEMO:
        obj['memo'] = MEMO
    return obj


# ---- HTTP（纯 stdlib；org/user header 鉴权，离线内网直连）----
class EasyOpsHttp(object):
    """EasyOps 内网直连客户端。无第三方依赖、无公网访问。"""

    def __init__(self, base_url, org, user, timeout=30, verify=False):
        self.base_url = str(base_url).rstrip('/')
        self.org = str(org)
        self.user = str(user)
        self.timeout = timeout
        self.verify = verify
        self.ssl_ctx = None if verify else ssl._create_unverified_context()

    def _headers(self):
        return {'Content-Type': 'application/json', 'org': self.org, 'user': self.user}

    def request_json(self, method, path, body=None):
        url = self.base_url + path
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        req = Request(url, data=data, headers=self._headers())
        req.get_method = lambda: method
        kwargs = {'timeout': self.timeout}
        if url.lower().startswith('https'):
            kwargs['context'] = self.ssl_ctx
        fobj = urlopen(req, **kwargs)
        try:
            raw = fobj.read()
        finally:
            fobj.close()
        try:
            return json.loads(raw)
        except ValueError:
            return raw


def _error_body(e):
    """从 HTTPError 榨出响应体（EasyOps 业务错误 JSON 在 body 里）。"""
    try:
        return e.read().decode('utf-8', 'replace')
    except Exception:
        return str(e)


def import_model(http, model_json, check_only=False):
    """调 /v2/object_import_check（预检不落库）或 /v2/object_import（upsert 落库）。"""
    path = '/v2/object_import_check' if check_only else '/v2/object_import'
    return http.request_json('POST', path, {'object_list': [model_json]})


def import_instances(http, object_id, datas, keys):
    """POST /object/{object_id}/instance/_import（批量 upsert 实例）。"""
    path = '/object/%s/instance/_import' % urlquote(object_id)
    return http.request_json('POST', path, {'keys': keys, 'datas': datas})


# ---- 主流程 ----
def load_data():
    """SAMPLE_DATA 为 list 直接返回；为 str 时按 JSON 文件路径读（顶层须为数组）。"""
    if isinstance(SAMPLE_DATA, list):
        return SAMPLE_DATA
    if isinstance(SAMPLE_DATA, str):
        with open(SAMPLE_DATA, 'r') as f:
            loaded = json.load(f)
        if not isinstance(loaded, list):
            raise ValueError('JSON 文件顶层必须是数组（list[dict]）: %s' % SAMPLE_DATA)
        return loaded
    raise ValueError('SAMPLE_DATA 既不是 list 也不是 JSON 文件路径')


def main():
    data = load_data()
    log.info('读入数据 %d 条', len(data))

    model = build_cmdb_object(data, OBJECT_ID, OBJECT_NAME, CATEGORY)

    # 落盘前剥离 _note（仅摘要展示用），保证落盘 JSON 是干净的 CmdbObject schema
    clean_model = json.loads(json.dumps(model, ensure_ascii=False))
    for a in clean_model['attrList']:
        a.pop('_note', None)

    # 落盘：脚本同级目录/<objectId 主名小写>.json
    out_dir = JSON_OUTPUT_DIR or os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(out_dir, ('%s.json' % OBJECT_ID.split('@')[0]).lower())
    with open(out_path, 'w') as f:
        json.dump(clean_model, f, ensure_ascii=False, indent=2)
    log.info('模型设计 JSON 已落盘: %s', out_path)

    # 推断摘要
    log.info('推断结果摘要（%d 属性）:', len(model['attrList']))
    for a in model['attrList']:
        v = a['value']
        extra = ''
        if v['type'] in ('enum', 'enums'):
            extra = ' regex=%s' % (v.get('regex'),)
        elif v['type'] in ('struct', 'structs'):
            extra = ' 子字段=%s' % ([d['id'] for d in v.get('struct_define', [])],)
        note = a.get('_note')
        log.info('  - %-18s (%s) → %-8s%s%s  [分组: %s]',
                 a['id'], a['name'], v['type'], extra,
                 ('（注: %s）' % note) if note else '', a['tag'][0])

    if DRY_RUN:
        log.info('DRY_RUN=True，止步于分析+落盘，不调写接口。')
        return 0

    if not WRITE_MODEL and not CREATE_INSTANCES:
        return 0

    http = EasyOpsHttp(CMDB_BACKEND_URL, EASYOPS_ORG, EASYOPS_USER,
                       timeout=REQUEST_TIMEOUT, verify=VERIFY_TLS)

    if WRITE_MODEL:
        if IMPORT_CHECK:
            log.info('import_check 预检中 …')
            try:
                chk = import_model(http, clean_model, check_only=True)
            except Exception as e:
                log.error('[import_check] 请求异常: %s | %s', e, _error_body(e))
                return 2
            log.info('import_check 返回: %s', json.dumps(chk, ensure_ascii=False)[:2000])
            if isinstance(chk, dict) and chk.get('code') not in (0, None, '0'):
                log.error('[import_check] 预检失败: %s', json.dumps(chk, ensure_ascii=False))
                return 2

        log.info('object_import 写入模型 …')
        try:
            resp = import_model(http, clean_model, check_only=False)
        except Exception as e:
            log.error('[import_model] 写入失败: %s | %s', e, _error_body(e))
            return 3
        if not isinstance(resp, dict):
            log.error('[import_model] 非 JSON 响应: %r', resp)
            return 3
        log.info('object_import 返回 code=%s', resp.get('code'))
        for r in ((resp.get('data') or {}).get('import_result') or []):
            log.info('  模型 %s is_create=%s code=%s msg=%s',
                     r.get('objectId'), r.get('is_create'), r.get('code'), r.get('message'))
            for a in (r.get('attr_list_result') or []):
                if a.get('code') not in (0, None, '0'):
                    log.warning('  ! 属性 %s(%s): %s', a.get('id'), a.get('name'), a.get('message'))
        if resp.get('code') not in (0, None, '0'):
            log.error('[import_model] 写入失败: %s', json.dumps(resp, ensure_ascii=False)[:2000])
            return 3

    if CREATE_INSTANCES:
        log.info('CREATE_INSTANCES=True，写入实例 %d 条 …', len(data))
        # 字段名对齐：模型属性加了 field_prefix 时，实例数据同步加
        prefix = TYPE_CONFIG.get('field_prefix', '')
        if prefix:
            datas = [{prefix + k: v for k, v in row.items() if v is not None}
                     for row in data]
        else:
            datas = [{k: v for k, v in row.items() if v is not None} for row in data]
        keys = [prefix + k for k in INSTANCE_KEY_FIELDS]
        try:
            resp = import_instances(http, OBJECT_ID, datas, keys)
        except Exception as e:
            log.error('[import_instances] 实例写入失败: %s | %s', e, _error_body(e))
            return 4
        if not isinstance(resp, dict):
            log.error('[import_instances] 非 JSON 响应: %r', resp)
            return 4
        d = resp.get('data') or {}
        log.info('实例写入 insert=%s update=%s failed=%s',
                 d.get('insert_count'), d.get('update_count'), d.get('failed_count'))
        for item in (d.get('data') or []):
            log.warning('  ! 失败明细: %s', json.dumps(item, ensure_ascii=False)[:500])
        if resp.get('code') not in (0, None, '0') or d.get('failed_count'):
            return 4

    log.info('完成。模型 JSON: %s', out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
