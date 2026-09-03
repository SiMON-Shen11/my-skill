#!/usr/bin/env python3
"""
模块2 (备选): 像素投影 OCR + 题型标注
基于像素投影精确定位题号和文本段, 配合 Agent 视觉识别的题型标注生成 OCR JSON。

适用场景:
- 纯像素投影无法区分选择题选项行(A.)和解答题子问行((1)), 需要 Agent 视觉辅助标注题型
- 页面布局规则, 题号位置稳定的试卷/打卡册

工作流:
1. 像素投影检测每页题号位置和文本段
2. 生成题型标注模板 (question_types_template.json)
3. Agent 视觉逐页识别题型, 填写模板
4. 生成带 question_type 字段的 OCR JSON

用法:
    # 步骤1: 像素投影检测 + 生成题型标注模板
    python3 pixel_ocr.py detect pages/ ocr/ --template question_types.json

    # 步骤2: (Agent 视觉) 填写 question_types.json 中每题的 type 字段
    #        格式: {"page": {"qnum": "选择题"|"填空题"|"解答题"}}

    # 步骤3: 基于题型标注生成最终 OCR JSON
    python3 pixel_ocr.py generate pages/ ocr/ --types question_types.json

    # 一步完成 (使用内置的像素特征兜底分类, 准确率较低)
    python3 pixel_ocr.py auto pages/ ocr/
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


# ---------- 配置 ----------
ROW_PROJ_THRESHOLD = 15       # 行投影阈值 (大于此值认为有内容)
SEGMENT_GAP = 5               # 段间最小行距
QUESTION_LEFT_SCAN = 400      # 题号行左侧扫描范围
QUESTION_LEFT_MAX = 350       # 题号行左侧内容最大 x
QUESTION_LEFT_W_MIN = 50      # 题号行左侧内容最小宽度
QUESTION_H_MIN = 15           # 题号行最小高度
QUESTION_H_MAX = 120          # 题号行最大高度
QUESTION_FULL_W_MIN = 300     # 题号行最小全宽
INDENT_LEFT_MIN = 50         # 缩进行最小 x (排除题号行)
SECTION_LEFT_MIN = 150        # 大题标题最小 x
SECTION_H_MIN = 20            # 大题标题最小高度
SECTION_H_MAX = 80            # 大题标题最大高度
SECTION_FULL_W_MAX = 600      # 大题标题最大全宽
SHORT_LINE_H_MAX = 80         # 短行最大高度
TALL_TABLE_H_MIN = 500        # 大表格最小高度
AVG_FILL_W_THRESHOLD = 1000   # 填空题第二行平均宽度阈值


def detect_segments(binary: np.ndarray) -> list[tuple[int, int]]:
    """基于行投影检测文本段。返回 [(start_y, end_y), ...]"""
    row_proj = np.sum(binary, axis=1)
    content_rows = np.where(row_proj > ROW_PROJ_THRESHOLD)[0]
    segments = []
    if len(content_rows) == 0:
        return segments
    start = content_rows[0]
    prev = content_rows[0]
    for r in content_rows[1:]:
        if r - prev > SEGMENT_GAP:
            segments.append((int(start), int(prev)))
            start = r
        prev = r
    segments.append((int(start), int(prev)))
    return segments


def detect_section_start(binary: np.ndarray, segments: list[tuple[int, int]],
                         img_w: int, img_h: int) -> int:
    """检测第一个大题标题的 y 坐标 (用于排除页面顶部的注意事项等)。
    大题标题特征: 居中、高度适中(25-60)、在页面中下部(y > img_h*0.4)。
    返回第一个大题标题的 y 坐标, 找不到返回 0。
    """
    min_y = int(img_h * 0.4)  # 跳过页面顶部的试卷标题和注意事项
    for s, e in segments:
        if s < min_y:
            continue
        full_cols = np.where(np.sum(binary[s:e + 1, :], axis=0) > 0)[0]
        if len(full_cols) == 0:
            continue
        full_min = int(full_cols.min())
        full_max = int(full_cols.max())
        full_w = full_max - full_min
        center = (full_min + full_max) / 2
        height = int(e - s + 1)
        # 大题标题: 居中、高度适中、宽度足够
        if (abs(center - img_w / 2) < 250
                and full_w >= 200
                and 25 <= height <= 60):
            return int(s)
    return 0


def detect_questions(binary: np.ndarray, segments: list[tuple[int, int]],
                     start_y: int = 0) -> list[int]:
    """检测题号行的 y 坐标。start_y: 只在此 y 之后检测 (排除注意事项和大题标题)。
    对于高度超过 QUESTION_H_MAX 的大段(含图形), 在左侧区域细分检测题号行。
    """
    question_ys = []
    section_end = start_y + 80 if start_y > 0 else 0

    def _check_segment(s: int, e: int) -> bool:
        """检查一个段是否满足题号行条件。"""
        left = binary[s:e + 1, :QUESTION_LEFT_SCAN]
        left_cols = np.where(np.sum(left, axis=0) > 0)[0]
        full_cols = np.where(np.sum(binary[s:e + 1, :], axis=0) > 0)[0]
        if len(left_cols) == 0:
            return False
        left_min = int(left_cols.min())
        left_w = int(left_cols.max() - left_cols.min())
        height = int(e - s + 1)
        full_w = int(full_cols.max() - full_cols.min()) if len(full_cols) > 0 else 0
        return (left_min < QUESTION_LEFT_MAX
                and left_w > QUESTION_LEFT_W_MIN
                and QUESTION_H_MIN <= height <= QUESTION_H_MAX
                and full_w > QUESTION_FULL_W_MIN)

    for s, e in segments:
        if s < start_y or s < section_end:
            continue
        height = int(e - s + 1)
        if height <= QUESTION_H_MAX:
            # 普通段, 直接检查
            if _check_segment(s, e):
                question_ys.append(int(s))
        else:
            # 大段(含图形), 在左侧区域细分检测题号行
            left_region = binary[s:e + 1, 100:QUESTION_LEFT_SCAN]
            row_proj = np.sum(left_region, axis=1)
            content_rows = np.where(row_proj > 10)[0]
            if len(content_rows) == 0:
                continue
            # 细分子段
            sub_start = content_rows[0]
            sub_prev = content_rows[0]
            for r in content_rows[1:]:
                if r - sub_prev > 5:
                    sub_s = int(s + sub_start)
                    sub_e = int(s + sub_prev)
                    if _check_segment(sub_s, sub_e):
                        question_ys.append(sub_s)
                    sub_start = r
                sub_prev = r
            # 最后一个子段
            sub_s = int(s + sub_start)
            sub_e = int(s + sub_prev)
            if _check_segment(sub_s, sub_e):
                question_ys.append(sub_s)

    question_ys = sorted(set(question_ys))
    return question_ys


def classify_by_pixel_features(q_items: list[dict]) -> str:
    """基于像素特征的兜底题型分类 (准确率较低, 建议使用 Agent 视觉标注)。

    规则:
    - 大表格(高行>500) → 解答题
    - 2个短行且无大图形 → 解答题
    - 1个短行且平均宽度>1000 → 填空题
    - 有短行 → 选择题
    - 无短行 → 填空题
    """
    if not q_items:
        return "填空题"
    short_items = [it for it in q_items
                   if (it["bottom_right_y"] - it["top_left_y"]) <= SHORT_LINE_H_MAX]
    tall_items = [it for it in q_items
                  if (it["bottom_right_y"] - it["top_left_y"]) > SHORT_LINE_H_MAX]
    max_tall_h = max((it["bottom_right_y"] - it["top_left_y"] for it in tall_items),
                     default=0)
    n_short = len(short_items)
    avg_short_w = np.mean([it["bottom_right_x"] - it["top_left_x"]
                           for it in short_items]) if short_items else 0

    if max_tall_h > TALL_TABLE_H_MIN:
        return "解答题"
    if n_short == 2 and max_tall_h <= SHORT_LINE_H_MAX:
        return "解答题"
    if n_short == 1 and avg_short_w > AVG_FILL_W_THRESHOLD:
        return "填空题"
    if n_short >= 1:
        return "选择题"
    return "填空题"


def generate_ocr_with_types(img_path: str, page_num: int,
                            question_types: dict[int, str] | None = None,
                            day: int | None = None,
                            page_question_nums: list[int] | None = None
                            ) -> tuple[list[dict], list[int]]:
    """生成单页 OCR JSON。

    Args:
        img_path: 页面图片路径
        page_num: 页码
        question_types: {qnum: type} 题型映射, None 时使用像素特征兜底
        day: DAY 编号 (打卡册), None 时不标注 section
        page_question_nums: 该页题号列表 (用于跨页/重新编号场景), None 时按顺序1..N

    Returns:
        (ocr_items, question_ys)
    """
    img = cv2.imread(img_path)
    if img is None:
        return [], []
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    segments = detect_segments(binary)
    section_start = detect_section_start(binary, segments, w, h)
    question_ys = detect_questions(binary, segments, start_y=section_start)

    # 题号映射
    if page_question_nums and len(page_question_nums) >= len(question_ys):
        q_num_map = {y: page_question_nums[i] for i, y in enumerate(question_ys)}
    else:
        q_num_map = {y: i + 1 for i, y in enumerate(question_ys)}

    raw_items = []
    for s, e in segments:
        left = binary[s:e + 1, :QUESTION_LEFT_SCAN]
        left_cols = np.where(np.sum(left, axis=0) > 0)[0]
        full_cols = np.where(np.sum(binary[s:e + 1, :], axis=0) > 0)[0]
        if len(full_cols) == 0:
            continue
        left_min = int(left_cols.min()) if len(left_cols) > 0 else 999
        full_w = int(full_cols.max() - full_cols.min())
        full_min = int(full_cols.min())
        full_max = int(full_cols.max())
        height = int(e - s + 1)
        if height <= 5 and full_w > 1000:
            continue  # 跳过分隔线

        item_type = "text"
        content = "text"
        question_type = None
        center = (full_min + full_max) / 2

        # 大题标题 (DAY 标题)
        if ((left_min > SECTION_LEFT_MIN or len(left_cols) == 0)
                and abs(center - w / 2) < 300
                and SECTION_H_MIN <= height <= SECTION_H_MAX
                and full_w < SECTION_FULL_W_MAX):
            if day is not None:
                item_type = "section"
                content = f"期末打卡 DAY {day}"
        # 题号行
        elif int(s) in q_num_map:
            qnum = q_num_map[int(s)]
            item_type = "question"
            content = f"{qnum}. question"
            if question_types and qnum in question_types:
                question_type = question_types[qnum]
        # 缩进行 (选项/子问/题干第二行)
        elif left_min > INDENT_LEFT_MIN and height >= 15:
            item_type = "indent"
            content = "indent"

        item = {
            "content": content,
            "type": item_type,
            "top_left_x": full_min,
            "top_left_y": int(s),
            "bottom_right_x": full_max,
            "bottom_right_y": int(e),
        }
        if question_type:
            item["question_type"] = question_type
        raw_items.append(item)

    # 按题分组, 标注缩进行类型
    for i, q_y in enumerate(question_ys):
        next_y = question_ys[i + 1] if i + 1 < len(question_ys) else 99999
        qnum = q_num_map[q_y]
        qtype = (question_types.get(qnum) if question_types
                 else classify_by_pixel_features(
                     [it for it in raw_items
                      if q_y <= it["top_left_y"] < next_y and it["type"] == "indent"]))
        q_items = [it for it in raw_items
                   if q_y <= it["top_left_y"] < next_y and it["type"] == "indent"]
        if not q_items:
            continue

        if qtype == "选择题":
            for it in q_items:
                h_it = it["bottom_right_y"] - it["top_left_y"]
                if h_it <= SHORT_LINE_H_MAX:
                    it["type"] = "option"
                    it["content"] = "A. option"
                else:
                    it["type"] = "text"
                    it["content"] = "figure"
        elif qtype == "解答题":
            for it in q_items:
                h_it = it["bottom_right_y"] - it["top_left_y"]
                if h_it <= SHORT_LINE_H_MAX:
                    it["type"] = "subquestion"
                    it["content"] = "(1) subquestion"
                elif h_it > TALL_TABLE_H_MIN:
                    it["type"] = "subquestion"
                    it["content"] = "(1) table"
                else:
                    it["type"] = "text"
                    it["content"] = "figure"
        else:  # 填空题
            for it in q_items:
                it["type"] = "text"
                it["content"] = "text"

        for it in q_items:
            if it["type"] == "indent":
                it["type"] = "text"
                it["content"] = "text"

    # 只保留第一个 section
    sections = [it for it in raw_items if it["type"] == "section"]
    if len(sections) > 1:
        first_y = min(s["top_left_y"] for s in sections)
        for it in raw_items:
            if it["type"] == "section" and it["top_left_y"] != first_y:
                it["type"] = "text"
                it["content"] = "text"

    return raw_items, question_ys


def cmd_detect(pages_dir: str, ocr_dir: str, template_path: str,
               question_nums_path: str | None = None):
    """检测题号并生成题型标注模板。"""
    pages_dir = Path(pages_dir)
    ocr_dir = Path(ocr_dir)
    ocr_dir.mkdir(parents=True, exist_ok=True)
    template = {}
    q_nums_map = {}
    if question_nums_path:
        q_nums_map = {int(k): v for k, v in
                      json.load(open(question_nums_path, encoding="utf-8")).items()}

    pngs = sorted(pages_dir.glob("page_*.png"))
    for png in pngs:
        page_num = int(png.stem.split("_")[1])
        page_q_nums = q_nums_map.get(page_num)
        items, q_ys = generate_ocr_with_types(
            str(png), page_num, page_question_nums=page_q_nums)
        # 保存初步 OCR (无题型标注)
        with open(ocr_dir / f"ocr_page_{page_num:02d}.json", "w", encoding="utf-8") as f:
            json.dump({"ocr_result": items, "page": page_num,
                       "source": "pixel_projection", "success": True},
                      f, ensure_ascii=False, indent=2)
        # 生成题型标注模板
        page_template = {}
        for y in q_ys:
            for it in items:
                if it["top_left_y"] == y and it["type"] == "question":
                    qnum = int(it["content"].split(".")[0])
                    page_template[str(qnum)] = "待标注"
                    break
        template[str(page_num)] = page_template
        print(f"  page {page_num}: {len(q_ys)} 题")

    with open(template_path, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    print(f"\n题型标注模板已生成: {template_path}")
    print("请用 Agent 视觉识别每页题型, 填写后使用 generate 子命令生成最终 OCR")


def cmd_generate(pages_dir: str, ocr_dir: str, types_path: str,
                 day_map_path: str | None = None,
                 question_nums_path: str | None = None):
    """基于题型标注生成最终 OCR JSON。"""
    pages_dir = Path(pages_dir)
    ocr_dir = Path(ocr_dir)
    ocr_dir.mkdir(parents=True, exist_ok=True)
    types_data = json.load(open(types_path, encoding="utf-8"))
    day_map = json.load(open(day_map_path, encoding="utf-8")) if day_map_path else {}
    q_nums_map = {}
    if question_nums_path:
        q_nums_map = {int(k): v for k, v in
                      json.load(open(question_nums_path, encoding="utf-8")).items()}

    pngs = sorted(pages_dir.glob("page_*.png"))
    for png in pngs:
        page_num = int(png.stem.split("_")[1])
        page_types = {int(k): v for k, v in types_data.get(str(page_num), {}).items()}
        day = day_map.get(str(page_num))
        page_q_nums = q_nums_map.get(page_num)
        items, q_ys = generate_ocr_with_types(
            str(png), page_num, question_types=page_types, day=day,
            page_question_nums=page_q_nums)
        with open(ocr_dir / f"ocr_page_{page_num:02d}.json", "w", encoding="utf-8") as f:
            json.dump({"ocr_result": items, "page": page_num,
                       "source": "pixel_projection+agent_type", "success": True},
                      f, ensure_ascii=False, indent=2)
        print(f"  page {page_num}: {len(q_ys)} 题")

    print(f"\nOCR 已生成: {ocr_dir}")


def cmd_auto(pages_dir: str, ocr_dir: str):
    """一步完成 (使用像素特征兜底分类, 准确率较低)。"""
    pages_dir = Path(pages_dir)
    ocr_dir = Path(ocr_dir)
    ocr_dir.mkdir(parents=True, exist_ok=True)

    pngs = sorted(pages_dir.glob("page_*.png"))
    for png in pngs:
        page_num = int(png.stem.split("_")[1])
        items, q_ys = generate_ocr_with_types(str(png), page_num, question_types=None)
        with open(ocr_dir / f"ocr_page_{page_num:02d}.json", "w", encoding="utf-8") as f:
            json.dump({"ocr_result": items, "page": page_num,
                       "source": "pixel_projection_auto", "success": True},
                      f, ensure_ascii=False, indent=2)
        print(f"  page {page_num}: {len(q_ys)} 题")

    print(f"\nOCR 已生成 (像素特征兜底分类): {ocr_dir}")
    print("注意: 像素特征无法准确区分选择题和解答题, 建议使用 detect+generate 工作流")


def main():
    ap = argparse.ArgumentParser(description="像素投影 OCR + 题型标注")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_detect = sub.add_parser("detect", help="检测题号并生成题型标注模板")
    p_detect.add_argument("pages_dir", help="page_*.png 目录")
    p_detect.add_argument("ocr_dir", help="输出 OCR 目录")
    p_detect.add_argument("--template", default="question_types.json",
                          help="题型标注模板路径")
    p_detect.add_argument("--question-nums", help="题号映射 JSON (打卡册每页题号不连续时使用)")

    p_gen = sub.add_parser("generate", help="基于题型标注生成最终 OCR")
    p_gen.add_argument("pages_dir", help="page_*.png 目录")
    p_gen.add_argument("ocr_dir", help="输出 OCR 目录")
    p_gen.add_argument("--types", required=True, help="题型标注 JSON")
    p_gen.add_argument("--day-map", help="DAY 映射 JSON (打卡册)")
    p_gen.add_argument("--question-nums", help="题号映射 JSON (打卡册每页题号不连续时使用)")

    p_auto = sub.add_parser("auto", help="一步完成 (像素特征兜底分类)")
    p_auto.add_argument("pages_dir", help="page_*.png 目录")
    p_auto.add_argument("ocr_dir", help="输出 OCR 目录")

    args = ap.parse_args()
    if args.cmd == "detect":
        cmd_detect(args.pages_dir, args.ocr_dir, args.template,
                   args.question_nums)
    elif args.cmd == "generate":
        cmd_generate(args.pages_dir, args.ocr_dir, args.types,
                     args.day_map, args.question_nums)
    elif args.cmd == "auto":
        cmd_auto(args.pages_dir, args.ocr_dir)


if __name__ == "__main__":
    main()
