#!/usr/bin/env python3
"""
模块3: 版面分析
从 OCR 结果中识别大题标题、题号、页脚, 并按题型分类。

输出 markers.json:
{
  "pages": [
    {
      "page": 1,
      "markers": [
        {"type": "section", "y": 1571, "text": "一、选择题...", "qtype": "选择题"},
        {"type": "question", "y": 1721, "num": 1, "text": "1.下列...", "qtype": "选择题"},
        {"type": "footer", "y": 2040, "text": "数学试卷第1页..."}
      ]
    },
    ...
  ],
  "questions": [
    {"num": 1, "type": "选择题", "page": 1, "y": 1721},
    ...
  ]
}

用法:
    python3 layout_analysis.py <ocr_dir> <output_json>
"""
import argparse
import json
import re
import sys
from pathlib import Path

import cv2


def _imread_unicode(path):
    """cv2.imread 不支持中文/非ASCII路径, 用 np.fromfile + imdecode 兼容 Windows。"""
    try:
        import numpy as _np
        data = _np.fromfile(str(path), dtype=_np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


# ---------- 正则 ----------
# 大题/页面标题: 标准试卷(第X部分/一、) + 非标准(期末打卡/DAY/打卡)
# + 教材层级标题(第X章 / 25.1 / 25.2.1 / 第N课时 / 方法技巧等) —— 升级新增
RE_SECTION = re.compile(
    r'^\s*(第[一二三四五六七八九十]+部分|[一二三四五六七八九十]+[、．.]|期末打卡.*DAY|.*DAY\s*\d*'
    r'|第[一二三四五六七八九十]+章'
    r'|\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\s'
    r'|第\d+课时'
    r'|知识点\d+'
    r'|[A-C]?\s*(基础夯实|基础题夯实|中档题运用|综合题探究|方法技巧|回归教材|题型研究|思想方法|数学活动|综合与实践|一题多法|一题练透|图形研究|实践操作|易错警示|名师点拨|能力提升|综合运用|素养提升))'
)
# 教材层级编号(如 25.1 / 25.1.1): 仅当整行较短(像标题)才当大题标题;
# 长句(如 OCR 把题号 "10．2台…" 识别成 "10.2 台…")是题目而非标题
RE_HIER_NUM = re.compile(r'^\s*\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\s')
HIER_TITLE_MAX_LEN = 30
RE_QUESTION = re.compile(r'^\s*(\d+)[.．]\s*')
# 选项: 支持 (A) 和 A. 两种格式 (教辅常见 "A.1个" 无空格, 故用 \s*)
RE_OPTION = re.compile(r'^\s*[（(][A-D][）)]|^\s*[A-D][.．]\s*')
RE_SUBQ = re.compile(r'^\s*[（(]\d+[）)]')
# 解答题关键词(用户判别标准): 计算/证明/写出过程等要求; "是否存在"做OCR分词容错(是否分别存在)
# "写出"仅限解答语境(写出过程/理由/结论等), 避免"写出一个…方程/值"这类填空被误判
# "列方程"仅"列方程解/列方程并"才算解答(列并解/并求解); "可列方程组为____(只列不解)"这类
# 列而不解的填空不命中(如打卡册 p2 题9 被 PaddleOCR 丢横线后曾因"列方程"误判为解答题)
RE_SOLVE = re.compile(r'求|证明|求证|化简|解方程|解不等式|列方程解|列方程并|画出|写出(过程|理由|证明|结论|步骤|你的|完整|详细|解答|思路|如何|为什么|简要|算式)|是否.{0,4}存在|试说明|是多少|请算|计算')
# 填空横线: 2个以上连续下划线(半角/全角)
RE_BLANK = re.compile(r'_{2,}|＿{2,}')
# 跨页判定阈值(与 crop.py 保持一致): 末题内容底距页底小于此值怀疑跨页;
# 下页首题 y 大于此值说明页首有延续内容
CROSS_PAGE_THRESHOLD = 400
CROSS_NEXT_PAGE_TOP = 200
# 页码/页脚行(纯数字或 ·N· / -N- / —N—), 判定时剔除, 避免污染问号/关键词判断
RE_PAGENO = re.compile(r'^[·\-—]?\s*\d{1,4}\s*[·\-—]?$')
RE_CIRCLE = re.compile(r'^\s*[①②③④⑤⑥⑦⑧⑨⑩]')
RE_FOOTER = re.compile(r'数学试卷.*第\d+页|第\d+页.*共\d+页')

# 题号行 x 坐标上限 (避免把右侧图形标签误判为题号)
QUESTION_X_MAX = 350

# 表格页特征: 左栏"类型一/二/三"分类标签 + 右栏"【教材变式N】"或"教材母题"
# 这种页面左栏的"1.2.3."是类型子问不是题目, 右栏"【教材变式N】"不匹配题号正则,
# 常规题号检测会把左栏子问误识别为题号而漏掉右栏真正题目 → 整表作为一道解答题
RE_TABLE_TYPE = re.compile(r'类型[一二三四五六七八九十]')
RE_TABLE_VARIANT = re.compile(r'变式|教材母题')


def _is_table_page(items: list[dict]) -> bool:
    """检测是否为镶嵌多个题目的大表格页(如"回归教材"/"方法技巧"页: 左栏类型分类+子问, 右栏题目)。

    判定条件(满足其一即可):
    1. 同时存在"类型[一二三四...]"和"变式|教材母题"(标准表格页)
    2. 存在"类型[一二三四...]"且左栏(x<300)有≥2个"数字."编号
       (这些左栏编号是类型子问步骤说明, 不是真正题目, 如"1.知a,b... 2.知a,c... 3.建立方程组")
    """
    has_type = any(RE_TABLE_TYPE.search(it["content"]) for it in items)
    if not has_type:
        return False
    # 条件1: 右栏有变式/教材母题
    has_variant = any(RE_TABLE_VARIANT.search(it["content"]) for it in items)
    if has_variant:
        return True
    # 条件2: 左栏有≥2个"数字."编号(表格左栏的步骤说明被误识别为题号)
    RE_LEFT_NUM = re.compile(r'^\s*\d+[.．]\s*')
    left_num_count = sum(1 for it in items
                         if it.get("top_left_x", 0) < 300 and RE_LEFT_NUM.match(it["content"]))
    return left_num_count >= 2


def _classify_section(text: str, current_type: str) -> str:
    """根据大题标题文字判断题型。"""
    if "选择题" in text and "非选择题" not in text:
        return "选择题"
    if "填空题" in text:
        return "填空题"
    if "解答题" in text:
        return "解答题"
    # 不包含题型关键词的section(教材小节标题如"25.2.3 因式分解法"、
    # 板块标题如"基础题夯实") → 返回"未分类", 使后续题目走自动判定,
    # 避免继承上一页的题型(如解答题)导致选择题/填空题被误判
    return "未分类"


def _is_text_stroke(bw, x, y, ww, hh, y_offset=0, ocr_items=None) -> bool:
    """判断检测到的水平线段是否为文字横画/汉字"一", 而非填空横线。

    填空横线的特征: 孤立的水平线, 上方/左右无其他笔画, 不在 OCR 文本块内部。
    文字横画/汉字"一"的特征: 上方有字的上半部分笔画, 或左右连着其他字,
    或 y 范围与 OCR 文本块高度重叠。
    """
    # 1. 横线上方 0~3px 紧邻区域有连续黑色像素 → 文字底部横画(如"王""里"
    #    的底横紧挨着字的上半部分); 填空横线与上方文字通常有 >3px 行间距
    above_y0 = max(0, y - 4)
    above_y1 = max(0, y - 1)
    if above_y1 > above_y0:
        above = bw[above_y0:above_y1, max(0, x - 2):min(bw.shape[1], x + ww + 2)]
        if cv2.countNonZero(above) > ww * 0.08:
            return True
    # 2. 横线左右 6px 内有黑色像素 → 汉字"一"在词语中(左右连着其他字)
    for dx0, dx1 in [(max(0, x - 8), x), (x + ww, min(bw.shape[1], x + ww + 8))]:
        if dx1 > dx0:
            side = bw[y:y + hh, dx0:dx1]
            if cv2.countNonZero(side) > 2:
                return True
    return False


def _detect_blank_lines(page_img, y_top: int, y_bot: int,
                        x_left: int = 0, x_right: int = None,
                        ocr_items: list | None = None) -> bool:
    """在页面图像指定区域检测填空横线(较薄的暗色长水平线)。

    PP-OCR 对填空横线(下划线)识别不稳定(常丢失), 用像素检测补充:
    该区域存在 40px 以上的细长水平实线 → 判定有填空横线。
    ocr_items: 该题范围内的 OCR 文本块, 用于排除文字横画/汉字"一"的误判。
    """
    if page_img is None:
        return False
    h, w = page_img.shape[:2]
    x_right = x_right if x_right is not None else w
    # 上边界仅极小幅向上扩展(避免把上一题的填空横线算进来); 下边界严格不越过 next_y
    y_top = max(0, int(y_top) - 4)
    y_bot = min(h, int(y_bot))
    x_left = max(0, int(x_left))
    x_right = min(w, int(x_right))
    if y_bot - y_top < 8 or x_right - x_left < 30:
        return False
    roi = page_img[y_top:y_bot, x_left:x_right]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # 水平闭运算连接水平线段
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (51, 1))
    lines = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel)
    n, _, stats, _ = cv2.connectedComponentsWithStats(lines, 8)
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        # 填空横线: 宽度足、厚度薄(纯横线)、实心占比高
        if ww >= 40 and hh <= 12 and area > ww * 0.4:
            # 防误判: 排除文字横画/汉字"一"
            if _is_text_stroke(bw, x, y, ww, hh, y_offset=y_top, ocr_items=ocr_items):
                continue
            return True
    return False


