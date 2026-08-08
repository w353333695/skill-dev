#!/usr/bin/env python3
"""
通用层级关系图生成器

架构：
1. 数据获取：从各种数据源获取数据 → 输出通用 YAML/JSON
2. 渲染引擎：从 YAML/JSON → 生成 drawio

通用数据格式 (YAML):
```yaml
title: 拓扑图标题
nodes:
  - id: node1
    name: 节点1
    category: 一级分类.二级分类
  - id: node2
    name: 节点2
    category: 一级分类.二级分类

edges:
  - from: node1
    to: node2
    label: 关系名称
    cardinality: "1:N"
```

使用示例：
    # 从 CMDB 获取并生成
    python generate_topology_drawio.py --from-cmdb "MODEL1\\MODEL2" -o output.drawio

    # 从 YAML 生成
    python generate_topology_drawio.py --from-yaml data.yaml -o output.drawio

    # 仅导出 YAML（不生成 drawio）
    python generate_topology_drawio.py --from-cmdb "MODEL1\\MODEL2" --export-yaml data.yaml
"""

import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
import argparse
import html
import platform

import requests
import yaml

# 尝试导入 yaml，不强制依赖
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class TopologyData:
    """通用拓扑数据结构"""

    def __init__(self, title: str = "拓扑图"):
        self.title = title
        self.nodes: List[dict] = []
        self.edges: List[dict] = []

    def add_node(self, node_id: str, name: str, category: str = "默认"):
        """添加节点"""
        self.nodes.append({
            'id': node_id,
            'name': name,
            'category': category
        })

    def add_edge(self, from_id: str, to_id: str, label: str = "", cardinality: str = ""):
        """添加边"""
        self.edges.append({
            'from': from_id,
            'to': to_id,
            'label': label,
            'cardinality': cardinality
        })

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'title': self.title,
            'nodes': self.nodes,
            'edges': self.edges
        }

    def to_yaml(self) -> str:
        """导出为 YAML"""
        if not HAS_YAML:
            raise ImportError("需要安装 pyyaml: pip install pyyaml")
        return yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    def to_json(self) -> str:
        """导出为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> 'TopologyData':
        """从字典创建"""
        topo = cls(title=data.get('title', '拓扑图'))
        topo.nodes = data.get('nodes', [])
        topo.edges = data.get('edges', [])
        return topo

    @classmethod
    def from_yaml(cls, yaml_str: str) -> 'TopologyData':
        """从 YAML 创建"""
        if not HAS_YAML:
            raise ImportError("需要安装 pyyaml: pip install pyyaml")
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)

    @classmethod
    def from_json(cls, json_str: str) -> 'TopologyData':
        """从 JSON 创建"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_file(cls, file_path: str) -> 'TopologyData':
        """从文件加载（自动识别 YAML/JSON）"""
        path = Path(file_path)
        content = path.read_text(encoding='utf-8')

        if path.suffix in ('.yaml', '.yml'):
            return cls.from_yaml(content)
        elif path.suffix == '.json':
            return cls.from_json(content)
        else:
            # 尝试自动识别
            try:
                return cls.from_json(content)
            except json.JSONDecodeError:
                return cls.from_yaml(content)


