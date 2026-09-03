#!/usr/bin/env python3
"""
升级模块 3: 章节层级状态机
为每个题目(来自 markers.json)计算所在教材层级路径: 章→节→小节→课时/板块。

原理:
  - 逐页读取 OCR/文字层行, 用正则识别正文中的层级标题
    (第X章 / 25.1 / 25.2.1 / 第N课时 / 方法技巧等), 维护当前层级上下文;
  - 每个题目标记(题号行)出现时, 快照当前层级上下文作为该题的层级路径;
  - 状态跨页保持, 支持跨页章节延续。
  - 若提供 tree.json(目录树), 用其校验层级编号合法性并补充章标题。

输出 hierarchy.json:
  {"questions": [
     {"page":1,"num":1,"type":"选择题","path":{
         "chapter":25,"chapter_cn":"第二十五章","chapter_title":"一元二次方程",
         "section":"25.2","section_ordinal":2,
         "subsection":"25.2.1","subsection_ordinal":1,
         "lesson":1,"block":null }}, ...],
   "headers":[...]}

用法:
    python hierarchy_tracker.py <markers.json> <ocr_dir> <output.json>
        [--tree tree.json] [--chapter 25]
"""
import argparse
import json
import re
import sys
from pathlib import Path

RE_CHAPTER = re.compile(r'^\s*第\s*([一二三四五六七八九十百]+)\s*章')
RE_SUBSEC = re.compile(r'^\s*(\d{1,2})\.(\d{1,2})\.(\d{1,2})\b')
RE_SECTION = re.compile(r'^\s*(\d{1,2})\.(\d{1,2})\b')
RE_LESSON = re.compile(r'^\s*第\s*(\d+)\s*课时')
# 教辅板块 (含 A/B/C 前缀, 如 "B中档题运用"); 名称取 canonical 板块名(去前缀)
RE_BLOCK = re.compile(r'^\s*[A-C]?\s*(基础夯实|基础题夯实|中档题运用|综合题探究|方法技巧|回归教材|题型研究|思想方法|数学活动|综合与实践|一题多法|一题练透|图形研究|实践操作|易错警示|名师点拨|能力提升|综合运用|素养提升)\s*')
# 排除项: 选项行 / 子问行 / 题号行 / 页脚
RE_SKIP = re.compile(r'^[（(][A-Da-d][)）]|^[A-Da-d][.．]\s|^[（(]\d+[)）]|^[①②③④⑤⑥⑦⑧⑨⑩]')

_CN = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
def cn_to_int(s: str) -> int:
    s = s.strip()
    if not s:
        return 0
    if '十' in s:
        a, b = s.split('十', 1)
        return (_CN.get(a, 1) if a else 1) * 10 + (_CN.get(b, 0) if b else 0)
    return _CN.get(s, 0)


# 板块名归一化: 归一 OCR 变体为规范名, 避免同一板块归档成两个目录
_BLOCK_NORM = {
    '基础夯实': '基础题夯实',
    '能力提升': '综合题探究',
    '综合运用': '综合题探究',
}
def _normalize_block(name: str) -> str:
    return _BLOCK_NORM.get(name, name)


def load_ocr_lines(ocr_dir: Path, page: int) -> list[dict]:
    f = ocr_dir / f"ocr_page_{page:02d}.json"
    if not f.exists():
        return []
    data = json.load(open(f, encoding="utf-8"))
    items = data.get("ocr_result", [])
    lines = []
    for it in items:
        lines.append({
            "text": it.get("content", "").strip(),
            "x": it.get("top_left_x", 0),
            "y": it.get("top_left_y", 0),
        })
    lines.sort(key=lambda l: l["y"])
    return lines


