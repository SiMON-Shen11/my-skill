#!/usr/bin/env python3
"""
模块4: 图形边界检测
通过 OCR 匹配"图N"标题, 在标题上方区域做形态学闭运算(连接图形内部分散点线),
找离标题最近的连通域顶部作为图形真实边界。

输出 figures.json:
{
  "pages": [
    {
      "page": 3,
      "figures": [
        {"id": 4, "top_y": 1137, "bottom_y": 1278, "caption_y": 1236, "cx": 1278},
        ...
      ]
    },
    ...
  ]
}

用法:
    python3 figure_detection.py <png_dir> <ocr_dir> <output_json>
"""
import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np


def _imread_unicode(path):
    """cv2.imread 不支持中文/非ASCII路径, 用 np.fromfile + imdecode 兼容 Windows。"""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


RE_FIGURE = re.compile(r'^图(\d+)')

# 形态学闭运算垂直核大小 (连接图形内部分散的点和线)
MORPH_KERNEL_H = 25
# 扫描区域半宽
SCAN_HALF_WIDTH = 200
# 连通域底部到标题的最大距离
MAX_DIST_TO_CAPTION = 80
# 连通域最小面积
MIN_COMPONENT_AREA = 30


def detect_figures_on_page(img, ocr_items: list[dict]) -> list[dict]:
    """检测单页中所有图形的边界。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 235, 255, cv2.THRESH_BINARY_INV)
    h, w = binary.shape
    figures = []

    for it in ocr_items:
        text = it["content"].strip()
        m = RE_FIGURE.match(text)
        if not m:
            continue
        fig_id = int(m.group(1))
        cap_y1 = it["top_left_y"]
        cap_y2 = it["bottom_right_y"]
        cap_cx = (it["top_left_x"] + it["bottom_right_x"]) // 2

        # 取标题上方较宽区域
        sx1 = max(0, cap_cx - SCAN_HALF_WIDTH)
        sx2 = min(w, cap_cx + SCAN_HALF_WIDTH)
        roi = binary[0:cap_y1, sx1:sx2]

        # 垂直闭运算: 连接图形内部分散点线
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, MORPH_KERNEL_H))
        closed = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, kernel)

        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            closed, connectivity=8)

        fig_top = cap_y1 - 80  # fallback
        for lbl in range(1, n_labels):
            x, y, bw, bh, area = stats[lbl]
            comp_bottom = y + bh
            if cap_y1 - comp_bottom < MAX_DIST_TO_CAPTION and area > MIN_COMPONENT_AREA:
                fig_top = min(fig_top, y)

        figures.append({
            "id": fig_id,
            "top_y": int(fig_top),
            "bottom_y": int(cap_y2),
            "caption_y": int(cap_y1),
            "cx": int(cap_cx),
        })

    return figures


def run_figure_detection(png_dir: str, ocr_dir: str, output_json: str) -> dict:
    """对所有页做图形检测。"""
    png_dir = Path(png_dir)
    ocr_dir = Path(ocr_dir)
    pngs = sorted(png_dir.glob("page_*.png"))
    if not pngs:
        print(f"[ERROR] {png_dir} 中没有 page_*.png", file=sys.stderr)
        sys.exit(1)

    pages_result = []
    total = 0
    for png in pngs:
        page_num = int(png.stem.split("_")[1])
        img = _imread_unicode(str(png))
        if img is None:
            print(f"  [WARN] 无法读取 {png}, 跳过")
            continue

        ocr_file = ocr_dir / f"ocr_page_{page_num:02d}.json"
        if not ocr_file.exists():
            print(f"  [WARN] 未找到 {ocr_file}, 跳过")
            continue
        items = json.load(open(ocr_file, encoding="utf-8")).get("ocr_result", [])
        items.sort(key=lambda r: (r["top_left_y"], r["top_left_x"]))

        figures = detect_figures_on_page(img, items)
        pages_result.append({"page": page_num, "figures": figures})
        total += len(figures)
        info = [(f["id"], f["top_y"]) for f in figures]
        print(f"  page {page_num}: {len(figures)} 个图形 {info}")

    result = {"pages": pages_result, "total": total}
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nDone: {total} 个图形 -> {out}")
    return result


def main():
    ap = argparse.ArgumentParser(description="试卷图形边界检测")
    ap.add_argument("png_dir", help="page_*.png 所在目录")
    ap.add_argument("ocr_dir", help="ocr_page_*.json 所在目录")
    ap.add_argument("output_json", help="输出 figures.json 路径")
    args = ap.parse_args()
    run_figure_detection(args.png_dir, args.ocr_dir, args.output_json)


if __name__ == "__main__":
    main()
