# -*- coding: utf-8 -*-
"""
esayops应用配置修改（EasyOps 应用/组件配置修改工具）

功能：修改本机 EasyOps 组件配置文件（默认 agent 的 conf.yaml；conf_path 可指任何组件 yaml）。
文本级编辑——保留注释/缩进/格式，不依赖 yaml 库。
配置文件位置（自动探测，可用 conf_path 入参覆盖）：
    Windows: c:\\easyops\\agent\\conf\\conf.yaml
    Linux:   /usr/local/easyops/agent/conf/conf.yaml
修改成功后自动使配置生效：cd <组件包根> && easyops init && easyops restart（Windows 加 /d）。
🔴重启目录语义（2026-09-30 .26 实测）：easyops 是全局脚本（/usr/bin）但对 cwd 敏感——
须 cd 组件包根（如 /usr/local/easyops/agent）；conf 目录或任意目录报
"current path is not a valid package"(2004)；`easyops restart agent` 位置参数同样报错。
自动推导：<配置文件在 组件根/conf/ 下 → 组件根=上两级>；restart_dir 入参可显式覆盖。

定位规则（修改方式=按参数路径 时，batch 每行的配置项）：
    · "ip" —— 修改配置文件【所有深度】的 ip 键（command/report/collector_agent/
      plugin_manager 各 server_groups.hosts 全部命中）
    · "xx.yy.zz" 点路径精确指定——支持任意深度；路径中的纯数字段匹配列表索引
      （如 command.server_groups.0.hosts.0.ip 精确第一组第一台）；
      【忽略数字段】模糊匹配命中全部列表元素（如 command.server_groups.hosts.ip
      = 该子树下所有 hosts 的 ip）

替换规则（修改方式=直接替换 时，batch 每行的写法）：
    "原文->新文本" —— 在整个配置文件里按【字面文本】替换全部命中处（不解释正则）；
    多条规则按填写顺序依次执行；原文须非空，修改时新文本不能为空（不支持删成空）。

入参（平台注入 globals 同名变量）：
    batch        批量修改（必填，多行字符串），每行格式随「修改方式」（空行与 # 注释忽略）：
                  · 按参数路径：每行 "配置项=修改值"，如：
                     ip=10.1.2.3
                     org=1888
                     command.server_groups.hosts.ip=10.1.2.9
                  · 直接替换：每行 "原文->新文本"，如：
                     10.1.2.3->10.1.2.4
                     port: 8079->port: 8080
                 批量语义（整体事务）：
                 任一项未命中 / 多项命中同一行（路径模式冲突）→ 整体不落盘直接报错；
                 全部通过后只备份一次、批量替换、统一回读校验，最后只执行一次 init+restart；
                 任一校验失败整体从备份恢复，不重启。
    edit_mode    修改方式，枚举 按参数路径/直接替换，默认 按参数路径——
                 按参数路径=按 YAML 点路径定位键并改值；直接替换=按字面文本全局替换
    action       动作，枚举 预览/修改，默认 预览——预览=列出命中项当前值不改动；
                 修改=备份→替换→回读验证→easyops init→easyops restart
    conf_path    配置文件完整路径，字符串，可选——默认按平台自动探测
    restart_dir  生效命令执行目录，字符串，可选——默认按 conf 路径推导组件包根
输出：
    PutStr("report", <预览清单或修改报告>) —— 完整值不截断
运行环境：EasyOps agent（py2）/ 编排侧 py3。stdlib only。
"""
import os
import re
import shutil
import subprocess
import sys
import time

IS_PY2 = sys.version_info[0] == 2
if IS_PY2:
    reload(sys)
    sys.setdefaultencoding('utf-8')

try:
    _string_types = (str, unicode)  # noqa: F821
except NameError:
    _string_types = (str,)

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('agent_conf_tool')

WIN_CONF = r'c:\easyops\agent\conf\conf.yaml'
LINUX_CONF = '/usr/local/easyops/agent/conf/conf.yaml'

# 行识别正则：key: value（冒号后有空格或行尾）；list 项 "- key: value"
RE_KEYVAL = re.compile(r'^(\s*)(-?\s*)([A-Za-z_][\w\-\.]*)\s*:(?:\s+(.*))?$')
RE_LISTITEM = re.compile(r'^(\s*)-\s+(.*)$')