def _subq_all_blank(lines: list[dict]) -> bool:
    """有 (1)(2) 子问且每个子问范围内都有填空横线 → True; 任一子问无横线 → False。"""
    subqs = sorted([it for it in lines if RE_SUBQ.match(it["content"].strip())],
                   key=lambda it: it["top_left_y"])
    if not subqs:
        return False
    for i, sq in enumerate(subqs):
        if i + 1 < len(subqs):
            end_y = subqs[i + 1]["top_left_y"]
        else:
            # 最后一个子问: 到范围内剩余行最大 bottom
            end_y = max((it["bottom_right_y"] for it in lines
                         if it["top_left_y"] >= sq["top_left_y"]),
                        default=sq["bottom_right_y"])
        seg = "".join(it["content"].strip() for it in lines
                      if sq["top_left_y"] <= it["top_left_y"] < end_y)
        if not RE_BLANK.search(seg):
            return False
    return True


def _subq_all_blank_pixel(page_img, lines: list[dict]) -> bool:
    """子问全横线的像素版: 每个子问区域都检测到填空横线。"""
    subqs = sorted([it for it in lines if RE_SUBQ.match(it["content"].strip())],
                   key=lambda it: it["top_left_y"])
    if not subqs:
        return False
    # 下划线(填空横线)通常在 OCR 文本块底部下方几~20px, 最后一个子问
    # 的检测区间需向下扩展才能包含, 否则 PaddleOCR 丢掉下划线时误判为解答题
    BLANK_EXTEND_PX = 30
    # 横线也可能在 OCR 文本块上方(如"(1) [π]=____"的横线比 OCR 块顶高 28px),
    # 起始 y 需向上扩展才能包含
    SUBQ_BLANK_TOP_PAD = 30
    for i, sq in enumerate(subqs):
        if i + 1 < len(subqs):
            end_y = subqs[i + 1]["top_left_y"]
        else:
            end_y = max((it["bottom_right_y"] for it in lines
                         if it["top_left_y"] >= sq["top_left_y"]),
                        default=sq["bottom_right_y"]) + BLANK_EXTEND_PX
        # 起始 y 向上扩展, 但不得侵入上一行 OCR 文字区域, 否则会把上一行
        # 文字的底部笔画(如汉字横画/公式分数线)误检为填空横线.
        # _detect_blank_lines 内部会再 -4px, 这里 +4 抵消, 确保不侵入.
        prev_bottom = max((it["bottom_right_y"] for it in lines
                           if it["top_left_y"] < sq["top_left_y"]), default=0)
        start_y = max(prev_bottom + 4, sq["top_left_y"] - SUBQ_BLANK_TOP_PAD)
        if not _detect_blank_lines(page_img, start_y, end_y, ocr_items=lines):
            return False
    return True


