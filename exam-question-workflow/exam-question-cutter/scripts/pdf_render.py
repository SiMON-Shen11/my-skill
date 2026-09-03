#!/usr/bin/env python3
"""
模块1: PDF 渲染
将中学试卷 PDF 按页渲染为高清 PNG, 供后续 OCR 和切分使用。

用法:
    python3 pdf_render.py <input.pdf> <output_dir> [--dpi 200]

输出:
    <output_dir>/page_01.png, page_02.png, ...
"""
import argparse
import sys
from pathlib import Path


def render_pdf(pdf_path: str, output_dir: str, dpi: int = 200) -> list[str]:
    """将 PDF 每页渲染为 PNG, 返回生成的图片路径列表。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[ERROR] 需要 PyMuPDF: pip install pymupdf", file=sys.stderr)
        sys.exit(1)

    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    paths = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        fname = out / f"page_{i+1:02d}.png"
        pix.save(str(fname))
        paths.append(str(fname))
        print(f"  rendered page {i+1}/{len(doc)}: {pix.width}x{pix.height} -> {fname.name}")
    doc.close()
    return paths


def main():
    ap = argparse.ArgumentParser(description="PDF 渲染为高清 PNG")
    ap.add_argument("pdf", help="输入 PDF 文件路径")
    ap.add_argument("output_dir", help="输出目录")
    ap.add_argument("--dpi", type=int, default=200, help="渲染 DPI (默认 200)")
    args = ap.parse_args()
    paths = render_pdf(args.pdf, args.output_dir, args.dpi)
    print(f"\nDone: {len(paths)} pages -> {args.output_dir}")


if __name__ == "__main__":
    main()