def put_str(key, value):
    try:
        PutStr(key, value)  # noqa: F821 (平台注入)
    except NameError:
        logger.info(u'[%s] %s', key, value)


def _to_unicode(v):
    if IS_PY2 and isinstance(v, str):
        try:
            return v.decode('utf-8')
        except UnicodeDecodeError:
            return v
    return v


def detect_conf_path():
    if sys.platform.startswith('win'):
        return WIN_CONF
    return LINUX_CONF


def _split_value_comment(raw):
    """行值与行内注释分离：无引号包裹且含 ' #' 时在首个 ' #' 处切分。返回 (value, comment)。
    修改时只替换 value 段、保留注释（不丢配置文件的行内注释）。"""
    raw = raw.rstrip('\r\n')
    if raw.startswith('"') or raw.startswith("'"):
        # 引号值：找闭合引号后再看注释
        q = raw[0]
        end = raw.find(q, 1)
        while end != -1 and len(raw) > end + 1 and raw[end + 1:end + 2] == q and q == "'":
            end = raw.find(q, end + 2)  # 单引号转义 '' 跳过
        if end != -1:
            return raw[:end + 1], raw[end + 1:]
        return raw, ''
    # 无引号：# 前须有空白才是注释（防 # 出现在值中间的误切——如密码含#）
    m = re.search(r'\s+#', raw)
    if m:
        return raw[:m.start()], raw[m.start():]
    return raw, ''


class Line:
    __slots__ = ('no', 'indent', 'is_list', 'dash_col', 'list_idx', 'key', 'raw_value', 'text', 'path_segs')

    def __init__(self, no, text):
        self.no = no
        self.text = text
        self.indent = -1
        self.is_list = False
        self.dash_col = -1
        self.list_idx = -1
        self.key = None
        self.raw_value = None
        self.path_segs = []


def scan_lines(text):
    """文本级 YAML 扫描：识别全部 key: value 行，还原完整点路径（含列表索引数字段）。
    栈元素 (列号, 段名, 是否list项上下文)；list 项上下文压在 '-' 起始列，
    同列后续普通键不弹它（YAML 语义：项内容列的键属于该 list 项）。"""
    lines = []
    stack = []            # [(col, seg, is_item)]
    list_counter = {}     # dash_col -> 序号
    in_block = False
    block_col = 0
    for i, raw in enumerate(text.split('\n'), 1):
        ln = Line(i, raw.rstrip('\r'))
        lines.append(ln)
        stripped = raw.strip()
        if in_block:
            if stripped and (len(raw) - len(raw.lstrip(' '))) <= block_col:
                in_block = False   # 缩进回升出块，本行继续正常解析
            else:
                continue
        if not stripped or stripped.startswith('#'):
            continue
        m = RE_KEYVAL.match(ln.text)
        if not m:
            continue
        indent, dash, key, val = m.group(1), m.group(2), m.group(3), m.group(4)
        dash_col = len(indent)
        content_col = dash_col + len(dash)
        is_list = bool(dash.strip())
        # pop 阈值：list 项按 '-' 列（弹掉旧项上下文）；普通键按内容列
        pop_to = dash_col if is_list else content_col
        while stack and stack[-1][0] >= pop_to:
            stack.pop()
        for c in list(list_counter.keys()):
            if c >= pop_to:
                del list_counter[c]
        if is_list:
            idx = list_counter.get(dash_col, -1) + 1
            list_counter[dash_col] = idx
            stack.append((dash_col, str(idx), True))
            ln.list_idx = idx
        ln.indent = content_col
        ln.is_list = is_list
        ln.dash_col = dash_col
        ln.key = key
        ln.raw_value = val if val is not None else ''
        ln.path_segs = [s for (_c, s, _it) in stack] + [key]
        v = ln.raw_value.strip()
        if v in ('|', '>', '|-', '>-', '|+', '>+'):
            in_block = True
            block_col = content_col
        elif v == '':
            stack.append((content_col, key, False))   # 纯父节点入栈
        # 有值行是叶子：不push（path_segs 已含自身 key）
    return lines


def find_targets(text, config_item):
    """返回 [(line_no, full_path, value, comment)]——config_item 命中的全部叶子行。"""
    out = []
    for ln in scan_lines(text):
        if ln.key is None or not ln.raw_value.strip():
            continue
        full = '.'.join(ln.path_segs)
        if match_path(config_item, full):
            val, cmt = _split_value_comment(ln.raw_value)
            out.append((ln.no, full, val.strip(), cmt))
    return out