def _classify_question(items: list[dict], q_y: int, next_y: int,
                       page_img=None) -> str | None:
    """按老师判别标准自适应题型分类, 优先级: 选择题 → 填空题 → 解答题 → 无法确定(None)。

    执行级短路: 每一步只计算该步所需特征, 命中即返回, 不再执行后续判断。

    判定原则(与老师确认的最终版):
       - 选择题: 有 A./B./C./D. 或 (A)(B)(C)(D) 选项行 → 命中即返回
       - 填空题: 只看横线特征, 不涉及解答关键词/问号
           (a) 有 (1)(2) 子问: 每个子问都有填空横线 → 填空题
           (b) 无子问: 题后有填空横线(OCR 或像素检测) → 填空题
       - 解答题: 无横线时才用解答特征判断
           有子问(非全横线) / 命中解答关键词 / 出现问号(引号内除外)
       - 均不满足 → None (交 Agent 视觉判断)
    """
    q_items = [it for it in items
               if q_y <= it["top_left_y"] < next_y]
    q_items_sorted = sorted(q_items, key=lambda r: (r["top_left_y"], r["top_left_x"]))
    # 剔除页码/页脚行, 避免污染横线/关键词/问号判断
    body = [it for it in q_items_sorted if not RE_PAGENO.match(it["content"].strip())]

    # 1. 选择题: 只检测选项行, 命中即短路返回(不做横线/关键词/问号计算)
    has_option = any(RE_OPTION.match(it["content"].strip()) for it in body)
    if has_option:
        return "选择题"

    # 2. 填空题: 只看横线特征, 命中即短路返回(不计算解答关键词/问号)
    full_text = "".join(it["content"].strip() for it in body)
    has_subq = any(RE_SUBQ.match(it["content"].strip()) for it in body)
    if has_subq:
        # 有子问: 必须每个子问都有横线才判填空
        subq_all = _subq_all_blank(body)
        if page_img is not None:
            subq_all_px = _subq_all_blank_pixel(page_img, body)
            subq_all = subq_all or subq_all_px
        if subq_all:
            return "填空题"
    else:
        # 无子问: 有横线就判填空(OCR 横线优先, 像素检测兜底)
        has_blank = bool(RE_BLANK.search(full_text))
        if not has_blank and page_img is not None:
            has_blank = _detect_blank_lines(page_img, q_y, next_y, ocr_items=body)
        if has_blank:
            return "填空题"

    # 3. 解答题: 无横线时才用解答特征判断(复用第2步已算的 full_text/has_subq)
    has_solve = bool(RE_SOLVE.search(full_text))
    # 引号内(古籍引文/引用语)的问号不计入, 如"…问诸侯几何？"的引文本身不影响题型
    text_wo_quote = re.sub(r'“[^”]*”|"[^"]*"|‘[^’]*’|\'[^\']*\'', '', full_text)
    has_question = ("？" in text_wo_quote) or ("?" in text_wo_quote)
    if has_subq or has_solve or has_question:
        return "解答题"

    # 4. 无法确定 → 交 Agent 视觉判断
    return None


