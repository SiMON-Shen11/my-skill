#!/usr/bin/env python3
"""
升级模块 2: 教材目录解析 -> 层级树
从电子版教材 PDF 解析「章 → 节 → 小节 → 课时/板块」层级树。

两种数据来源(按优先级):
  1. PDF 内嵌书签 (doc.get_toc()) —— 最可靠, 教材 PDF 常见
  2. 文字层目录页解析 —— 解析目录页文本行(第X章 / 25.1 / 25.2.1 / 第N课时 / 方法技巧)
     目录行页码从行尾数字提取; 若无法提取, 以正文层级状态机兜底。

输出 tree.json:
  [{"type":"chapter","number":25,"cn":"第二十五章","title":"一元二次方程",
    "start_page":1,
    "children":[
      {"type":"section","number":"25.1","ordinal":1,"title":"一元二次方程的概念",
       "start_page":2,"children":[
         {"type":"subsection","number":"25.2.1","ordinal":1,"title":"配方法",
          "start_page":4,"children":[
             {"type":"lesson","ordinal":1,"title":"第1课时 配方法(一)","start_page":4}]}]}]}]

用法:
    python toc_parser.py <input.pdf> <output_tree.json> [--toc-page N] [--dpi 200]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import fitz

# ---------------- 正则 ----------------
RE_CHAPTER = re.compile(r'^\s*第\s*([一二三四五六七八九十百]+)\s*章\s*(.*)$')
RE_SUBSEC = re.compile(r'^\s*(\d{1,2})\.(\d{1,2})\.(\d{1,2})\s*(.*)$')
RE_SECTION = re.compile(r'^\s*(\d{1,2})\.(\d{1,2})\s*(.*)$')
RE_LESSON = re.compile(r'^\s*第\s*(\d+)\s*课时\s*(.*)$')
# 教辅板块: 覆盖 基础题夯实/中档题运用/综合题探究/方法技巧/回归教材/题型研究/思想方法/
# 数学活动/综合与实践/一题多法/一题练透/图形研究/实践操作 等 (含 A/B/C 前缀, 如 "B中档题运用")
RE_BLOCK = re.compile(r'^\s*[A-C]?\s*(基础夯实|基础题夯实|中档题运用|综合题探究|方法技巧|回归教材|题型研究|思想方法|数学活动|综合与实践|一题多法|一题练透|图形研究|实践操作|易错警示|名师点拨|能力提升|综合运用|素养提升)\s*(.*)$')
RE_TRAILING_PAGE = re.compile(r'(?:[.．·]{2,}|[　 ]{2,})\s*(\d+)\s*$')  # 行尾页码(点线或空格分隔)

# 中文数字 -> 阿拉伯
_CN = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
def cn_to_int(s: str) -> int:
    s = s.strip()
    if not s:
        return 0
    if '十' in s:
        a, b = s.split('十', 1)
        tens = _CN.get(a, 1) if a else 1
        ones = _CN.get(b, 0) if b else 0
        return tens * 10 + ones
    return _CN.get(s, 0)


def clean_title(text: str) -> str:
    """去掉行尾页码与点线占位, 得到纯标题文本。"""
    t = text.strip()
    t = RE_TRAILING_PAGE.sub('', t).strip()
    t = re.sub(r'[.．·]{2,}$', '', t).strip()
    return t


def extract_trailing_page(text: str) -> int | None:
    m = RE_TRAILING_PAGE.search(text)
    return int(m.group(1)) if m else None


def get_pdf_text_lines(doc, page_index: int, zoom: float) -> list[dict]:
    """取某页所有文本行, 返回 [{text, y, x, font_size}] (坐标已转像素)。"""
    d = doc[page_index].get_text("dict")
    lines = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            size = max(s["size"] for s in spans)
            lines.append({
                "text": text, "y": y0 * zoom, "x": x0 * zoom,
                "font_size": size * zoom,
            })
    lines.sort(key=lambda l: l["y"])
    return lines


def is_toc_line(text: str) -> bool:
    """判断一行文本是否像目录条目。"""
    return bool(RE_CHAPTER.match(text) or RE_SUBSEC.match(text)
                or RE_SECTION.match(text) or RE_LESSON.match(text)
                or RE_BLOCK.match(text))


def auto_detect_toc_pages(doc, zoom: float, max_pages: int = 6) -> list[int]:
    """在前几页中自动找出目录页(命中目录条目最多的页)。"""
    best = []
    best_score = 0
    for i in range(min(len(doc), max_pages)):
        lines = get_pdf_text_lines(doc, i, zoom)
        score = sum(1 for l in lines if is_toc_line(l["text"]))
        has_toc_word = any('目录' in l["text"] for l in lines)
        if has_toc_word:
            score += 3
        if score > best_score:
            best_score = score
            best = [i]
        elif score == best_score and score > 0:
            best.append(i)
    return best


# ---------------- 目录行解析 -> 扁平节点 ----------------
def parse_toc_lines(lines: list[dict]) -> list[dict]:
    """解析目录文本行, 返回扁平节点序列。"""
    nodes = []
    for l in lines:
        text = l["text"]
        m = RE_CHAPTER.match(text)
        if m:
            num = cn_to_int(m.group(1))
            nodes.append({"type": "chapter", "number": num,
                          "title": clean_title(m.group(2)) or text,
                          "start_page": extract_trailing_page(text),
                          "y": l["y"]})
            continue
        m = RE_SUBSEC.match(text)
        if m:
            num = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            nodes.append({"type": "subsection", "number": num,
                          "ordinal": int(m.group(3)),
                          "title": clean_title(m.group(4)) or text,
                          "start_page": extract_trailing_page(text), "y": l["y"]})
            continue
        m = RE_SECTION.match(text)
        if m:
            num = f"{m.group(1)}.{m.group(2)}"
            nodes.append({"type": "section", "number": num,
                          "ordinal": int(m.group(2)),
                          "title": clean_title(m.group(3)) or text,
                          "start_page": extract_trailing_page(text), "y": l["y"]})
            continue
        m = RE_LESSON.match(text)
        if m:
            nodes.append({"type": "lesson", "ordinal": int(m.group(1)),
                          "title": clean_title(text),
                          "start_page": extract_trailing_page(text), "y": l["y"]})
            continue
        m = RE_BLOCK.match(text)
        if m:
            nodes.append({"type": "block", "block": m.group(1),
                          "title": clean_title(text),
                          "start_page": extract_trailing_page(text), "y": l["y"]})
            continue
    return nodes


def build_tree(nodes: list[dict]) -> list[dict]:
    """扁平节点 -> 层级树。课时挂到最近小节(若无小节则挂到节); 板块挂到节。"""
    chapters: list[dict] = []
    cur_ch = cur_sec = cur_sub = None
    for n in nodes:
        if n["type"] == "chapter":
            cur_ch = {"type": "chapter", "number": n["number"],
                      "title": n["title"], "start_page": n.get("start_page"),
                      "children": []}
            chapters.append(cur_ch)
            cur_sec = cur_sub = None
            continue
        if not chapters:  # 目录前没有章标题时, 用节号推断章
            num = n.get("number", "")
            m = re.match(r'^(\d+)\.', str(num))
            ch_num = int(m.group(1)) if m else 0
            cur_ch = {"type": "chapter", "number": ch_num, "title": f"第{ch_num}章",
                      "start_page": None, "children": []}
            chapters.append(cur_ch)
        if n["type"] == "section":
            cur_sec = {"type": "section", "number": n["number"],
                       "ordinal": n.get("ordinal"), "title": n["title"],
                       "start_page": n.get("start_page"), "children": []}
            cur_ch["children"].append(cur_sec)
            cur_sub = None
        elif n["type"] == "subsection":
            cur_sub = {"type": "subsection", "number": n["number"],
                       "ordinal": n.get("ordinal"), "title": n["title"],
                       "start_page": n.get("start_page"), "children": []}
            (cur_sec["children"] if cur_sec else cur_ch["children"]).append(cur_sub)
        elif n["type"] == "lesson":
            node = {"type": "lesson", "ordinal": n.get("ordinal"),
                    "title": n["title"], "start_page": n.get("start_page")}
            if cur_sub is not None:
                cur_sub["children"].append(node)
            elif cur_sec is not None:
                cur_sec["children"].append(node)
        elif n["type"] == "block":
            node = {"type": "block", "block": n["block"], "title": n["title"],
                    "start_page": n.get("start_page")}
            if cur_sub is not None:
                cur_sub["children"].append(node)
            elif cur_sec is not None:
                cur_sec["children"].append(node)
            else:
                cur_ch["children"].append(node)
    return chapters


def extract_toc(pdf_path: str, toc_page: int | None = None,
                dpi: int = 200) -> dict:
    """提取层级树。优先内嵌书签, 其次目录页文本解析, 再次扫描版目录页 OCR。"""
    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    result = {"source": "bookmark", "tree": [], "toc_pages": []}

    # 策略1: 内嵌书签
    bm = doc.get_toc(simple=True)  # [(level, title, page), ...]
    if bm:
        tree = build_tree([{"type": _bm_type(level), "number": _bm_number(level, title),
                            "ordinal": _bm_number(level, title),
                            "title": title, "start_page": page}
                           for level, title, page in bm])
        result["source"] = "bookmark"
        result["tree"] = tree
        doc.close()
        return result

    # 策略2: 目录页文本解析
    if toc_page is not None:
        pages = [toc_page - 1]
    else:
        pages = auto_detect_toc_pages(doc, zoom)
    result["toc_pages"] = [p + 1 for p in pages]
    all_lines = []
    for p in pages:
        all_lines.extend(get_pdf_text_lines(doc, p, zoom))
    nodes = parse_toc_lines(all_lines)
    if nodes:
        result["source"] = "text-layer"
        result["tree"] = build_tree(nodes)
        doc.close()
        return result

    # 策略3: 扫描版教材(无文字层) -> 渲染目录候选页 + PaddleOCR -> 目录行
    doc.close()
    return extract_toc_ocr(pdf_path, toc_page, dpi)


def extract_toc_ocr(pdf_path: str, toc_page: int | None, dpi: int) -> dict:
    """扫描版教材目录解析: 渲染候选目录页 -> PaddleOCR -> 目录行 -> 层级树。

    - 指定 --toc-page N 时, 以 N 为中心取前后共 5 页窗口 (目录常跨页);
    - 未指定时扫描前 8 页自动挑目录条目命中页。
    """
    import tempfile
    base = Path(__file__).resolve().parent.parent / "exam-question-cutter" / "scripts"
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    from ocr import run_ocr  # noqa: E402

    doc = fitz.open(pdf_path)
    if toc_page is not None:
        candidates = list(range(max(1, toc_page - 2),
                                min(len(doc), toc_page + 2) + 1))
    else:
        candidates = list(range(1, min(len(doc), 8) + 1))

    with tempfile.TemporaryDirectory(prefix="toc_ocr_") as tmp:
        tmp = Path(tmp)
        png_dir = tmp / "pages"
        png_dir.mkdir()
        for p in candidates:
            pix = doc[p - 1].get_pixmap(dpi=dpi)
            pix.save(str(png_dir / f"page_{p:02d}.png"))
        ocr_out = tmp / "ocr"
        run_ocr(str(png_dir), str(ocr_out), "paddleocr")
        all_lines = []
        toc_pages = []
        for p in candidates:
            f = ocr_out / f"ocr_page_{p:02d}.json"
            if not f.exists():
                continue
            data = json.load(open(f, encoding="utf-8"))
            page_lines = []
            for it in data.get("ocr_result", []):
                page_lines.append({
                    "text": it.get("content", "").strip(),
                    "y": it.get("top_left_y", 0),
                    "x": it.get("top_left_x", 0),
                })
            page_lines.sort(key=lambda l: l["y"])
            toc_like = sum(1 for l in page_lines if is_toc_line(l["text"]))
            if toc_like >= 3:
                toc_pages.append(p)
                all_lines.extend(page_lines)
    doc.close()
    return {"source": "ocr", "toc_pages": toc_pages,
            "tree": build_tree(parse_toc_lines(all_lines))}


def _bm_type(level: int) -> str:
    return {1: "chapter", 2: "section", 3: "subsection"}.get(level, "section")


def _bm_number(level: int, title: str) -> int | None:
    m = re.match(r'^(\d+)', title.strip())
    if m:
        return int(m.group(1))
    if level == 1:
        m2 = re.match(r'^第([一二三四五六七八九十百]+)章', title.strip())
        return cn_to_int(m2.group(1)) if m2 else None
    return None


def main():
    ap = argparse.ArgumentParser(description="教材目录解析 -> 层级树")
    ap.add_argument("pdf", help="输入教材 PDF")
    ap.add_argument("output_json", help="输出 tree.json")
    ap.add_argument("--toc-page", type=int, default=None, help="目录页页码(1-based)")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()
    result = extract_toc(args.pdf, args.toc_page, args.dpi)
    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n来源: {result['source']}, 目录页: {result['toc_pages']}")
    print(f"章数: {len(result['tree'])}")
    for ch in result["tree"]:
        print(f"  第{ch['number']}章 {ch['title']} "
              f"({len(ch['children'])} 节)")
    print(f"\nDone -> {args.output_json}")


if __name__ == "__main__":
    main()