def match_path(user_path, full_path):
    """点路径匹配（后缀语义）：用户路径匹配行全路径的【尾部】任意深度。
    从末尾逐段对齐：用户数字段→行路径对应段须是相同数字（精确列表索引）；
    用户非数字段→跳过行路径数字段（模糊命中全部列表元素）。
    例："ip"=所有深度的 ip 键；"server_groups.hosts.ip"=任意子树该链；
    "command.server_groups.0.hosts.0.ip"=精确第一组第一台。"""
    if not user_path:
        return False
    usegs = [x.strip() for x in user_path.split('.') if x.strip()]
    fsegs = full_path.split('.') if full_path else []
    ui = len(usegs) - 1
    fi = len(fsegs) - 1
    while ui >= 0:
        if fi < 0:
            return False
        if fsegs[fi].isdigit():
            if usegs[ui].isdigit():
                if fsegs[fi] != usegs[ui]:
                    return False
                ui -= 1
            fi -= 1   # 用户未给索引 → 跳过行路径数字段（模糊命中所有列表元素）
            continue
        if fsegs[fi] != usegs[ui]:
            return False
        ui -= 1
        fi -= 1
    return True


def apply_changes(text, targets, new_value):
    """逐行替换值段（保留 key/缩进/行内注释）。返回新文本。"""
    lines = text.split('\n')
    for no, _full, _old, _cmt in targets:
        raw = lines[no - 1]
        m = RE_KEYVAL.match(raw)
        indent, dash, key, val = m.group(1), m.group(2), m.group(3), m.group(4)
        _v, cmt = _split_value_comment(val or '')
        lines[no - 1] = '%s%s%s:%s%s' % (indent, dash, key, ' ' + new_value if new_value else '', cmt)
    return '\n'.join(lines)


def resolve_restart_dir(conf_path, override):
    """重启执行目录推导（2026-09-30 .26 实测）：easyops restart 须 cd【组件包根】——
    conf 目录/其它目录报 "current path is not a valid package"（2004）。
    规则：配置文件在 <组件根>/conf/ 下 → 组件根=dirname(dirname(conf))；否则=dirname(conf)。
    restart_dir 入参可显式覆盖。双端路径兼容：含反斜杠/盘符的按 windows 语义拆。"""
    if override:
        return override
    if '\\' in conf_path or ':' in conf_path:
        import ntpath
        d = ntpath.dirname(conf_path)
        return ntpath.dirname(d) if ntpath.basename(d).lower() == 'conf' else d
    d = os.path.dirname(conf_path)
    if os.path.basename(d) == 'conf':
        return os.path.dirname(d)
    return d


def restart_agent(pkg_dir):
    """使配置生效：cd <组件包根> && easyops init && easyops restart（win 加 /d）。返回 (rc, output)。"""
    if sys.platform.startswith('win'):
        cmd = 'cd /d %s && easyops init && easyops restart' % pkg_dir
    else:
        cmd = 'cd %s && easyops init && easyops restart' % pkg_dir
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.communicate()[0]
    if isinstance(out, bytes):
        out = out.decode('utf-8', 'replace')
    return p.returncode, (out or '').strip()


def _unquote(raw):
    """去掉 YAML 值的成对引号，用于回读比对（引号值落盘后仍能校验通过）。"""
    v = (raw or '').strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


def parse_batch_items(raw, allow_empty_value=False):
    """解析 batch 多行文本：每行 "配置项=修改值"；忽略空行与 # 注释。
    返回 (items, errors)，items=[(config_item, value)]。"""
    items = []
    errors = []
    seen = {}
    for idx, line in enumerate((raw or '').split('\n')):
        cur = line.strip()
        if not cur or cur.startswith('#'):
            continue
        if '=' not in cur:
            errors.append(u'第 %d 行缺少 "="：%s' % (idx + 1, cur))
            continue
        key, val = cur.split('=', 1)
        key = key.strip()
        val = val.strip()
        if not key:
            errors.append(u'第 %d 行配置项为空：%s' % (idx + 1, cur))
            continue
        if not val and not allow_empty_value:
            errors.append(u'第 %d 行修改值为空：%s' % (idx + 1, cur))
            continue
        if key in seen:
            errors.append(u'第 %d 行配置项重复：%s（首次出现在第 %d 行）' % (idx + 1, key, seen[key]))
            continue
        seen[key] = idx + 1
        items.append((key, val))
    return items, errors


