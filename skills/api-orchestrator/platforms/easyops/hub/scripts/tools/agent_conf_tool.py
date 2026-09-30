# -*- coding: utf-8 -*-
"""
Agent配置修改（EasyOps agent conf.yaml 修改工具）

功能：修改本机 EasyOps agent 配置文件 conf.yaml（文本级编辑——保留注释/缩进/格式，不依赖 yaml 库）。
配置文件位置（自动探测，可用 conf_path 入参覆盖）：
    Windows: c:\\easyops\\agent\\conf\\conf.yaml
    Linux:   /usr/local/easyops/agent/conf/conf.yaml
修改成功后自动重启 agent：cd <conf目录> && easyops restart（Windows 加 /d）。

定位规则（config_item 入参）：
    · 默认 "ip" —— 修改配置文件【所有深度】的 ip 键（command/report/collector_agent/
      plugin_manager 各 server_groups.hosts 全部命中）
    · "xx.yy.zz" 点路径精确指定——支持任意深度；路径中的纯数字段匹配列表索引
      （如 command.server_groups.0.hosts.0.ip 精确第一组第一台）；
      【忽略数字段】模糊匹配命中全部列表元素（如 command.server_groups.hosts.ip
      = 该子树下所有 hosts 的 ip）

入参（平台注入 globals 同名变量）：
    config_item  配置项，字符串，默认 "ip"（全深度 ip 键；或 xx.yy.zz 点路径精确指定）
    value        修改值，字符串，动作=修改 时必填（原样写入；带空格/特殊字符自行加引号）
    action       动作，枚举 预览/修改，默认 预览——预览=列出命中项当前值不改动；
                 修改=备份→替换→回读验证→重启 agent
    conf_path    配置文件完整路径，字符串，可选——默认按平台自动探测
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


def restart_agent(conf_dir):
    """重启 agent：cd <conf目录> && easyops restart（win 加 /d）。返回 (rc, output)。"""
    if sys.platform.startswith('win'):
        cmd = 'cd /d %s && easyops restart' % conf_dir
    else:
        cmd = 'cd %s && easyops restart' % conf_dir
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.communicate()[0]
    if isinstance(out, bytes):
        out = out.decode('utf-8', 'replace')
    return p.returncode, (out or '').strip()


def main():
    g = globals()
    config_item = _to_unicode(g.get('config_item') or g.get('Config_item') or 'ip')
    if not isinstance(config_item, _string_types):
        config_item = _string_types[0](config_item)
    config_item = config_item.strip() or 'ip'
    new_value = _to_unicode(g.get('value') or g.get('new_value') or '')
    if not isinstance(new_value, _string_types):
        new_value = _string_types[0](new_value)
    new_value = new_value.strip()
    action = _to_unicode(g.get('action') or u'预览')
    if isinstance(action, bool):
        action = u'修改' if action else u'预览'
    conf_path = _to_unicode(g.get('conf_path') or g.get('confPath') or '') or detect_conf_path()

    if action not in (u'预览', u'修改'):
        put_str('report', u'❌ 动作必须是 预览 或 修改，当前：%r' % action)
        return 1
    if action == u'修改' and not new_value:
        put_str('report', u'❌ 动作=修改 时必须提供修改值（value）')
        return 1
    if not os.path.isfile(conf_path):
        put_str('report', u'❌ 配置文件不存在：%s（可用 conf_path 入参指定完整路径）' % conf_path)
        return 1

    with open(conf_path, 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-8', 'replace')

    targets = find_targets(text, config_item)
    if not targets:
        put_str('report', u'配置项 %s 未命中任何键（conf=%s）。\n提示：默认 ip=全深度 ip 键；精确指定用点路径（如 command.server_groups.hosts.ip，数字段可选用于精确列表索引）。' % (config_item, conf_path))
        return 0

    if action == u'预览':
        lines_out = [u'预览（未做任何修改）——配置项 %s 命中 %d 处 @%s：' % (config_item, len(targets), conf_path)]
        for no, full, val, _cmt in targets:
            lines_out.append(u'  行%-4d %s = %s' % (no, full, val))
        lines_out.append(u'（执行修改：action=修改 + value=<新值>；修改后自动备份并重启 agent）')
        put_str('report', u'\n'.join(lines_out))
        return 0

    # ---- 修改：备份 → 替换 → 回读验证 → 重启 ----
    stamp = time.strftime('%Y%m%d_%H%M%S')
    backup = '%s.bak.%s' % (conf_path, stamp)
    shutil.copy2(conf_path, backup)

    old_vals = [(no, full, val) for no, full, val, _c in targets]
    new_text = apply_changes(text, targets, new_value)
    # 行数不变校验
    if len(new_text.split('\n')) != len(text.split('\n')):
        shutil.copy2(backup, conf_path)
        put_str('report', u'❌ 替换后行数变化（异常），已从备份恢复：%s' % backup)
        return 2

    with open(conf_path, 'wb') as f:
        f.write(new_text.encode('utf-8'))

    # 回读验证
    with open(conf_path, 'rb') as f:
        check_text = f.read().decode('utf-8', 'replace')
    check_targets = find_targets(check_text, config_item)
    ok = len(check_targets) == len(targets) and all(v[2] == new_value for v in check_targets)
    if not ok:
        shutil.copy2(backup, conf_path)
        put_str('report', u'❌ 回读验证失败（新值未全部落位），已从备份恢复：%s' % backup)
        return 3

    report = [u'修改完成——配置项 %s 共 %d 处 @%s：' % (config_item, len(targets), conf_path)]
    for no, full, val in old_vals:
        report.append(u'  行%-4d %s: %s → %s' % (no, full, val, new_value))
    report.append(u'备份：%s' % backup)
    report.append(u'回读验证：✅ %d 处新值全部落位' % len(check_targets))
    # 🔴先发主报告再重启（agent 自重启可能终止本进程——报告先落袋，重启结果二次输出）
    report.append(u'即将重启 agent（cd conf目录 && easyops restart）……')
    put_str('report', u'\n'.join(report))

    rc, out = restart_agent(os.path.dirname(conf_path))
    tail = [u'重启 agent：exit=%s' % rc]
    if out:
        tail.append(u'重启输出：\n%s' % out)
    if rc != 0:
        tail.append(u'⚠️ 重启命令返回非 0——请人工确认 agent 状态（配置已改好，备份在 %s）' % backup)
    put_str('report', u'\n'.join(tail))
    return 0


if __name__ == '__main__':
    main()