class CMDBDataFetcher:
    """CMDB 数据获取器"""

    def __init__(self):
        import urllib3
        urllib3.disable_warnings()

        # 从 agent 配置自动读取 host/org
        try:
            if platform.system().lower() == "windows":
                conf_path = "C:\\easyOps\\agent\\conf\\conf.yaml"
            else:
                conf_path = "/usr/local/easyops/agent/conf/conf.yaml"
            with open(conf_path, 'r') as f:
                conf = yaml.load(f, Loader=yaml.FullLoader)
            self.host = conf['command']['server_groups'][0]['hosts'][0]['ip'].split(',')[0]
            self.org = str(conf['base']['client_id'])
        except Exception:
            self.host = None
            self.org = None
        self.headers = {
            "user": "defaultUser",
            "org": self.org or "",
            "Content-Type": "application/json"
        }

    def _get_model_desc(self, model_id: str) -> dict:
        """获取 CMDB 模型描述"""
        url = f"http://{self.host}:8079/object/{model_id}"
        response = requests.get(url, headers=self.headers, timeout=30, verify=False)
        response.raise_for_status()
        return response.json().get("data", {})

    def fetch(self, model_ids: List[str]) -> TopologyData:
        """从 CMDB 获取模型数据，转换为通用格式"""
        topo = TopologyData(title="CMDB 模型拓扑图")
        models = {}

        # 获取模型信息
        for model_id in model_ids:
            try:
                desc = self._get_model_desc(model_id)
                models[model_id] = desc
                topo.add_node(
                    node_id=model_id,
                    name=desc.get('name', model_id),
                    category=desc.get('category', '未分类')
                )
                print(f"[OK] 获取模型: {model_id} ({desc.get('name', '')})")
            except Exception as e:
                print(f"[WARN] 获取模型失败: {model_id} - {e}")

        # 收集关系
        # 构建 objectId 映射：API 返回的完整 ID（如 APP_SYSTEM@ONEMODEL）→ 用户传入的 ID（如 APP_SYSTEM）
        full_id_map = {}
        for model_id, desc in models.items():
            full_id_map[model_id] = model_id
            obj_id = desc.get('objectId', '')
            if obj_id and obj_id != model_id:
                full_id_map[obj_id] = model_id

        seen_edges = set()

        for model_id, desc in models.items():
            for rel in desc.get('relation_list', []):
                left_obj = rel.get('left_object_id')
                right_obj = rel.get('right_object_id')

                # 将完整 ID 映射回用户传入的 ID
                left_mapped = full_id_map.get(left_obj)
                right_mapped = full_id_map.get(right_obj)

                if left_mapped and right_mapped:
                    edge_key = (left_mapped, right_mapped)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)

                        rel_name = rel.get('left_name') or rel.get('relation_id', '')
                        left_max = rel.get('left_max', -1)
                        right_max = rel.get('right_max', -1)
                        left_card = 'N' if left_max == -1 else str(left_max)
                        right_card = 'N' if right_max == -1 else str(right_max)

                        topo.add_edge(
                            from_id=left_mapped,
                            to_id=right_mapped,
                            label=rel_name,
                            cardinality=f"{left_card}:{right_card}"
                        )

        print(f"\n获取完成: {len(topo.nodes)} 个节点, {len(topo.edges)} 条关系")
        return topo


