#!/usr/bin/env python3
"""
升级模块 4: 层级命名 + 按层级归档
把切分结果(meta.json 的 questions)按题目层级路径命名并归档。

命名规则(与目录页层级一一对应):
    文件名: 第{章}章_第{节}节_第{小节}小节_第{课时}课时_{题型}_第{NN}题.png
    例:    第25章_第2节_第1小节_第1课时_选择题_第01题.png
    板块题(无小节/课时): 第25章_第2节_方法技巧_选择题_第01题.png
    试卷(无层级信息):    {题型}_第{NN}题.png  (按题型归入对应目录)

两种组织方式:
  --organize  按层级建目录: 第25章/第2节/第1小节/第1课时/选择题_第01题.png
  --flat      平铺命名(不建层级目录), 文件名携带完整层级路径

输出:
    <output_root>/...层级目录/图片
    <output_root>/final_meta.json  (每题含 path + file + size 等完整信息)

用法:
    python naming.py <crop_meta.json> <hierarchy.json> <output_root>
                     [--organize|--flat] [--sep _]
"""
import argparse
import json
import shutil
from pathlib import Path


def path_label(path: dict) -> dict:
    """生成层级标签, 缺失层级留 None。"""
    return {
        "chapter": path.get("chapter"),
        "chapter_cn": path.get("chapter_cn"),
        "section_ordinal": path.get("section_ordinal"),
        "subsection_ordinal": path.get("subsection_ordinal"),
        "lesson": path.get("lesson"),
        "block": path.get("block"),
    }


def build_flat_name(lbl: dict, qtype: str, idx: int, sep: str = "_") -> str:
    parts = []
    if lbl.get("chapter") is not None:
        parts.append(f"第{lbl['chapter']}章")
    if lbl.get("section_ordinal") is not None:
        parts.append(f"第{lbl['section_ordinal']}节")
    if lbl.get("subsection_ordinal") is not None:
        parts.append(f"第{lbl['subsection_ordinal']}小节")
    if lbl.get("lesson") is not None:
        parts.append(f"第{lbl['lesson']}课时")
    if lbl.get("block"):
        parts.append(lbl["block"])
    if not parts:
        return f"{qtype}_第{idx:02d}题.png"
    parts.append(f"{qtype}_第{idx:02d}题")
    return sep.join(parts) + ".png"


def build_dir_parts(lbl: dict, qtype: str = "未分类") -> list[str]:
    parts = []
    if lbl.get("chapter") is not None:
        parts.append(f"第{lbl['chapter']}章")
    if lbl.get("section_ordinal") is not None:
        parts.append(f"第{lbl['section_ordinal']}节")
    if lbl.get("subsection_ordinal") is not None:
        parts.append(f"第{lbl['subsection_ordinal']}小节")
    if lbl.get("lesson") is not None:
        parts.append(f"第{lbl['lesson']}课时")
    if lbl.get("block"):
        parts.append(lbl["block"])
    return parts or [qtype]


def rename_organize(crop_meta_path: str, hierarchy_path: str, output_root: str,
                    organize: bool = True, sep: str = "_") -> dict:
    crop_meta = json.load(open(crop_meta_path, encoding="utf-8"))
    hier = json.load(open(hierarchy_path, encoding="utf-8"))
    qs = crop_meta.get("questions", [])
    hier_map = {(h["page"], h["num"]): h for h in hier.get("questions", [])}

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    # 清理旧归档图片, 防止重跑(如题型重判)后旧分类文件残留
    for old in root.rglob("*.png"):
        try:
            old.unlink()
        except OSError:
            pass
    src_questions_dir = Path(crop_meta_path).parent / "questions"

    # 统计每题序号: 按 (路径, 题型) 计数
    counters: dict[tuple, int] = {}
    final = []
    for q in qs:
        key = (q.get("page"), q.get("original_num", q.get("num")))
        h = hier_map.get(key, {})
        path = h.get("path", {}) if h else {}
        lbl = path_label(path)
        qtype = q.get("type", "未分类")
        dir_parts = build_dir_parts(lbl, qtype)
        counter_key = (tuple(dir_parts), qtype)
        counters[counter_key] = counters.get(counter_key, 0) + 1
        idx = counters[counter_key]

        flat = build_flat_name(lbl, qtype, idx, sep)
        if organize:
            rel_dir = Path(*dir_parts)
            dest_dir = root / rel_dir
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{qtype}_第{idx:02d}题.png"
        else:
            dest = root / flat

        # 复制切分好的图片到归档位置
        src = src_questions_dir / q.get("file", "")
        if src.exists():
            shutil.copy2(str(src), str(dest))
            moved = True
        else:
            moved = False

        final.append({
            **{k: v for k, v in q.items()},
            "path": path,
            "hier_label": lbl,
            "idx_in_group": idx,
            "final_file": str(dest),
            "copied": moved,
        })

    meta_out = {
        "total_questions": len(final),
        "organize": organize,
        "naming_example": build_flat_name(path_label(final[0]["path"]) if final else {},
                                          final[0].get("type", "选择题") if final else "选择题",
                                          1, sep),
        "questions": final,
    }
    with open(root / "final_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta_out, f, ensure_ascii=False, indent=2)
    print(f"\n命名示例: {meta_out['naming_example']}")
    print(f"题目总数: {len(final)}, 已归档: {sum(1 for x in final if x['copied'])}")
    print(f"输出: {root}")
    return meta_out


def main():
    ap = argparse.ArgumentParser(description="题目层级命名 + 归档")
    ap.add_argument("crop_meta_json", help="切分输出 meta.json")
    ap.add_argument("hierarchy_json", help="层级状态机 hierarchy.json")
    ap.add_argument("output_root", help="归档输出根目录")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--organize", action="store_true", help="按层级建目录(默认)")
    g.add_argument("--flat", action="store_true", help="平铺命名")
    ap.add_argument("--sep", default="_", help="命名分隔符")
    args = ap.parse_args()
    rename_organize(args.crop_meta_json, args.hierarchy_json, args.output_root,
                    organize=not args.flat, sep=args.sep)


if __name__ == "__main__":
    main()
