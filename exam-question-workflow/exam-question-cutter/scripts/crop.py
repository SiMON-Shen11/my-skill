#!/usr/bin/env python3
"""
模块5: 题目切分
根据版面分析 (markers.json) 和图形检测 (figures.json) 结果, 按完整性优先原则切割每题。
核心边界规则:
- 上边界 = 题号行 - PADDING; 若本题图形顶部高于题号行则向上延伸到图形顶部
- 下边界 = 本题范围内所有 OCR 内容最大 y + CONTENT_MARGIN (不被下一题图形收紧)
- 上边界不进入前一个大题标题区域
- 下边界夹紧到下一题题号 - 2px 和页脚
- 相邻题目在图形区域允许重叠, 优先保证每题自身内容完整
- 跨页题: 上页从题号到页底 + 下页从页顶到下一题题号前, 垂直拼接
输出:
    output/questions/选择题/q01.png, ...
    output/questions/填空题/q11.png, ...
    output/questions/解答题/q17.png, ...
    output/meta.json
    output/overlay_page_XX.png (整页预览)
用法:
    python3 crop.py <png_dir> <ocr_dir> <markers.json> <figures.json> <output_dir>
"""
import argparse
import json
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

# ---------- 配置 ----------
PADDING = 28
PAGE_LEFT = 150
PAGE_RIGHT = 1510
AUTO_MARGIN_PAD = 12
CONTENT_MARGIN = 50
FIG_TOP_MARGIN = 10
MIN_HEIGHT = 180
CROSS_PAGE_THRESHOLD = 400
CROSS_NEXT_PAGE_TOP = 200


def _get_page_markers(markers_data: dict, page_num: int) -> list[dict]:
    for p in markers_data["pages"]:
        if p["page"] == page_num:
            return p["markers"]
    return []


def _get_page_figures(figures_data: dict, page_num: int) -> list[dict]:
    for p in figures_data["pages"]:
        if p["page"] == page_num:
            return p["figures"]
    return []