class HierarchyState:
    def __init__(self, chapter_hint: int | None = None):
        self.chapter = chapter_hint
        self.chapter_cn = None
        self.chapter_title = None
        self.section = None       # "25.2"
        self.section_ordinal = None
        self.subsection = None    # "25.2.1"
        self.subsection_ordinal = None
        self.lesson = None
        self.block = None

    def snapshot(self) -> dict:
        return {
            "chapter": self.chapter,
            "chapter_cn": self.chapter_cn,
            "chapter_title": self.chapter_title,
            "section": self.section,
            "section_ordinal": self.section_ordinal,
            "subsection": self.subsection,
            "subsection_ordinal": self.subsection_ordinal,
            "lesson": self.lesson,
            "block": self.block,
        }

    def apply(self, line: dict, valid: dict) -> bool:
        """识别一行是否为层级标题并更新状态。valid 用于编号合法性校验(可空)。"""
        text = line["text"]
        x = line.get("x", 0)
        # 排除窄列文字(如右侧页码)与明显非标题行
        if not text or x > 900:
            return False
        if RE_SKIP.match(text):
            return False

        m = RE_CHAPTER.match(text)
        if m:
            self.chapter = cn_to_int(m.group(1))
            self.chapter_cn = m.group(1)
            self.chapter_title = text.strip()
            self.section = self.subsection = None
            self.section_ordinal = self.subsection_ordinal = None
            self.lesson = self.block = None
            return True

        m = RE_SUBSEC.match(text)
        if m:
            num = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            if valid and valid.get("subsections") and num not in valid["subsections"]:
                return False
            self.subsection = num
            self.subsection_ordinal = int(m.group(3))
            # 小节同时给出所属节
            self.section = f"{m.group(1)}.{m.group(2)}"
            self.section_ordinal = int(m.group(2))
            self.lesson = self.block = None
            return True

        m = RE_SECTION.match(text)
        if m:
            num = f"{m.group(1)}.{m.group(2)}"
            if valid and valid.get("sections") and num not in valid["sections"]:
                return False
            self.section = num
            self.section_ordinal = int(m.group(2))
            self.subsection = self.subsection_ordinal = None
            self.lesson = self.block = None
            return True

        m = RE_LESSON.match(text)
        if m:
            self.lesson = int(m.group(1))
            self.block = None
            return True

        m = RE_BLOCK.match(text)
        if m:
            # 板块嵌套在课时下(第N课时 → 基础题夯实/中档题运用...), 不重置课时
            self.block = _normalize_block(m.group(1))
            return True

        return False


def build_valid_set(tree: list[dict]) -> dict:
    """从目录树收集合法编号集合, 用于校验正文标题。"""
    sections, subsections = set(), set()
    for ch in tree:
        for sec in ch.get("children", []):
            if sec["type"] == "section":
                sections.add(sec["number"])
                for sub in sec.get("children", []):
                    if sub["type"] == "subsection":
                        subsections.add(sub["number"])
    return {"sections": sections, "subsections": subsections}


def run_hierarchy_tracker(markers_json: str, ocr_dir: str, output_json: str,
                          tree: list[dict] | None = None,
                          chapter_hint: int | None = None) -> dict:
    markers = json.load(open(markers_json, encoding="utf-8"))
    questions = sorted(markers.get("questions", []),
                       key=lambda q: (q["page"], q.get("y", 0)))
    valid = build_valid_set(tree) if tree else {}
    state = HierarchyState(chapter_hint)

    # 逐页处理: 该页 OCR 行(标题)与题目混合, 严格按 y 顺序推进状态再快照,
    # 保证"课时/板块切换只影响其后的题目"
    headers = []
    results = []
    cur_page = None
    page_items = []  # (y, kind, obj)  kind: line / question

    def flush_page(items):
        nonlocal state
        for y, kind, obj in sorted(items, key=lambda t: t[0]):
            if kind == "line":
                if state.apply(obj, valid):
                    headers.append({"page": obj["page"], "y": round(y, 1),
                                    "text": obj["text"], "path": state.snapshot()})
            else:
                results.append({
                    "page": obj["page"], "num": obj["num"],
                    "type": obj.get("type", "未分类"),
                    "y": y, "path": state.snapshot(),
                })

    for q in questions:
        page = q["page"]
        if page != cur_page:
            if cur_page is not None:
                flush_page(page_items)
            page_items = []
            cur_page = page
            for line in load_ocr_lines(Path(ocr_dir), page):
                line["page"] = page
                page_items.append((line["y"], "line", line))
        page_items.append((q.get("y", 0), "question", q))
    if page_items:
        flush_page(page_items)

    result = {"questions": results, "headers": headers}
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 统计
    with_path = sum(1 for r in results if r["path"].get("section"))
    print(f"\n题目总数: {len(results)}, 有章节归属: {with_path}, 层级标题数: {len(headers)}")
    if results:
        s = results[0]["path"]
        print(f"示例路径: 第{s.get('chapter')}章 节{s.get('section')} "
              f"小节{s.get('subsection')} 课时{s.get('lesson')} "
              f"板块{s.get('block')}")
    print(f"\nDone -> {output_json}")
    return result


def main():
    ap = argparse.ArgumentParser(description="题目层级状态机")
    ap.add_argument("markers_json", help="版面分析 markers.json")
    ap.add_argument("ocr_dir", help="ocr_page_XX.json 目录")
    ap.add_argument("output_json", help="输出 hierarchy.json")
    ap.add_argument("--tree", default=None, help="目录树 tree.json (可选, 用于校验)")
    ap.add_argument("--chapter", type=int, default=None, help="章号提示")
    args = ap.parse_args()
    tree = None
    if args.tree:
        tree = json.load(open(args.tree, encoding="utf-8")).get("tree", [])
    run_hierarchy_tracker(args.markers_json, args.ocr_dir, args.output_json,
                          tree=tree, chapter_hint=args.chapter)


if __name__ == "__main__":
    main()
