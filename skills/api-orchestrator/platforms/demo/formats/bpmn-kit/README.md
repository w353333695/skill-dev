# bpmn-kit —— BPMN 自动布局（ITSM 流程图 DI 重排）

relayout.py：读入 bpmnXML（含烂 DI 或纯语义无 DI），重算全部节点坐标+正交连线，流程语义零改动。
- 算法：Kahn 最长路径分层（DFS 灰边剔回边）→ barycenter 列内排序 → dominator 必经链锚主轴
  → 回环侧支挂上/下 → 正交折线 + 跨列/回边绕行通道（嵌套深度+贪心选侧）
- 入口：CLI `python3 relayout.py <in> [-o out]`；库 `from relayout import relayout_xml`（XML 串进出）
- 领域适配点（为何在 platforms 不在 skill）：flowable: 扩展属性、EasyOps parser 的
  incoming/outgoing 回填、userTask 100x80/网关 50x50 尺寸约定、bpmn2:→bpmn: 前缀重写（URI 等价）
- 使用方：flows/build-process.yaml（设计时生成即布局）/ flows/relayout-process-diagram.yaml（存量补救）