RE_DAY = re.compile(r'DAY\s*(\d+)', re.IGNORECASE)


def _extract_day(text: str) -> int | None:
    """从标题中提取 DAY 编号, 如 '期末打卡 DAY 5' -> 5。"""
    m = RE_DAY.search(text)
    return int(m.group(1)) if m else None


def analyze_page(items: list[dict], in_question_zone: bool,
                 current_type: str, current_day: int = 0
                 ) -> tuple[list[dict], bool, str, int]:
    """分析单页 OCR, 返回 (markers, in_question_zone, current_type, current_day)。"""
    markers = []

    # 表格页: 镶嵌多个题目的大表格(回归教材/方法技巧等), 左栏"1.2.3."是类型子问,
    # 右栏"【教材变式N】"不匹配题号正则 → 整表作为一道解答题切割, 跳过常规题号检测
    if _is_table_page(items):
        section_it = None
        for it in items:
            text = it["content"].strip()
            if RE_SECTION.match(text) or "回归教材" in text or "方法技巧" in text:
                section_it = it
                break
        if section_it:
            section_text = section_it["content"].strip()
            markers.append({"type": "section", "y": section_it["top_left_y"],
                            "text": section_text, "item": section_it,
                            "qtype": "解答题", "day": current_day})
            current_type = "解答题"
            in_question_zone = True
            # 计算表格边界: section标题下方到页脚/页码上方
            sec_bottom = section_it["bottom_right_y"]
            content = [it for it in items
                       if it["top_left_y"] > sec_bottom + 10
                       and not RE_PAGENO.match(it["content"].strip())
                       and not RE_FOOTER.search(it["content"])]
            if content:
                # 上边界设为 section 标题 y(不小于 section, 避免 crop 把 section 当作
                # next_marker 夹紧下边界); 上边界 y1=top_y-28 会自然包含标题
                table_top = section_it["top_left_y"]
                table_bottom = max(it["bottom_right_y"] for it in content) + 20
                table_item = {
                    "content": section_text + "（整表）",
                    "top_left_x": min(it["top_left_x"] for it in content),
                    "top_left_y": table_top,
                    "bottom_right_x": max(it["bottom_right_x"] for it in content),
                    "bottom_right_y": table_bottom,
                }
                markers.append({"type": "question", "y": table_top, "num": 1,
                                "text": section_text + "（整表）", "item": table_item,
                                "qtype": "解答题", "day": current_day,
                                "content_bottom": table_bottom, "is_table": True})
        markers.sort(key=lambda m: m["y"])
        return markers, in_question_zone, current_type, current_day

    for it in items:
        text = it["content"].strip()
        y = it["top_left_y"]
        x = it["top_left_x"]

        if RE_FOOTER.search(text):
            markers.append({"type": "footer", "y": y, "text": text, "item": it})
            continue

        # 教材层级编号(如 25.1)开头的长句是题目(如 "10.2 台大收割机…"), 不是小节标题
        if RE_HIER_NUM.match(text) and len(text) > HIER_TITLE_MAX_LEN:
            section_match = None
        else:
            section_match = RE_SECTION.match(text)
        if section_match:
            qtype = _classify_section(text, current_type)
            current_type = qtype
            day = _extract_day(text)
            if day is not None:
                current_day = day
            elif "DAY" in text.upper() or "打卡" in text:
                # OCR 未识别到 DAY 数字时, 按标题出现顺序自动编号
                current_day += 1
            markers.append({"type": "section", "y": y, "text": text,
                            "item": it, "qtype": qtype, "day": current_day})
            in_question_zone = True
            continue

        m = RE_QUESTION.match(text)
        if m and in_question_zone and x < QUESTION_X_MAX:
            if not RE_OPTION.match(text) and not RE_SUBQ.match(text) and not RE_CIRCLE.match(text):
                num = int(m.group(1))
                # 优先使用 OCR 中标注的 question_type (Agent视觉识别)
                qtype = it.get("question_type", current_type)
                markers.append({"type": "question", "y": y, "num": num,
                                "text": text, "item": it, "qtype": qtype,
                                "day": current_day})

    markers.sort(key=lambda m: m["y"])
    return markers, in_question_zone, current_type, current_day