def parse_replace_items(raw, allow_empty_value=False):
    """解析 batch 多行文本（直接替换模式）：每行 "原文->新文本"；忽略空行与 # 注释。
    按首个 "->" 切分，两侧按字面使用（不额外 strip 内部空格）。返回 (items, errors)。"""
    items = []
    errors = []
    seen = {}
    for idx, line in enumerate((raw or '').split('\n')):
        cur = line.strip()
        if not cur or cur.startswith('#'):
            continue
        if '->' not in cur:
            errors.append(u'第 %d 行缺少 "->"：%s' % (idx + 1, cur))
            continue
        old, new = cur.split('->', 1)
        if not old:
            errors.append(u'第 %d 行原文为空：%s' % (idx + 1, cur))
            continue
        if not new and not allow_empty_value:
            errors.append(u'第 %d 行新文本为空：%s' % (idx + 1, cur))
            continue
        if old in seen:
            errors.append(u'第 %d 行原文重复：%s（首次出现在第 %d 行）' % (idx + 1, old, seen[old]))
            continue
        seen[old] = idx + 1
        items.append((old, new))
    return items, errors


def find_replace_hits(text, old):
    """按字面查找 old 的全部命中，按行聚合。返回 [(line_no, count, line_text)]。"""
    hits = []
    start = 0
    while True:
        pos = text.find(old, start)
        if pos < 0:
            break
        no = text.count('\n', 0, pos) + 1
        if hits and hits[-1][0] == no:
            hits[-1][1] += 1
        else:
            hits.append([no, 1, text.split('\n')[no - 1]])
        start = pos + len(old)
    return hits


def run_replace_mode(text, conf_path, restart_dir_in, items, action):
    """直接替换模式：预览或修改（字面文本全局替换，按填写顺序依次执行）。"""
    scope = u'文本替换 %d 条' % len(items)
    if action == u'预览':
        out = [u'预览（直接替换，未做任何修改）——%s @%s：' % (scope, conf_path)]
        cur = text
        for old, new in items:
            hits = find_replace_hits(cur, old)
            out.append(u'【%s -> %s】命中 %d 处%s' % (old, new, sum(h[1] for h in hits),
                                                    u'' if hits else u'  ⚠️ 未命中'))
            for no, cnt, line in hits:
                out.append(u'  行%-4d%s %s' % (no, (u'（×%d）' % cnt) if cnt > 1 else u'', line))
            cur = cur.replace(old, new)
        out.append(u'（执行修改：action=修改 + 修改方式=直接替换；全部命中后统一备份，只执行一次 easyops init && easyops restart）')
        put_str('report', u'\n'.join(out))
        return 0

    cur = text
    missing = []
    detail = []
    for old, new in items:
        hits = find_replace_hits(cur, old)
        if not hits:
            missing.append(old)
            continue
        detail.append((old, new, sum(h[1] for h in hits), [h[0] for h in hits]))
        cur = cur.replace(old, new)
    if missing:
        put_str('report', u'❌ 以下原文未命中任何内容，未做任何修改（整体不落盘）：%s\nconf=%s\n提示：直接替换按字面匹配，请检查原文是否与配置文件完全一致（含空格/标点）。'
                % (u', '.join(missing), conf_path))
        return 1

    stamp = time.strftime('%Y%m%d_%H%M%S')
    backup = '%s.bak.%s' % (conf_path, stamp)
    shutil.copy2(conf_path, backup)

    with open(conf_path, 'wb') as f:
        f.write(cur.encode('utf-8'))

    with open(conf_path, 'rb') as f:
        check = f.read().decode('utf-8', 'replace')
    if check != cur:
        shutil.copy2(backup, conf_path)
        put_str('report', u'❌ 回读验证失败（写入内容不一致），已从备份恢复：%s' % backup)
        return 3

    total = sum(d[2] for d in detail)
    report = [u'修改完成——%s，共 %d 处 @%s：' % (scope, total, conf_path)]
    for old, new, cnt, nos in detail:
        report.append(u'  【%s -> %s】命中 %d 处（行 %s）' % (old, new, cnt, u', '.join(str(n) for n in nos)))
    report.append(u'备份：%s' % backup)
    report.append(u'回读验证：✅ 文件内容与预期完全一致')
    report.append(u'即将使配置生效（cd 组件包根 %s && easyops init && easyops restart）……' % resolve_restart_dir(conf_path, restart_dir_in))
    put_str('report', u'\n'.join(report))

    rc, out = restart_agent(resolve_restart_dir(conf_path, restart_dir_in))
    tail = [u'配置生效（cd 组件包根 && easyops init && easyops restart，目录=%s）：exit=%s' % (resolve_restart_dir(conf_path, restart_dir_in), rc)]
    if out:
        tail.append(u'重启输出：\n%s' % out)
    if rc != 0:
        tail.append(u'⚠️ 重启命令返回非 0——请人工确认 agent 状态（配置已改好，备份在 %s）' % backup)
    put_str('report', u'\n'.join(tail))
    return 0


