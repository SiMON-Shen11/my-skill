#!/usr/bin/env python3
"""
升级模块 1: 文字层 OCR (电子版教材专用)
从带文字层的 PDF 直接提取文本块 + 坐标 + 字号 + 字体, 生成与底座 OCR 一致的
ocr_page_XX.json 格式。电子版教材无需 OCR 即可获得精确坐标, 且字号/字体信息
是层级识别(章/节/小节/课时标题)的重要依据。

输出:
    <ocr_dir>/ocr_page_01.json ... 
    每个文件: {"ocr_result": [{"content","type","top_left_x","top_left_y",
                               "bottom_right_x","bottom_right_y","font_size","font"}]}

坐标单位 = 渲染像素 (默认 200 DPI), 与底座 crop.py 的页面图片坐标系一致。
用法:
    python pdf_text_ocr.py <input.pdf> <ocr_dir> [--dpi 200]
"""
import argparse
import json
import sys
from pathlib import Path

import fitz


def text_to_ocr(pdf_path: str, ocr_dir: str, dpi: int = 200) -> list[str]:
    """从 PDF 文字层提取结构化文本块, 输出 ocr_page_XX.json, 返回文件列表。"""
    out = Path(ocr_dir)
    out.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0

    doc = fitz.open(pdf_path)
    files = []
    for pno, page in enumerate(doc, start=1):
        d = page.get_text("dict")
        result = []
        for block in d.get("blocks", []):
            if block.get("type") != 0:  # 0=文字块, 跳过图片块
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans)
                if not text.strip():
                    continue
                x0 = min(s["bbox"][0] for s in spans)
                y0 = min(s["bbox"][1] for s in spans)
                x1 = max(s["bbox"][2] for s in spans)
                y1 = max(s["bbox"][3] for s in spans)
                size = max(s["size"] for s in spans)
                font = spans[0]["font"]
                result.append({
                    "content": text,
                    "type": "text",
                    "top_left_x": round(x0 * zoom, 1),
                    "top_left_y": round(y0 * zoom, 1),
                    "bottom_right_x": round(x1 * zoom, 1),
                    "bottom_right_y": round(y1 * zoom, 1),
                    "font_size": round(size * zoom, 1),
                    "font": font,
                })
        fname = out / f"ocr_page_{pno:02d}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump({"ocr_result": result}, f, ensure_ascii=False, indent=1)
        files.append(str(fname))
        print(f"  text-layer page {pno}: {len(result)} 行 -> {fname.name}")
    doc.close()
    return files


def main():
    ap = argparse.ArgumentParser(description="从 PDF 文字层提取结构化 OCR JSON")
    ap.add_argument("pdf", help="输入 PDF")
    ap.add_argument("ocr_dir", help="OCR 输出目录")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()
    files = text_to_ocr(args.pdf, args.ocr_dir, args.dpi)
    print(f"\nDone: {len(files)} pages -> {args.ocr_dir}")


if __name__ == "__main__":
    main()
