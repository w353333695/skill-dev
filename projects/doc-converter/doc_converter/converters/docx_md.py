"""
Word (.docx) -> Markdown 转换器。

使用 pandoc 将 .docx 转换为 GFM Markdown，并把文档内嵌图片
提取到输出 md 所在目录下的 `_assets/<文件名去扩展名>/` 中
（扁平化掉 pandoc 默认多建的 `media/` 子目录层）。

对于文档里以绝对路径/外链形式存在、未真正嵌入的图片引用
（某些导出工具会残留指向源服务器本地路径的死链），
保留引用并在转换结果中统一给出警告——不针对任何特定系统路径。

依赖：系统需安装 pandoc（非 pip 包）。
    macOS:   brew install pandoc
    Linux:   apt-get install pandoc  /  yum install pandoc
    Windows: 见 https://pandoc.org/installing.html
"""

import re
import shutil
import subprocess
from pathlib import Path

from .base import BaseConverter, ConvertResult, register


@register
class DocxToMarkdownConverter(BaseConverter):
    """Word 文档转 Markdown（pandoc，图片提取到 _assets/<文件名>/）"""

    name = "docx-md"
    source_formats = ["docx"]
    target_formats = ["md", "markdown"]
    description = "Word 转 Markdown (pandoc，图片提取到 _assets/<文件名>/)"
    # pandoc 是系统二进制而非 pip 包，由 check_dependencies 单独检测
    dependencies = []

    def check_dependencies(self) -> tuple[bool, list[str]]:
        """pandoc 为系统工具，不能用 __import__ 检测，改用 which。"""
        if shutil.which("pandoc") is None:
            return False, ["pandoc"]
        return True, []

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        """
        将 docx 转为 Markdown。

        Args:
            input_path: 输入 .docx 文件
            output_path: 输出 .md 文件
            **options:
                media_dir: 自定义图片目录（默认 _assets/<输入文件名去扩展名>/，
                           相对输出 md 所在目录；可传绝对路径）

        Returns:
            ConvertResult（metadata 含 images_extracted / refs_fixed / missing_refs）
        """
        if shutil.which("pandoc") is None:
            return ConvertResult(
                success=False,
                message="缺少系统依赖 pandoc，请先安装："
                "macOS `brew install pandoc`；Linux `apt-get install pandoc`；"
                "Windows 见 https://pandoc.org/installing.html",
            )

        input_path = Path(input_path)
        output_path = Path(output_path)
        out_dir = output_path.resolve().parent
        out_dir.mkdir(parents=True, exist_ok=True)
        # pandoc 在 out_dir 下运行，传入绝对路径避免被 cwd 影响
        input_abs = str(input_path.resolve())
        output_abs = str(output_path.resolve())

        # —— 计算图片目录 ——
        # 默认 ./_assets/<输入文件名去扩展名>/，相对输出 md 所在目录
        stem = input_path.stem
        media_dir_opt = options.get("media_dir")
        if media_dir_opt:
            opt_path = Path(str(media_dir_opt))
            if opt_path.is_absolute():
                abs_media_dir = opt_path
                extract_arg = str(opt_path)  # 绝对路径：md 中 src 也会是绝对路径
            else:
                abs_media_dir = out_dir / opt_path
                extract_arg = str(opt_path)  # 相对 out_dir
        else:
            extract_arg = f"_assets/{stem}"
            abs_media_dir = out_dir / extract_arg

        # pandoc --extract-media 会在 extract_arg 下固定再建 media/ 子目录
        abs_media_subdir = abs_media_dir / "media"
        # 清理可能存在的旧 media 子目录，避免残留混淆
        if abs_media_subdir.exists():
            shutil.rmtree(abs_media_subdir)

        # —— 调用 pandoc ——
        cmd = [
            "pandoc", input_abs,
            "-t", "gfm",
            f"--extract-media={extract_arg}",
            "-o", output_abs,
        ]
        try:
            proc = subprocess.run(
                cmd, cwd=str(out_dir), capture_output=True, text=True
            )
        except Exception as e:  # pragma: no cover
            return ConvertResult(success=False, message=f"调用 pandoc 失败: {e}")
        if proc.returncode != 0:
            return ConvertResult(
                success=False,
                message=f"pandoc 转换失败: "
                f"{(proc.stderr or proc.stdout).strip()}",
            )

        if not output_path.exists():
            return ConvertResult(success=False, message="pandoc 未生成输出文件")

        # —— 扁平化：把 media/ 下的图片提到上级 ——
        moved = 0
        if abs_media_subdir.exists():
            for f in abs_media_subdir.iterdir():
                if f.is_file():
                    target = abs_media_dir / f.name
                    if target.exists():
                        target = abs_media_dir / f"dup_{moved}_{f.name}"
                    shutil.move(str(f), str(target))
                    moved += 1
            try:
                abs_media_subdir.rmdir()
            except OSError:
                # 目录非空（有子目录等异常情况），保留不影响结果
                pass

        # —— 修正 md 中图片引用路径：去掉 media/ 层 ——
        # pandoc 写入的 src 形如 "<extract_arg>/media/imageN.png"，
        # 用精确字符串替换避免误伤正文。
        content = output_path.read_text(encoding="utf-8")
        old_prefix = f"{extract_arg}/media/"
        new_prefix = f"{extract_arg}/"
        n_fixed = content.count(old_prefix)
        content = content.replace(old_prefix, new_prefix)

        # —— 检测缺失/外链图片引用（通用，不匹配任何特定系统路径） ——
        warnings: list[str] = []
        seen_warn: set[str] = set()

        def _check_ref(url: str) -> None:
            url = url.strip()
            if not url:
                return
            # 去掉 markdown 图片语法里 "url title" 的 title 部分
            url = url.split()[0]
            if url.startswith(("http://", "https://")):
                return  # 网络图片，保留不报警
            # 绝对路径 / 相对路径统一做文件存在性检查：
            # 本次刚提取出的图片即使以绝对路径引用也存在，不应误报；
            # 真正的死链（如导出工具残留的源服务器本地路径）文件不存在才报警。
            if url.startswith("/") or (len(url) > 2 and url[1] == ":"):
                chk = Path(url)
            else:
                chk = out_dir / url
            if not chk.exists() and url not in seen_warn:
                warnings.append(url)
                seen_warn.add(url)

        # markdown 图片语法 ![](url)
        for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", content):
            _check_ref(m.group(1))
        # HTML <img src="url">
        for m in re.finditer(r'<img[^>]+src="([^"]+)"', content):
            _check_ref(m.group(1))

        output_path.write_text(content, encoding="utf-8")

        # —— 组装结果 ——
        parts = [f"已转换 {input_path.name} -> {output_path.name}"]
        parts.append(f"图片提取 {moved} 张到 {extract_arg}/")
        parts.append(f"修正图片引用 {n_fixed} 处")
        if warnings:
            preview = warnings[:5]
            more = "" if len(warnings) <= 5 else f" …等共 {len(warnings)} 处"
            parts.append(f"⚠️ {len(warnings)} 处图片引用可能缺失/为外链: "
                         f"{preview}{more}")

        return ConvertResult(
            success=True,
            output_path=output_path,
            message="；".join(parts),
            metadata={
                "media_dir": str(abs_media_dir),
                "media_dir_ref": extract_arg,
                "images_extracted": moved,
                "refs_fixed": n_fixed,
                "missing_refs": warnings,
            },
        )