def main():
    g = globals()
    action = _to_unicode(g.get('action') or u'预览')
    if isinstance(action, bool):
        action = u'修改' if action else u'预览'
    edit_mode = _to_unicode(g.get('edit_mode') or g.get('editMode') or u'按参数路径')
    conf_path = _to_unicode(g.get('conf_path') or g.get('confPath') or '') or detect_conf_path()
    restart_dir_in = _to_unicode(g.get('restart_dir') or g.get('restartDir') or '')
    batch_raw = g.get('batch')
    if isinstance(batch_raw, (list, tuple)):
        batch_raw = u'\n'.join(_to_unicode(x) for x in batch_raw)
    else:
        batch_raw = _to_unicode(batch_raw or '')
        if not isinstance(batch_raw, _string_types):
            batch_raw = _string_types[0](batch_raw)

    if action not in (u'预览', u'修改'):
        put_str('report', u'❌ 动作必须是 预览 或 修改，当前：%r' % action)
        return 1
    if edit_mode not in (u'按参数路径', u'直接替换'):
        put_str('report', u'❌ 修改方式必须是 按参数路径 或 直接替换，当前：%r' % edit_mode)
        return 1

    if not batch_raw.strip():
        if edit_mode == u'直接替换':
            hint = u'每行 "原文->新文本"，如：\n  10.1.2.3->10.1.2.4\n  port: 8079->port: 8080'
        else:
            hint = u'每行 "配置项=修改值"，如：\n  ip=10.1.2.3\n  org=1888'
        put_str('report', u'❌ 批量修改内容为空。请按多行格式填写，%s\n（空行与 # 注释会被忽略）' % hint)
        return 1

    if edit_mode == u'直接替换':
        items, errors = parse_replace_items(batch_raw, allow_empty_value=(action == u'预览'))
        fmt = u'每行 "原文->新文本"，如 10.1.2.3->10.1.2.4；空行与 # 注释会被忽略。'
    else:
        items, errors = parse_batch_items(batch_raw, allow_empty_value=(action == u'预览'))
        fmt = u'每行 "配置项=修改值"，如 ip=10.1.2.3；空行与 # 注释会被忽略。'
    if errors:
        put_str('report', u'❌ batch 解析失败，未做任何修改：\n  ' + u'\n  '.join(errors) +
                u'\n格式：' + fmt)
        return 1
    if not items:
        put_str('report', u'❌ batch 为空（只含空行/注释），未做任何修改。')
        return 1

    if not os.path.isfile(conf_path):
        put_str('report', u'❌ 配置文件不存在：%s（可用 conf_path 入参指定完整路径）' % conf_path)
        return 1

    with open(conf_path, 'rb') as f:
        raw_text = f.read()
    text = raw_text.decode('utf-8', 'replace')

    if edit_mode == u'直接替换':
        return run_replace_mode(text, conf_path, restart_dir_in, items, action)

    resolved = []
    missing = []
    for key, val in items:
        tg = find_targets(text, key)
        resolved.append((key, val, tg))
        if not tg:
            missing.append(key)

    scope = u'批量 %d 项' % len(items)

    if action == u'预览':
        out = [u'预览（未做任何修改）——%s @%s：' % (scope, conf_path)]
        for key, val, tg in resolved:
            out.append(u'【%s】命中 %d 处%s' % (key, len(tg), u'' if tg else u'  ⚠️ 未命中'))
            for no, full, cur, _cmt in tg:
                out.append(u'  行%-4d %s = %s%s' % (no, full, cur, (u' → ' + val) if val else u''))
        if missing:
            out.append(u'⚠️ 修改模式下未命中会直接报错且整体不落盘：%s' % u', '.join(missing))
        out.append(u'（执行修改：action=修改 + 修改方式=按参数路径 + 填写「批量修改」多行内容，每行 配置项=修改值；全部通过后统一备份、只执行一次 easyops init && easyops restart）')
        put_str('report', u'\n'.join(out))
        return 0

    if missing:
        put_str('report', u'❌ 以下配置项未命中任何键，未做任何修改（整体不落盘）：%s\nconf=%s\n提示：默认 ip=全深度 ip 键；精确指定用点路径（如 command.server_groups.hosts.ip，数字段可选用于精确列表索引）。' % (u', '.join(missing), conf_path))
        return 1

    # 冲突检测：同一行被多个配置项命中 → 无法确定以谁为准，整体不落盘
    line_owner = {}
    conflicts = []
    for key, _val, tg in resolved:
        for no, full, _cur, _cmt in tg:
            if no in line_owner:
                prev_key, prev_full = line_owner[no]
                conflicts.append(u'行%d 同时命中 %s(%s) 与 %s(%s)' % (no, prev_key, prev_full, key, full))
            else:
                line_owner[no] = (key, full)
    if conflicts:
        put_str('report', u'❌ 配置项相互冲突，未做任何修改（整体不落盘）：\n  ' + u'\n  '.join(conflicts) +
                u'\n请改用更精确的点路径，避免宽泛项（如 ip）与具体路径同时命中同一行。')
        return 1

    # ---- 修改：一次备份 → 批量替换 → 统一回读验证 → 一次 init+restart ----
    stamp = time.strftime('%Y%m%d_%H%M%S')
    backup = '%s.bak.%s' % (conf_path, stamp)
    shutil.copy2(conf_path, backup)

    old_vals = []
    new_text = text
    for key, val, tg in resolved:
        for no, full, cur, _cmt in tg:
            old_vals.append((no, full, cur, val))
        new_text = apply_changes(new_text, tg, val)

    if len(new_text.split('\n')) != len(text.split('\n')):
        shutil.copy2(backup, conf_path)
        put_str('report', u'❌ 替换后行数变化（异常），已从备份恢复：%s' % backup)
        return 2

    with open(conf_path, 'wb') as f:
        f.write(new_text.encode('utf-8'))

    with open(conf_path, 'rb') as f:
        check_text = f.read().decode('utf-8', 'replace')
    failed = []
    for key, val, tg in resolved:
        check_tg = find_targets(check_text, key)
        if len(check_tg) != len(tg) or any(_unquote(v[2]) != _unquote(val) for v in check_tg):
            failed.append(key)
    if failed:
        shutil.copy2(backup, conf_path)
        put_str('report', u'❌ 回读验证失败（%s），已从备份整体恢复：%s\n提示：修改值若含 " #" 请用引号包裹（如 \"a b # c\"）。' % (u', '.join(failed), backup))
        return 3

    total = sum(len(tg) for _k, _v, tg in resolved)
    report = [u'修改完成——%s，共 %d 处 @%s：' % (scope, total, conf_path)]
    for no, full, cur, val in old_vals:
        report.append(u'  行%-4d %s: %s → %s' % (no, full, cur, val))
    report.append(u'备份：%s' % backup)
    report.append(u'回读验证：✅ %d 处新值全部落位' % total)
    # 🔴先发主报告再重启（agent 自重启可能终止本进程——报告先落袋，重启结果二次输出）
    report.append(u'即将使配置生效（cd 组件包根 %s && easyops init && easyops restart）……' % resolve_restart_dir(conf_path, restart_dir_in))
    put_str('report', u'\n'.join(report))

    rc, out = restart_agent(resolve_restart_dir(conf_path, restart_dir_in))
    tail = [u'配置生效（cd 组件包根 && easyops init && easyops restart，目录=%s）：exit=%s' % (resolve_restart_dir(conf_path, restart_dir_in), rc)]
    if out:
        tail.append(u'重启输出：\n%s' % out)
    if rc != 0:
        tail.append(u'⚠️ 重启命令返回非 0——请人工确认 agent 状态（配置已改好，备份在 %s）' % backup)
    put_str('report', u'\n'.join(tail))
    return 0


if __name__ == '__main__':
    main()
