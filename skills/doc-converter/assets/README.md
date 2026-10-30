# doc-converter 运行时资产

## mermaid.min.js

- 用途：doc-converter 的 Mermaid 图表离线渲染（md→docx / md→pdf 等）
- 来源：https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js
- 版本：Mermaid 11.x（minified，约 3.5MB）
- 许可：MIT（Mermaid 项目）
- 加载优先级：
  1. `--options mermaid_js=/path/to/mermaid.min.js`
  2. 环境变量 `MERMAID_JS_PATH`
  3. 自动发现本文件（`skills/doc-converter/assets/mermaid.min.js`，从 cwd 或项目开发路径）
  4. 回退 CDN（仅当本文件不存在时）

升级：替换本文件即可；无需改代码。离线环境务必随 skill 一起分发本文件。
