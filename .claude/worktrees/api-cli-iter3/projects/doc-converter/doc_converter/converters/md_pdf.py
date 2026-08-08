"""Markdown → PDF 转换器

引擎优先级（轻 → 重）：

1. **pandoc3 + typst**（默认主路径）
   - pandoc 3.x 由 pypandoc-binary 自带、typst 为 PyPI 包，均走 pip 安装，免系统 TexLive。
   - 原生中文（typst 0.13+ 自动 CJK 字体回退）、表格/代码高亮由 typst 内置。
   - Mermaid 预先光栅化为 PNG 再以 ![]() 嵌入（需 [render] 的 playwright；缺失则回退为代码块）。
2. **系统 pandoc + xelatex**（回退）：md→pdf 老路径，依赖 TexLive 宏包，不渲染 mermaid。
3. **playwright + chromium**（最后回退）：浏览器内渲染，mermaid 客户端 JS 渲染，需 [render] + install-deps。
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import BaseConverter, ConvertResult, register


def _has_pypandoc() -> bool:
    """pypandoc-binary 是否可用（自带 pandoc 3.x，无需系统 pandoc）。"""
    try:
        import pypandoc
        pypandoc.get_pandoc_version()  # 触发自带 pandoc 探测，确认可执行
        return True
    except Exception:
        return False


def _has_typst_pkg() -> bool:
    try:
        import typst  # noqa: F401
        return True
    except ImportError:
        return False


def _has_typst_path() -> bool:
    """pandoc3+typst 主路径是否就绪。"""
    return _has_pypandoc() and _has_typst_pkg()


def _has_pandoc_pdf() -> bool:
    """系统 pandoc + xelatex（回退路径）。"""
    return bool(shutil.which("pandoc")) and bool(shutil.which("xelatex"))


def _has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


@register
class MdToPdf(BaseConverter):
    name = "md-pdf"
    source_formats = ["md", "markdown"]
    target_formats = ["pdf"]
    description = "Markdown 转 PDF (pandoc3+typst 优先, 回退 xelatex/playwright)"
    # pandoc/typst 是外部二进制/包，自行 check_dependencies 探测，不在 dependencies 列。
    dependencies = []

    def check_dependencies(self) -> tuple[bool, list[str]]:
        if _has_typst_path() or _has_pandoc_pdf() or _has_playwright():
            return True, []
        return False, [
            "pandoc3+typst (pip install pypandoc-binary typst) "
            "或 pandoc+xelatex(系统) 或 doc-converter[render]"
        ]

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        if _has_typst_path():
            return self._via_typst(input_path, output_path, **options)
        if _has_pandoc_pdf():
            return self._via_pandoc_xelatex(input_path, output_path, **options)
        return self._via_playwright(input_path, output_path, **options)

    # ----- 主路径：pandoc3 + typst -----
    def _via_typst(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        import pypandoc
        import typst
        from .mermaid_image import inline_mermaid_as_images

        text = input_path.read_text(encoding="utf-8")
        theme = options.get("theme", "default")
        tmp = Path(tempfile.mkdtemp(prefix="mdpdf_typst_"))
        try:
            # 1. Mermaid 预处理：成功→![](mermaid_i.png)；失败（缺 playwright）→还原代码块，不阻断
            text, mermaid_imgs = inline_mermaid_as_images(text, tmp, theme)
            # 2. 其他图片重定位到 tmp（typst root 单目录）；网络/缺失图降级为文本
            text = self._relocate_images(text, input_path, tmp)
            # 3. Markdown → typst 源（禁 auto_identifiers：typst label 不支持中文）
            typ_path = tmp / "doc.typ"
            pypandoc.convert_text(text, "typst", format="markdown-auto_identifiers", outputfile=str(typ_path))
            self._fix_typst_source(typ_path)
            # 4. typst → PDF（root=tmp 解析 mermaid/图片相对路径）
            typst.compile(str(typ_path), output=str(output_path), root=str(tmp))
            extra = f"，{len(mermaid_imgs)} 个 Mermaid 图已嵌入" if mermaid_imgs else ""
            return ConvertResult(
                True, output_path=output_path,
                message=f"Markdown 已转为 PDF (pandoc3+typst){extra}",
            )
        except Exception as e:
            # 主路径失败 → 尝试回退链
            if _has_pandoc_pdf():
                return self._via_pandoc_xelatex(input_path, output_path, **options)
            if _has_playwright():
                return self._via_playwright(input_path, output_path, **options)
            return ConvertResult(False, message=f"typst 转 PDF 失败: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _relocate_images(md_text: str, input_path: Path, tmp: Path) -> str:
        """把 Markdown 图片引用重定位到 tmp（受 typst root 单目录约束）。

        - Mermaid 图（inline_mermaid_as_images 已生成于 tmp）：保留引用；
        - 用户本地图片：复制到 tmp，引用改为文件名；
        - 网络/缺失图：降级为文本占位（typst image 不支持远程/不存在路径，会编译失败）。
        """

        def repl(m):
            alt, src = m.group(1), m.group(2).strip()
            if src.startswith(("http://", "https://", "data:", "mailto:")):
                return f"*［图片：{alt or src}］*"
            p = Path(src)
            if not p.is_absolute():
                if (tmp / src).exists():  # mermaid 图已在 tmp
                    return f"![{alt}]({src})"
                p = (input_path.parent / p).resolve()
            if p.exists():
                dst = tmp / p.name
                shutil.copy2(p, dst)
                return f"![{alt}]({p.name})"
            return f"*［图片缺失：{alt or src}］*"

        return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, md_text)

    @staticmethod
    def _fix_typst_source(typ_path) -> None:
        """修正 pandoc→typst 的已知不兼容产物（否则 typst 编译中断）。

        - `#horizontalrule`：pandoc HorizontalRule 输出，typst 无此内置 → 原生水平线；
        - `#link(<label>)[body]`：typst label 不支持中文，内部锚点链接降级为纯文本（外链 url 不受影响）。
        """
        text = Path(typ_path).read_text(encoding="utf-8")
        text = re.sub(r"^#horizontalrule\s*$", "#line(length: 100%)", text, flags=re.MULTILINE)
        text = re.sub(r'#link\(<[^>]*>\)\[(.*?)\]', r"\1", text)
        Path(typ_path).write_text(text, encoding="utf-8")

    # ----- 回退路径 1：系统 pandoc + xelatex -----
    def _via_pandoc_xelatex(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        """pandoc + xelatex 生成 PDF（支持中文，免 chromium；不渲染 mermaid）。

        pandoc 默认 latex template 引 ``\\usepackage{lmodern}``，系统 TexLive 若缺
        lmodern.sty 会编译失败；取默认 template 去掉该行（完整环境去掉亦无副作用）。
        """
        default = subprocess.run(
            ["pandoc", "-D", "latex"], capture_output=True, text=True, check=True
        ).stdout
        tmpl = default.replace(r"\usepackage{lmodern}" + "\n", "")
        with tempfile.NamedTemporaryFile(
            suffix=".tex", mode="w", encoding="utf-8", delete=False
        ) as f:
            f.write(tmpl)
            tmpl_path = f.name
        try:
            cjk = options.get("cjk_font", "Noto Sans CJK SC")
            cmd = [
                "pandoc", str(input_path), "-o", str(output_path),
                "--pdf-engine=xelatex", f"--template={tmpl_path}",
                f"-VCJKmainfont={cjk}", f"-Vmainfont={cjk}",
                "-V", "geometry:margin=2cm",
            ]
            if options.get("landscape"):
                cmd += ["-V", "geometry:landscape"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                if _has_playwright():
                    return self._via_playwright(input_path, output_path, **options)
                return ConvertResult(
                    False, message=f"pandoc 生成 PDF 失败:\n{r.stderr.strip()[:500]}"
                )
        finally:
            Path(tmpl_path).unlink(missing_ok=True)
        return ConvertResult(
            True, output_path=output_path, message="Markdown 已转为 PDF (pandoc+xelatex)"
        )

    # ----- 回退路径 2：playwright（浏览器内渲染，含 mermaid 客户端渲染）-----
    def _via_playwright(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        from .md_html import md_to_html_body, build_full_html
        from .renderer import html_to_pdf

        text = input_path.read_text(encoding="utf-8")
        title = options.get("title", input_path.stem)
        body, has_mermaid, extra_css = md_to_html_body(text, input_path=input_path)

        # 高亮 CSS（若有代码块）+ mermaid 脚本都注入 <head>，
        # 否则 PDF 里代码块只有 .codehilite class 却无颜色
        extra_head = ""
        if extra_css:
            extra_head += f"<style>\n{extra_css}\n</style>\n"
        if has_mermaid:
            extra_head += (
                '<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>\n'
                '<script>mermaid.initialize({startOnLoad: true});</script>'
            )
        html = build_full_html(body, title, extra_head)

        wait_ms = 3000 if has_mermaid else 500
        html_to_pdf(html, output_path, wait_ms=wait_ms, **options)
        return ConvertResult(
            True, output_path=output_path, message="Markdown 已转为 PDF (playwright)"
        )