def load_ocr_page(ocr_dir: Path, page_num: int) -> list[dict]:
    f = ocr_dir / f"ocr_page_{page_num:02d}.json"
    if not f.exists():
        return []
    data = json.load(open(f, encoding="utf-8"))
    items = data.get("ocr_result", [])
    items.sort(key=lambda r: (r["top_left_y"], r["top_left_x"]))
    return items


def run_layout_analysis(ocr_dir: str, output_json: str,
                        skip_pages: list[int] | None = None,
                        pages_dir: str | None = None) -> dict:
    """对所有页做版面分析, 输出汇总 JSON。
    skip_pages: 跳过的页面(如教材目录页); pages_dir: 页面PNG目录(用于像素级填空横线检测)。"""
    ocr_dir = Path(ocr_dir)
    ocr_files = sorted(ocr_dir.glob("ocr_page_*.json"))
    if not ocr_files:
        print(f"[ERROR] {ocr_dir} 中没有 ocr_page_*.json", file=sys.stderr)
        sys.exit(1)

    pages_result = []
    all_questions = []
    in_question_zone = False
    current_type = "未分类"
    current_day = 0
    skip = set(skip_pages or [])

    for of in ocr_files:
        page_num = int(re.search(r'ocr_page_(\d+)', of.name).group(1))
        if page_num in skip:
            print(f"  page {page_num}: skipped (目录页/跳过)")
            continue
        items = load_ocr_page(ocr_dir, page_num)
        markers, in_question_zone, current_type, current_day = analyze_page(
            items, in_question_zone, current_type, current_day)

        # 序列化: item 中的 numpy 类型转原生
        clean_markers = []
        for m in markers:
            cm = {k: v for k, v in m.items() if k != "item"}
            cm["item"] = {
                "content": m["item"]["content"],
                "top_left_x": int(m["item"]["top_left_x"]),
                "top_left_y": int(m["item"]["top_left_y"]),
                "bottom_right_x": int(m["item"]["bottom_right_x"]),
                "bottom_right_y": int(m["item"]["bottom_right_y"]),
            }
            clean_markers.append(cm)
            if m["type"] == "question":
                all_questions.append({
                    "num": m["num"], "type": m["qtype"],
                    "page": page_num, "y": m["y"],
                    "day": m.get("day", 0),
                    "text": m["text"],
                })

        pages_result.append({"page": page_num, "markers": clean_markers})
        qs = [m for m in markers if m["type"] == "question"]
        print(f"  page {page_num}: {len(qs)} 题 "
              f"{[(q['num'], q.get('qtype','?')) for q in qs]}")

    # 为每题补充 content_bottom(该题范围 OCR 内容最大 bottom), 供 crop 跨页判定与
    # 下面跨页题型判定使用: 跨页题(题干在本页底、选项/答案在下一页顶)的题号 y 可能不够靠下,
    # 用内容底判断才准确(如打卡册 p1 题8 题干到底但选项在 p2 顶)。
    page_markers_by_page = {p["page"]: p["markers"] for p in pages_result}
    for q in all_questions:
        markers = page_markers_by_page.get(q["page"], [])
        # 整表题: 使用预设 content_bottom, 不重新计算(避免把页码算进表格范围)
        q_marker = None
        for m in markers:
            if m["type"] == "question" and m["num"] == q["num"] and m["y"] == q["y"]:
                q_marker = m
                break
        if q_marker and q_marker.get("is_table"):
            q["content_bottom"] = q_marker["content_bottom"]
            continue
        nxt = 999999
        for m in markers:
            if m["y"] > q["y"] and m["type"] in ("question", "section", "footer"):
                nxt = min(nxt, m["y"])
        items = load_ocr_page(ocr_dir, q["page"])
        bottoms = [it["bottom_right_y"] for it in items
                   if q["y"] <= it["top_left_y"] < nxt]
        q["content_bottom"] = int(max(bottoms)) if bottoms else int(q["y"])
        # 同步补到 pages 的 marker(crop 的 _get_page_markers 从 pages 读取)
        for m in markers:
            if m["type"] == "question" and m["num"] == q["num"] and m["y"] == q["y"]:
                m["content_bottom"] = q["content_bottom"]
                break

    # 自适应题型后处理: 对"未分类"题目, 按 选择题→填空题→解答题 顺序判断;
    # 三步都不满足 → 保持"未分类"并收集到 pending (交 Agent 视觉判断)
    pending = []
    page_cache = {}
    pages_dir = Path(pages_dir) if pages_dir else None
    for qi, q in enumerate(all_questions):
        if q["type"] != "未分类":
            continue
        page_items = load_ocr_page(ocr_dir, q["page"])
        # 跨页题: 本页末题内容延伸到页底且下页首题有延续(非DAY切换)时,
        # 合并下页顶部内容一起判定题型(题型特征如选择题选项常在下一页,
        # 不合并会因缺选项/多问号误判, 如打卡册 p1 题8 的 ABCD 在 p2 顶)
        if (qi + 1 < len(all_questions)
                and all_questions[qi + 1]["page"] == q["page"] + 1
                and not (all_questions[qi + 1]["num"] < q["num"])
                and q["content_bottom"] > 0):
            nxt_q = all_questions[qi + 1]
            pg = pages_dir / f"page_{q['page']:02d}.png" if pages_dir else None
            if pg is not None and pg.exists():
                cross_img = _imread_unicode(str(pg))
                if cross_img is not None:
                    page_h = cross_img.shape[0]
                    if q["content_bottom"] > page_h - CROSS_PAGE_THRESHOLD \
                            and nxt_q["y"] > CROSS_NEXT_PAGE_TOP:
                        nxt_items = load_ocr_page(ocr_dir, q["page"] + 1)
                        merged = [it for it in page_items if it["top_left_y"] >= q["y"]]
                        for it in nxt_items:
                            if it["top_left_y"] < nxt_q["y"]:
                                # 把下页内容 y 抬升到本页底之后, 才能通过 _classify_question 的 q_y 过滤
                                it = dict(it)
                                it["top_left_y"] += page_h
                                it["bottom_right_y"] += page_h
                                merged.append(it)
                        if merged:
                            page_items = merged
        # 范围上界 = 该页本题之后最近的 题目题号 或 区块标题(section, 如"知识点N")
        # 使题型判定不把下一知识点标题等行计入(避免影响问号/横线判断)
        next_y = 99999
        for p in pages_result:
            if p["page"] == q["page"]:
                for m in p["markers"]:
                    if m["y"] > q["y"] and m["type"] in ("question", "section"):
                        next_y = min(next_y, m["y"])
        # 跨页: 若下一题在不同页, 则扫描当前页剩余所有行
        if qi + 1 < len(all_questions) and all_questions[qi + 1]["page"] != q["page"]:
            next_y = 99999
        elif next_y < q["y"]:
            next_y = 99999
        # 加载页面图像(像素级填空横线检测)
        page_img = None
        if pages_dir is not None:
            page_img = page_cache.get(q["page"])
            if page_img is None:
                pg = pages_dir / f"page_{q['page']:02d}.png"
                if pg.exists():
                    page_img = _imread_unicode(str(pg))
                    page_cache[q["page"]] = page_img
        # 跨页合并: 若 page_items 中有块 y 超出当前页图像高度, 说明下页内容已被
        # 抬升合并进来, page_img 也需垂直拼接下页图像, 否则像素横线检测超出范围失效
        if page_img is not None and pages_dir is not None:
            page_h = page_img.shape[0]
            if any(it["top_left_y"] >= page_h for it in page_items):
                nxt_pg = pages_dir / f"page_{q['page'] + 1:02d}.png"
                if nxt_pg.exists():
                    nxt_img = _imread_unicode(str(nxt_pg))
                    if nxt_img is not None:
                        import numpy as np
                        min_w = min(page_img.shape[1], nxt_img.shape[1])
                        page_img = np.vstack([page_img[:, :min_w], nxt_img[:, :min_w]])
        cls = _classify_question(page_items, q["y"], next_y, page_img=page_img)
        if cls is None:
            pending.append({"page": q["page"], "num": q["num"], "y": q["y"],
                            "next_y": next_y if next_y != 99999 else None,
                            "text": q.get("text", "")})
        else:
            q["type"] = cls
            for p in pages_result:
                if p["page"] == q["page"]:
                    for m in p["markers"]:
                        if m["type"] == "question" and m["num"] == q["num"] and m["y"] == q["y"]:
                            m["qtype"] = cls

    # 为每题补充 content_bottom(该题范围 OCR 内容最大 bottom), 供 crop 跨页判定使用:
    # 跨页题(题干在本页底、选项/答案在下一页顶)的题号 y 可能不够靠下,
    # 用内容底判断才准确(如打卡册 p1 题8 题干到底但选项在 p2 顶)。
    page_markers_by_page = {p["page"]: p["markers"] for p in pages_result}
    for q in all_questions:
        markers = page_markers_by_page.get(q["page"], [])
        nxt = 999999
        for m in markers:
            if m["y"] > q["y"] and m["type"] in ("question", "section", "footer"):
                nxt = min(nxt, m["y"])
        items = load_ocr_page(ocr_dir, q["page"])
        bottoms = [it["bottom_right_y"] for it in items
                   if q["y"] <= it["top_left_y"] < nxt]
        q["content_bottom"] = int(max(bottoms)) if bottoms else int(q["y"])

    result = {
        "pages": pages_result,
        "questions": all_questions,
        "pending": pending,
        "total": len(all_questions),
    }
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nDone: {len(all_questions)} 题 -> {out}")
    return result


def main():
    ap = argparse.ArgumentParser(description="试卷版面分析")
    ap.add_argument("ocr_dir", help="ocr_page_*.json 所在目录")
    ap.add_argument("output_json", help="输出 markers.json 路径")
    ap.add_argument("--skip-pages", default=None,
                    help="跳过的页面(逗号分隔, 如教材目录页 '4,5,6,7')")
    ap.add_argument("--pages-dir", default=None,
                    help="页面PNG目录(启用像素级填空横线检测)")
    args = ap.parse_args()
    skip = [int(x) for x in args.skip_pages.split(",")] if args.skip_pages else None
    run_layout_analysis(args.ocr_dir, args.output_json, skip_pages=skip,
                        pages_dir=args.pages_dir)


if __name__ == "__main__":
    main()