def detect_content_bounds(img: np.ndarray) -> tuple[int, int]:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    top_skip = min(150, h // 6)
    bottom_skip = min(100, h // 10)
    roi = gray[top_skip:h - bottom_skip, :]
    _, binary = cv2.threshold(roi, 200, 255, cv2.THRESH_BINARY_INV)
    col_proj = np.sum(binary, axis=0)
    content_cols = np.where(col_proj > 0)[0]
    if len(content_cols) == 0:
        return PAGE_LEFT, PAGE_RIGHT
    left = max(0, int(content_cols.min()) - AUTO_MARGIN_PAD)
    right = min(w, int(content_cols.max()) + AUTO_MARGIN_PAD)
    return left, right


def _assign_figures_to_questions(figures: list[dict], questions: list[dict],
                                 footer_y: int) -> dict:
    q_figures = {}
    for fig in figures:
        for i, q in enumerate(questions):
            qy = q["y"]
            ny = questions[i + 1]["y"] if i + 1 < len(questions) else footer_y
            if qy <= fig["caption_y"] < ny:
                q_figures.setdefault(q["num"], []).append(fig)
                break
    return q_figures


def _detect_fraction_range(items: list[dict], y_min: int, y_max: int) -> tuple[int, int] | None:
    """检测区域内的分式(垂直堆叠的分子/分母 OCR 块对), 返回所有分式块的 (min_y, max_y)。

    分式特征: 两个宽度不大的块垂直堆叠, 间距 0~12px, x 范围重叠。
    分子/分母常被 PaddleOCR 识别为独立小块, 其垂直范围可能超出题号定义的题目区间,
    导致切图时分子顶部或分母底部被裁。
    """
    frac_ids = set()
    # 分子 top_left_y 必须 < y_max(下一题题号), 确保是本题的分式;
    # 分母 bottom_right_y 可超过 y_max(向下延伸), 由调用方控制下边界上限
    candidates = [it for it in items if y_min - 20 <= it["top_left_y"] < y_max]
    for i, a in enumerate(candidates):
        wa = a["bottom_right_x"] - a["top_left_x"]
        ha = a["bottom_right_y"] - a["top_left_y"]
        if wa > 150 or ha > 30:
            continue
        for b in candidates:
            if b is a:
                continue
            wb = b["bottom_right_x"] - b["top_left_x"]
            hb = b["bottom_right_y"] - b["top_left_y"]
            if wb > 150 or hb > 30:
                continue
            gap = b["top_left_y"] - a["bottom_right_y"]
            if -2 <= gap <= 14:
                overlap = (min(a["bottom_right_x"], b["bottom_right_x"])
                           - max(a["top_left_x"], b["top_left_x"]))
                if overlap > 4:
                    frac_ids.add(id(a))
                    frac_ids.add(id(b))
    if not frac_ids:
        return None
    ys = []
    for it in candidates:
        if id(it) in frac_ids:
            ys.append(it["top_left_y"])
            ys.append(it["bottom_right_y"])
    return min(ys), max(ys)


def compute_bboxes(markers: list[dict], items: list[dict], page_h: int,
                   page_w: int, figures: list[dict],
                   page_left: int = PAGE_LEFT, page_right: int = PAGE_RIGHT) -> list[dict]:
    questions = [m for m in markers if m["type"] == "question"]
    footers = [m for m in markers if m["type"] == "footer"]
    footer_y = min((f["y"] for f in footers), default=page_h)
    q_figures = _assign_figures_to_questions(figures, questions, footer_y)
    # 用本页 OCR 文本的实际 x 范围扩展左右边界, 避免默认 PAGE_LEFT/RIGHT 或
    # auto-margin 检测过紧导致边缘字符(行首题号/行尾标点/公式)被裁
    text_lefts = [it["top_left_x"] for it in items
                  if it.get("top_left_y", 0) < page_h]
    text_rights = [it["bottom_right_x"] for it in items
                   if it.get("bottom_right_y", 0) > 0]
    page_text_l = min(text_lefts) if text_lefts else page_left
    page_text_r = max(text_rights) if text_rights else page_right
    results = []
    prev_y2 = 0
    for i, q in enumerate(questions):
        top_y = q["y"]
        next_markers = [m for m in markers if m["y"] > q["y"]]
        next_marker_y = next_markers[0]["y"] if next_markers else footer_y
        next_q = questions[i + 1] if i + 1 < len(questions) else None
        prev_sections = [m for m in markers if m["type"] == "section" and m["y"] < top_y]
        prev_section_bottom = max(
            (m["item"]["bottom_right_y"] for m in prev_sections), default=0)
        content_items = [
            it for it in items
            if it["top_left_y"] >= top_y - 5
            and it["top_left_y"] < next_marker_y
            and it["top_left_x"] >= page_left - 30
        ]
        content_max_y = max(
            (it["bottom_right_y"] for it in content_items),
            default=top_y + 40,
        )
        y1 = top_y - PADDING
        if q["num"] in q_figures:
            fig_top = min(f["top_y"] for f in q_figures[q["num"]])
            if fig_top < top_y:
                y1 = min(y1, fig_top - FIG_TOP_MARGIN)
        y1 = max(y1, prev_section_bottom + 8)
        # 不侵入上一题内容: 上边界不低于上一题下边界 (两题紧凑时避免残留上一题文本/选项)
        y1 = max(y1, prev_y2)
        # 本题内容可能在题号上方(如行列式分子行、分式分子与题号同行但更高),
        # 扫描题号上方80px内且在上一题下边界之后的OCR块, 若有则上边界扩展到
        # 内容顶部-8, 避免分子/行列式首行被裁。prev_y2 约束确保不侵入上一题内容。
        above_items = [it for it in items
                       if max(prev_y2, top_y - 80) <= it["top_left_y"] < top_y
                       and it["top_left_x"] >= page_left - 30]
        if above_items:
            content_min_y = min(it["top_left_y"] for it in above_items)
            y1 = min(y1, content_min_y - 8)
        y2 = content_max_y + CONTENT_MARGIN
        if next_q:
            # 以下一题题号 - 2 作为下边界, 确保当前题内容完整
            # (题号坐标比OCR段坐标更可靠)
            y2 = next_q["y"] - 2
            # 下一题内容可能向上延伸(大括号"{"比题号高、分式分子比题号高),
            # 检测下一题题号上方是否有属于下一题的 OCR 块(底部越过题号行),
            # 若有则下边界夹紧到该内容顶部 - 2, 避免当前题图片混入下一题内容
            # (如方程组分子)导致分母被截断, 同时避免下一题上边界被卡住裁掉大括号顶
            above_next = [it for it in items
                          if next_q["y"] - 100 <= it["top_left_y"] < next_q["y"]
                          and it["top_left_x"] >= page_left - 30
                          and it["bottom_right_y"] > next_q["y"] - 5]
            if above_next:
                next_content_top = min(it["top_left_y"] for it in above_next)
                y2 = min(y2, next_content_top - 2)
        # 不越过大题标题: 下一个标记(题目/大题标题/页脚)前即停止,
        # 确保 "第二部分/一、/二、/三、" 等大题标题不出现在单题图内
        y2 = min(y2, next_marker_y - 2, footer_y - 4)
        # 分式边界扩展: 含分式时分子/分母常被 OCR 识别为独立小块,
        # 其垂直范围可能超出题号定义的题目区间(分子在题号上方、分母在下一题题号下方),
        # 主动扩展上下边界到分式的实际范围, 保证分式完整不被截断。
        # 搜索范围: 分子 top_left_y 必须在 [题号上方30px, 下一题题号) 内(属于本题),
        # 分母 bottom_right_y 可超过下一题题号(向下延伸), 但不会把下一题的分式算进来。
        frac_y_max = next_q["y"] if next_q else content_max_y + 50
        frac_range = _detect_fraction_range(items, top_y - 30, frac_y_max)
        if frac_range:
            y1 = min(y1, frac_range[0] - 8)
            # 分式分母可能在下一题题号下方, 下边界取 max 不受 next_q.y - 2 约束,
            # 但最多延伸到下一题题号下方50px(避免包含下一题题干)
            y2 = max(y2, min(frac_range[1] + 8, frac_y_max + 50))
        # 左右边界: 取 (默认/auto-margin 边界) 与 (本页 OCR 文本范围) 的并集, 保证边缘内容不被裁
        x1 = max(0, min(page_left - 10, page_text_l - 15))
        y1 = max(0, y1)
        x2 = min(page_w, max(page_right + 10, page_text_r + 15))
        y2 = min(page_h, max(y1 + 10, y2))
        prev_y2 = y2
        results.append({
            "num": q["num"],
            "type": q.get("qtype", "未分类"),
            "day": q.get("day", 0),
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "question_text": q["text"][:60],
            "has_figure": q["num"] in q_figures,
            "content_max_y": int(content_max_y),
        })
    return results


def _detect_cross_page(markers_data: dict, page_num: int, page_h: int) -> dict | None:
    """检测当前页最后一题是否跨页。返回跨页信息或None。"""
    page_markers = _get_page_markers(markers_data, page_num)
    questions = [m for m in page_markers if m["type"] == "question"]
    if not questions:
        return None
    last_q = questions[-1]
    # 整表题(镶嵌多个题目的大表格页)的 content_bottom 是预设的表格底部,
    # 距页底可能 <400 但实际不跨页 → 跳过跨页判定
    if last_q.get("is_table"):
        return None
    next_page_markers = _get_page_markers(markers_data, page_num + 1)
    next_questions = [m for m in next_page_markers if m["type"] == "question"]
    if not next_questions:
        return None
    first_next_q = next_questions[0]
    is_day_switch = first_next_q["num"] < last_q["num"]
    # 用题目内容底(而非题号 y)判断是否接近页底: 跨页题的题干常延伸到页底,
    # 但题号可能不够靠下(如打卡册 p1 题8 题干在页底、选项在 p2 顶)
    last_content_bottom = last_q.get("content_bottom", last_q["y"])
    if (last_content_bottom > page_h - CROSS_PAGE_THRESHOLD
            and first_next_q["y"] > CROSS_NEXT_PAGE_TOP
            and not is_day_switch):
        return {
            "num": last_q["num"],
            "page": page_num,
            "y": last_q["y"],
            "next_page": page_num + 1,
            "next_q_y": first_next_q["y"],
            "qtype": last_q.get("qtype", "未分类"),
            "day": last_q.get("day", 0),
        }
    return None


def draw_overlay(img, markers, figures, qs) -> np.ndarray:
    vis = img.copy()
    h, w = vis.shape[:2]
    for r in qs:
        x1, y1, x2, y2 = r["bbox"]
        color = (0, 120, 255) if r["num"] % 2 == 0 else (255, 100, 0)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 3)
        cv2.putText(vis, f"Q{r['num']}", (x1 + 8, y1 + 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 3)
        qtype_map = {"选择题": "Choice", "填空题": "Fill", "解答题": "Solve"}
        qtype = qtype_map.get(r["type"], "")
        if qtype:
            cv2.putText(vis, qtype, (x2 - 80, y1 + 38),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 140, 0), 2)
    for fig in figures:
        sx1 = max(0, fig["cx"] - 200)
        sx2 = min(w, fig["cx"] + 200)
        cv2.rectangle(vis, (sx1, fig["top_y"]), (sx2, fig["bottom_y"]),
                      (0, 180, 0), 2)
        cv2.putText(vis, f"fig{fig['id']}", (sx1 + 4, fig["top_y"] + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 140, 0), 2)
    for m in markers:
        if m["type"] == "section":
            cv2.circle(vis, (m["item"]["top_left_x"], m["item"]["top_left_y"] + 15),
                       8, (0, 180, 0), -1)
    return vis


def run_crop(png_dir: str, ocr_dir: str, markers_json: str,
             figures_json: str, output_dir: str,
             auto_margin: bool = False) -> dict:
    png_dir = Path(png_dir)
    ocr_dir = Path(ocr_dir)
    out = Path(output_dir)
    q_out = out / "questions"
    q_out.mkdir(parents=True, exist_ok=True)
    # 清理旧切图, 防止重跑(如题型重判)后旧分类文件残留
    for old in q_out.rglob("*.png"):
        try:
            old.unlink()
        except OSError:
            pass
    markers_data = json.load(open(markers_json, encoding="utf-8"))
    figures_data = json.load(open(figures_json, encoding="utf-8"))
    all_results = []
    global_id = 0
    pngs = sorted(png_dir.glob("page_*.png"))

    # 预检测所有跨页题
    cross_page_map = {}
    for png in pngs:
        page_num = int(png.stem.split("_")[1])
        img = _imread_unicode(str(png))
        if img is None:
            continue
        page_h = img.shape[0]
        cross = _detect_cross_page(markers_data, page_num, page_h)
        if cross:
            cross_page_map[(page_num, cross["num"])] = cross
            print(f"  [跨页] page{page_num} Q{cross['num']} -> page{page_num + 1}")

    for png in pngs:
        page_num = int(png.stem.split("_")[1])
        img = _imread_unicode(str(png))
        if img is None:
            continue
        h, w = img.shape[:2]
        page_markers = _get_page_markers(markers_data, page_num)
        page_figures = _get_page_figures(figures_data, page_num)
        if auto_margin:
            page_left, page_right = detect_content_bounds(img)
        else:
            page_left, page_right = PAGE_LEFT, PAGE_RIGHT
        ocr_file = ocr_dir / f"ocr_page_{page_num:02d}.json"
        items = json.load(open(ocr_file, encoding="utf-8")).get("ocr_result", []) \
            if ocr_file.exists() else []
        qs = compute_bboxes(page_markers, items, h, w, page_figures,
                            page_left=page_left, page_right=page_right)

        for r in qs:
            cross_key = (page_num, r["num"])
            if cross_key in cross_page_map:
                cross = cross_page_map[cross_key]
                x1, y1, x2, _ = r["bbox"]
                x1, y1, x2 = int(x1), int(y1), int(x2)
                crop_top = img[y1:h, x1:x2]
                next_img = _imread_unicode(str(png_dir / f"page_{page_num + 1:02d}.png"))
                if next_img is not None:
                    next_h = next_img.shape[0]
                    next_y2 = int(min(cross["next_q_y"] - 2, next_h))
                    # 跨页合并: 上下页渲染宽度可能不同(如 1536 vs 1531),
                    # 取两页宽度较小值对齐, 避免 np.vstack 维度不匹配
                    min_w = min(img.shape[1], next_img.shape[1])
                    x2_aligned = min(x2, min_w)
                    crop_top = img[y1:h, x1:x2_aligned]
                    crop_bottom = next_img[0:next_y2, x1:x2_aligned]
                    crop = np.vstack([crop_top, crop_bottom])
                else:
                    crop = crop_top
                r["cross_page"] = True
            else:
                x1, y1, x2, y2 = r["bbox"]
                crop = img[int(y1):int(y2), int(x1):int(x2)]
                r["cross_page"] = False

            ch, cw = crop.shape[:2]
            if ch < MIN_HEIGHT:
                canvas = np.full((MIN_HEIGHT, cw, 3), 255, dtype=np.uint8)
                canvas[:ch, :] = crop
                crop = canvas
            qtype = r["type"]
            type_dir = q_out / qtype
            type_dir.mkdir(parents=True, exist_ok=True)
            day = r.get("day", 0)
            if day > 0:
                out_name = f"day{day}_q{r['num']:02d}.png"
            else:
                out_name = f"q{global_id:03d}.png"
            ok, buf = cv2.imencode(".png", crop)
            if ok:
                # 用 Python 原生字节写入, 避免 OpenCV 在 Windows 中文路径乱码
                (type_dir / out_name).write_bytes(buf.tobytes())
            else:
                print(f"[WARN] 图片编码失败: {type_dir / out_name}")
            global_id += 1
            r["page"] = page_num
            r["original_num"] = r["num"]
            r["global_id"] = global_id
            r["day"] = day
            r["file"] = f"{qtype}/{out_name}"
            r["size"] = list(crop.shape[:2][::-1])
            all_results.append(r)
        vis = draw_overlay(img, page_markers, page_figures, qs)
        cv2.imwrite(str(out / f"overlay_page_{page_num:02d}.png"), vis)
        print(f"  page {page_num}: {len(qs)} 题")

    all_results.sort(key=lambda r: r["global_id"])
    type_count = {}
    for r in all_results:
        type_count[r["type"]] = type_count.get(r["type"], 0) + 1
    meta = {
        "total_questions": len(all_results),
        "type_summary": type_count,
        "cross_page_count": len(cross_page_map),
        "questions": all_results,
    }
    with open(out / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"\nDone: {len(all_results)} 题 (跨页合并: {len(cross_page_map)} 题)")
    print(f"分类: {type_count}")
    print(f"输出: {q_out}")
    return meta


def main():
    ap = argparse.ArgumentParser(description="试卷题目切分")
    ap.add_argument("png_dir", help="page_*.png 所在目录")
    ap.add_argument("ocr_dir", help="ocr_page_*.json 所在目录")
    ap.add_argument("markers_json", help="版面分析 markers.json")
    ap.add_argument("figures_json", help="图形检测 figures.json")
    ap.add_argument("output_dir", help="输出目录")
    ap.add_argument("--auto-margin", action="store_true",
                    help="自动检测每页内容左右边界 (适配非标准试卷)")
    args = ap.parse_args()
    run_crop(args.png_dir, args.ocr_dir, args.markers_json,
             args.figures_json, args.output_dir,
             auto_margin=args.auto_margin)


if __name__ == "__main__":
    main()