class DrawioRenderer:
    """Draw.io 渲染器 - 从通用数据生成 drawio 文件"""

    # 预定义颜色（常用分类）
    PRESET_COLORS = {
        '应用资源': ('#dae8fc', '#6c8ebf', '#4a90d9'),  # fill, stroke, node
        '基础设施': ('#d5e8d4', '#82b366', '#50c878'),
        '资源管理': ('#ffe6cc', '#d79b00', '#ffb347'),
    }

    # 备用颜色池（用于未知分类）
    COLOR_POOL = [
        ('#f8cecc', '#b85450', '#e57373'),  # 红色系
        ('#e1d5e7', '#9673a6', '#9c27b0'),  # 紫色系
        ('#fff2cc', '#d6b656', '#ffc107'),  # 黄色系
        ('#d5e8d4', '#82b366', '#4caf50'),  # 绿色系
        ('#dae8fc', '#6c8ebf', '#2196f3'),  # 蓝色系
        ('#f5f5f5', '#666666', '#9e9e9e'),  # 灰色系
        ('#ffe0b2', '#ff9800', '#ff9800'),  # 橙色系
        ('#b2ebf2', '#00acc1', '#00bcd4'),  # 青色系
    ]

    def __init__(self):
        self.cell_id = 2
        self._category_color_map = {}  # 动态分配的颜色映射
        self._color_index = 0

    def next_id(self) -> str:
        self.cell_id += 1
        return str(self.cell_id)

    def _get_category_colors(self, category: str) -> tuple:
        """
        获取分类颜色，支持动态分配

        :param category: 分类名称
        :return: (fill_color, stroke_color, node_color)
        """
        # 先查预定义颜色
        if category in self.PRESET_COLORS:
            return self.PRESET_COLORS[category]

        # 再查已分配的颜色
        if category in self._category_color_map:
            return self._category_color_map[category]

        # 动态分配新颜色
        colors = self.COLOR_POOL[self._color_index % len(self.COLOR_POOL)]
        self._category_color_map[category] = colors
        self._color_index += 1
        return colors

    def _is_dark_color(self, hex_color: str) -> bool:
        """判断颜色是否为深色（用于选择字体颜色）"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return False
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        # 使用亮度公式判断
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance < 0.5

    def render(self, topo: TopologyData, output_path: str, by_category: bool = True, max_cols: int = 8):
        """渲染拓扑图到 drawio 文件"""
        # 构建节点索引
        nodes = {n['id']: n for n in topo.nodes}

        # 计算布局
        if by_category:
            positions, groups = self._calc_category_layout(topo.nodes, max_cols=max_cols)
        else:
            positions, groups = self._calc_linear_layout(topo.nodes)

        # 构建 XML
        root = ET.Element('mxfile', {
            'host': 'app.diagrams.net', 'modified': '2024-01-01T00:00:00.000Z',
            'agent': 'Topology Generator', 'version': '21.0.0', 'type': 'device'
        })
        diagram = ET.SubElement(root, 'diagram', {'id': 'topology', 'name': topo.title})
        graph = ET.SubElement(diagram, 'mxGraphModel', {
            'dx': '1000', 'dy': '800', 'grid': '1', 'gridSize': '10',
            'guides': '1', 'tooltips': '1', 'connect': '1', 'arrows': '1',
            'fold': '1', 'page': '1', 'pageScale': '1', 'pageWidth': '1600',
            'pageHeight': '1200', 'math': '0', 'shadow': '0'
        })

        root_cell = ET.SubElement(graph, 'root')
        ET.SubElement(root_cell, 'mxCell', {'id': '0'})
        ET.SubElement(root_cell, 'mxCell', {'id': '1', 'parent': '0'})

        node_cell_ids = {}

        # 绘制分类框（按层级顺序：1级 → 2级 → 3级）
        for level in [1, 2, 3]:
            for name, info in groups.items():
                if info.get('level') == level:
                    self._add_group_cell(root_cell, name, info)

        # 绘制节点
        for node_id, pos in positions.items():
            node = nodes.get(node_id, {})
            cell_id = self._add_node_cell(root_cell, node, pos)
            node_cell_ids[node_id] = cell_id

        # 绘制连线
        for edge in topo.edges:
            if edge['from'] in node_cell_ids and edge['to'] in node_cell_ids:
                self._add_edge_cell(
                    root_cell,
                    node_cell_ids[edge['from']],
                    node_cell_ids[edge['to']],
                    edge.get('label', ''),
                    edge.get('cardinality', '')
                )

        # 写入文件
        tree = ET.ElementTree(root)
        ET.indent(tree, space='  ')
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"\nDraw.io 文件已保存: {output_path}")

    def _group_by_category(self, nodes: List[dict]) -> Dict[str, Dict[str, Dict[str, List[dict]]]]:
        """
        按分类分组（支持最多3级）

        分类格式: l1.l2.l3.l4... → 解析为 l1, l2, l3.l4...
        """
        grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for node in nodes:
            category = node.get('category', '未分类')
            parts = category.split('.')

            level1 = parts[0] if len(parts) > 0 else '未分类'
            level2 = parts[1] if len(parts) > 1 else '默认'
            # 第三级及之后合并
            level3 = '.'.join(parts[2:]) if len(parts) > 2 else '默认'

            grouped[level1][level2][level3].append(node)
        return grouped

    def _calc_category_layout(self, nodes: List[dict], max_cols: int = 8):
        """
        按分类计算布局（支持3级分类，自动换行）

        :param nodes: 节点列表
        :param max_cols: 每行最大模型数量，超过则换行
        """
        grouped = self._group_by_category(nodes)
        positions = {}
        groups = {}

        node_w, node_h = 140, 60
        model_spacing_x = 160   # 模型水平间距
        model_spacing_y = 80    # 模型垂直间距（换行时）
        l3_spacing_x = 30       # 三级分类间距
        l2_spacing_x = 40       # 二级分类间距
        l1_spacing_y = 50       # 一级分类垂直间距
        padding = 25

        def calc_grid_size(count: int, max_cols: int):
            """计算网格尺寸（列数、行数）"""
            cols = min(count, max_cols)
            rows = (count + cols - 1) // cols
            return cols, rows

        def calc_box_size(count: int, max_cols: int):
            """计算容纳多行模型的框尺寸"""
            cols, rows = calc_grid_size(count, max_cols)
            w = (cols - 1) * model_spacing_x + node_w + padding * 2
            h = (rows - 1) * model_spacing_y + node_h + padding * 2
            return w, h, cols, rows

        # 第一遍：计算所有分类的宽度和高度，同级分类统一行数
        max_l1_width = 0
        l1_layouts = {}

        for l1, l2_dict in grouped.items():
            l2_layouts = []
            total_l2_width = 0
            max_l2_height = 0

            # 先收集该一级分类下所有三级分类的模型数量，确定统一行数
            all_l3_counts = []
            for l2, l3_dict in l2_dict.items():
                for l3, l3_nodes in l3_dict.items():
                    all_l3_counts.append(len(l3_nodes))

            # 计算统一行数：按最大模型数和 max_cols 计算
            max_count = max(all_l3_counts) if all_l3_counts else 1
            unified_rows = (max_count + max_cols - 1) // max_cols

            for l2, l3_dict in l2_dict.items():
                l3_layouts = []
                total_l3_width = 0
                max_l3_height = 0

                for l3, l3_nodes in l3_dict.items():
                    count = len(l3_nodes)
                    # 列数自适应：按统一行数计算每个分类需要的列数
                    cols = (count + unified_rows - 1) // unified_rows if unified_rows > 0 else count
                    cols = max(1, cols)  # 至少1列

                    # 宽度按实际列数计算
                    l3_w = (cols - 1) * model_spacing_x + node_w + padding * 2
                    # 高度按统一行数计算
                    l3_h = (unified_rows - 1) * model_spacing_y + node_h + padding * 2

                    l3_layouts.append({
                        'name': l3, 'nodes': l3_nodes,
                        'width': l3_w, 'height': l3_h,
                        'cols': cols, 'rows': unified_rows
                    })
                    total_l3_width += l3_w
                    max_l3_height = max(max_l3_height, l3_h)

                total_l3_width += max(0, len(l3_dict) - 1) * l3_spacing_x
                # 二级分类尺寸
                l2_w = total_l3_width + padding * 2
                l2_h = max_l3_height + 40  # 标题高度
                l2_layouts.append({
                    'name': l2, 'l3_layouts': l3_layouts,
                    'width': l2_w, 'height': l2_h
                })
                total_l2_width += l2_w
                max_l2_height = max(max_l2_height, l2_h)

            total_l2_width += max(0, len(l2_dict) - 1) * l2_spacing_x + padding * 2
            l1_layouts[l1] = {
                'l2_layouts': l2_layouts,
                'width': total_l2_width,
                'height': max_l2_height,
                'unified_rows': unified_rows
            }
            max_l1_width = max(max_l1_width, total_l2_width)

        max_l1_width = max(max_l1_width, 800)

        # 第二遍：计算位置，同级分类高度对齐
        y_offset = 50
        for l1, l1_layout in l1_layouts.items():
            l2_layouts = l1_layout['l2_layouts']
            actual_width = sum(l['width'] for l in l2_layouts) + max(0, len(l2_layouts) - 1) * l2_spacing_x
            start_x = padding + (max_l1_width - actual_width) / 2

            # 先计算该一级分类下所有二级分类的统一高度
            unified_l2_height = 0
            for l2_layout in l2_layouts:
                l3_layouts = l2_layout['l3_layouts']
                # 计算该二级分类下所有三级分类的最大高度
                max_l3_h = 0
                for l3_layout in l3_layouts:
                    l3_h = l3_layout['height']
                    box_h = l3_h + 35 if l3_layout['name'] != '默认' else l3_h
                    max_l3_h = max(max_l3_h, box_h)
                l2_h = max_l3_h + 50
                unified_l2_height = max(unified_l2_height, l2_h)

            # 同一个二级分类下，所有三级分类也要统一高度
            for l2_layout in l2_layouts:
                l3_layouts = l2_layout['l3_layouts']
                max_l3_h = 0
                for l3_layout in l3_layouts:
                    l3_h = l3_layout['height']
                    box_h = l3_h + 35 if l3_layout['name'] != '默认' else l3_h
                    max_l3_h = max(max_l3_h, box_h)
                l2_layout['unified_l3_height'] = max_l3_h

            l2_x = start_x
            l2_y = y_offset + 45

            for l2_layout in l2_layouts:
                l2_name = l2_layout['name']
                l3_layouts = l2_layout['l3_layouts']
                l2_w = l2_layout['width']
                unified_l3_height = l2_layout['unified_l3_height']

                # 计算三级分类位置
                l3_x = l2_x + padding
                l3_y = l2_y + 40

                for l3_layout in l3_layouts:
                    l3_name = l3_layout['name']
                    l3_nodes = l3_layout['nodes']
                    l3_w = l3_layout['width']
                    l3_h = l3_layout['height']
                    cols = l3_layout['cols']

                    # 只有当三级分类名不是"默认"时才显示三级分类框
                    if l3_name != '默认':
                        # 使用统一高度
                        groups[f"{l1}.{l2_name}.{l3_name}"] = {
                            'x': l3_x, 'y': l3_y, 'w': l3_w, 'h': unified_l3_height,
                            'category': l1, 'level': 3, 'name': l3_name
                        }
                        node_y_start = l3_y + 35
                    else:
                        node_y_start = l3_y

                    # 模型节点位置（支持多行）
                    for i, node in enumerate(l3_nodes):
                        col = i % cols
                        row = i // cols
                        node_x = l3_x + padding + col * model_spacing_x
                        node_y = node_y_start + row * model_spacing_y
                        positions[node['id']] = {
                            'x': node_x, 'y': node_y,
                            'w': node_w, 'h': node_h, 'category_key': l1
                        }

                    l3_x += l3_w + l3_spacing_x

                # 二级分类框使用统一高度
                if l2_name != '默认':
                    groups[f"{l1}.{l2_name}"] = {
                        'x': l2_x, 'y': l2_y, 'w': l2_w, 'h': unified_l2_height,
                        'category': l1, 'level': 2, 'name': l2_name
                    }
                l2_x += l2_w + l2_spacing_x

            # 一级分类框
            l1_h = unified_l2_height + 80
            groups[l1] = {
                'x': padding, 'y': y_offset, 'w': max_l1_width, 'h': l1_h,
                'category': l1, 'level': 1, 'name': l1
            }
            y_offset += l1_h + l1_spacing_y

        return positions, groups

    def _calc_linear_layout(self, nodes: List[dict]):
        """线性布局"""
        positions = {}
        node_w, node_h, spacing = 140, 60, 200
        for i, node in enumerate(nodes):
            positions[node['id']] = {'x': 400, 'y': 50 + i * spacing, 'w': node_w, 'h': node_h, 'category_key': '默认'}
        return positions, {}

    def _add_group_cell(self, parent, name: str, info: dict):
        """添加分类框（支持3级）"""
        cell_id = self.next_id()
        cat = info.get('category', '默认')
        level = info.get('level', 1)
        display_name = info.get('name', name)

        if level == 1:
            # 一级分类框 - 实线大框
            fill, stroke, _ = self._get_category_colors(cat)
            style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};"
                     f"strokeColor={stroke};strokeWidth=2;dashed=0;"
                     f"verticalAlign=top;fontStyle=1;fontSize=14;spacingTop=5;")
        elif level == 2:
            # 二级分类框 - 虚线中框
            style = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;"
                     "strokeColor=#999999;strokeWidth=1;dashed=1;dashPattern=3 3;"
                     "verticalAlign=top;fontStyle=0;fontSize=11;spacingTop=3;fillOpacity=60;")
        else:
            # 三级分类框 - 点线小框
            style = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#fafafa;"
                     "strokeColor=#cccccc;strokeWidth=1;dashed=1;dashPattern=1 2;"
                     "verticalAlign=top;fontStyle=0;fontSize=10;spacingTop=2;fillOpacity=40;")

        cell = ET.SubElement(parent, 'mxCell', {
            'id': cell_id, 'value': html.escape(display_name), 'style': style,
            'vertex': '1', 'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(info['x']), 'y': str(info['y']),
            'width': str(info['w']), 'height': str(info['h']), 'as': 'geometry'
        })

    def _add_node_cell(self, parent, node: dict, pos: dict):
        """添加节点"""
        cell_id = self.next_id()
        name = node.get('name', node.get('id', ''))
        node_id = node.get('id', '')
        cat = pos.get('category_key', '默认')

        _, _, node_fill = self._get_category_colors(cat)
        # 根据节点颜色深浅自动选择字体颜色
        font_color = '#ffffff' if self._is_dark_color(node_fill) else '#333333'

        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={node_fill};"
                 f"strokeColor=#333333;strokeWidth=2;fontColor={font_color};"
                 f"fontStyle=1;fontSize=12;shadow=1;")

        short_id = node_id.split('@')[0] if '@' in node_id else node_id
        label = f"{html.escape(name)}<br><font style='font-size:10px'>{html.escape(short_id)}</font>"

        cell = ET.SubElement(parent, 'mxCell', {
            'id': cell_id, 'value': label, 'style': style, 'vertex': '1', 'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(pos['x']), 'y': str(pos['y']),
            'width': str(pos['w']), 'height': str(pos['h']), 'as': 'geometry'
        })
        return cell_id

    def _add_edge_cell(self, parent, source_id: str, target_id: str, label: str, cardinality: str):
        """添加连线"""
        cell_id = self.next_id()
        # 使用 orthogonalEdgeStyle 正交连线，避免穿过节点
        # noEdgeStyle=0 确保使用边缘样式
        # entryX/entryY/exitX/exitY 控制连接点位置
        style = ("edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;"
                 "jettySize=auto;html=1;strokeColor=#666666;strokeWidth=2;"
                 "fontColor=#333333;fontSize=3;labelBackgroundColor=#ffffff;"
                 "endArrow=classic;endFill=1;jumpStyle=arc;jumpSize=10;"
                 "noEdgeStyle=0;elbow=vertical;")

        edge_label = f"{html.escape(label)}\n({cardinality})" if cardinality else html.escape(label)

        cell = ET.SubElement(parent, 'mxCell', {
            'id': cell_id, 'value': edge_label, 'style': style,
            'edge': '1', 'parent': '1', 'source': source_id, 'target': target_id
        })
        geo = ET.SubElement(cell, 'mxGeometry', {'relative': '1', 'as': 'geometry'})
        ET.SubElement(geo, 'mxPoint', {'x': '0', 'y': '10', 'as': 'offset'})


def parse_models(model_str: str) -> List[str]:
    """解析模型字符串"""
    if '\\' in model_str:
        return [m.strip() for m in model_str.split('\\') if m.strip()]
    return [m.strip() for m in model_str.split(',') if m.strip()]


def main():
    parser = argparse.ArgumentParser(
        description='通用层级关系图生成器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 从 CMDB 获取并生成 drawio
  %(prog)s --from-cmdb "MODEL1\\MODEL2\\MODEL3" -o output.drawio

  # 从 YAML 文件生成 drawio
  %(prog)s --from-yaml data.yaml -o output.drawio

  # 从 CMDB 导出为 YAML（不生成 drawio）
  %(prog)s --from-cmdb "MODEL1\\MODEL2" --export-yaml data.yaml

  # 从 CMDB 导出为 JSON
  %(prog)s --from-cmdb "MODEL1\\MODEL2" --export-json data.json
        '''
    )

    # 数据源
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--from-cmdb', metavar='MODELS', help='从 CMDB 获取模型（反斜杠或逗号分隔）')
    source.add_argument('--from-yaml', metavar='FILE', help='从 YAML 文件加载')
    source.add_argument('--from-json', metavar='FILE', help='从 JSON 文件加载')

    # 输出
    parser.add_argument('-o', '--output', default='topology.drawio', help='输出 drawio 文件')
    parser.add_argument('--export-yaml', metavar='FILE', help='导出为 YAML 文件')
    parser.add_argument('--export-json', metavar='FILE', help='导出为 JSON 文件')
    parser.add_argument('--linear', action='store_true', help='使用线性布局（默认按分类）')
    parser.add_argument('--max-cols', type=int, default=8, help='每行最大模型数量（默认8）')

    # 兼容旧参数
    parser.add_argument('models', nargs='*', help='模型ID列表（兼容旧用法）')

    args = parser.parse_args()

    # 获取数据
    topo = None

    if args.from_yaml:
        print(f"从 YAML 加载: {args.from_yaml}")
        topo = TopologyData.from_file(args.from_yaml)
    elif args.from_json:
        print(f"从 JSON 加载: {args.from_json}")
        topo = TopologyData.from_file(args.from_json)
    elif args.from_cmdb or args.models:
        model_str = args.from_cmdb or ' '.join(args.models)
        model_ids = parse_models(model_str)
        if not model_ids:
            model_ids = ['APP_SYSTEM@ONEMODEL', 'APPLICATION@ONEMODEL', 'HOST']
            print("未指定模型，使用默认示例")
        print(f"从 CMDB 获取 {len(model_ids)} 个模型...")
        fetcher = CMDBDataFetcher()
        topo = fetcher.fetch(model_ids)
    else:
        parser.print_help()
        return

    # 导出数据
    if args.export_yaml:
        Path(args.export_yaml).write_text(topo.to_yaml(), encoding='utf-8')
        print(f"已导出 YAML: {args.export_yaml}")

    if args.export_json:
        Path(args.export_json).write_text(topo.to_json(), encoding='utf-8')
        print(f"已导出 JSON: {args.export_json}")

    # 生成 drawio（除非只导出数据）
    if not (args.export_yaml or args.export_json) or args.output != 'topology.drawio':
        renderer = DrawioRenderer()
        renderer.render(topo, args.output, by_category=not args.linear, max_cols=args.max_cols)


if __name__ == '__main__':
    main()
