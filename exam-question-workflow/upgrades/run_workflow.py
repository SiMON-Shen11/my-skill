#!/usr/bin/env python3
"""
升级模块 5: 端到端工作流编排器
串联: 页面渲染 → OCR(文字层/Agent/像素/本地引擎) → 目录解析 → 版面分析
     → 图形检测 → 题目切分 → 层级命名归档

附加信息(增强 Agent / 提升准确率):
  --kind textbook|exam   输入类型: 教材(启用层级识别) / 试卷(仅题型分类)
  --toc-page N           教材目录页页码(1-based), 不传则自动检测
  --chapter N            章号提示(可选)
  --subject 数学         学科提示(可选, 影响题型/公式处理提示)

用法:
  # 电子版教材(有文字层, 自动用文字层OCR)
  python run_workflow.py 教材.pdf --kind textbook --workdir ./work1

  # 扫描版教材(需要OCR引擎, 可用Agent视觉或PaddleOCR)
  python run_workflow.py 扫描教材.pdf --kind textbook --toc-page 3 --ocr-backend agent

  # 试卷(无层级, 按题型归档)
  python run_workflow.py 试卷.pdf --kind exam --workdir ./work2

输出:
  <workdir>/pages/page_XX.png
  <workdir>/ocr/ocr_page_XX.json
  <workdir>/tree.json          (教材: 层级树)
  <workdir>/markers.json
  <workdir>/figures.json
  <workdir>/output/meta.json   (切分结果)
  <workdir>/output_hier/...    (按层级命名归档 + final_meta.json)
"""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "exam-question-cutter" / "scripts"
UPGRADES = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(UPGRADES))


def step(name):
    print(f"\n{'=' * 56}\n  {name}\n{'=' * 56}")


def has_text_layer(pdf_path: str) -> bool:
    try:
        import fitz
    except ImportError:
        return False
    doc = fitz.open(pdf_path)
    total = 0
    for page in doc:
        total += len(page.get_text().strip())
    doc.close()
    return total > 50


def check_gpu() -> tuple:
    """检测 PaddleOCR 可用的 GPU 是否正常。返回 (可用: bool, 说明: str)。

    判定标准: paddle 已编译 CUDA 支持 + 存在 CUDA 设备 + 实际能初始化 GPU 上下文并跑通张量运算。
    只负责"决策走哪条 OCR 路", 不在此加载模型。
    """
    try:
        import paddle
    except ImportError:
        return False, "未安装 paddle"
    try:
        if not paddle.device.is_compiled_with_cuda():
            return False, "paddle 未编译 CUDA 支持"
        n = paddle.device.cuda.device_count()
        if n < 1:
            return False, "未检测到 CUDA 设备"
        paddle.device.set_device("gpu:0")
        a = paddle.full([1], 1.0, dtype="float32")
        b = paddle.matmul(a, a)
        b.numpy()  # 强制同步, 触发真实 GPU 计算
        return True, f"可用 (CUDA 设备 {n} 张)"
    except Exception as e:
        return False, f"不可用: {e}"


def _imread_unicode(path):
    """cv2.imread 不支持中文/非ASCII路径, 用 np.fromfile + imdecode 兼容 Windows。"""
    import numpy as _np
    try:
        data = _np.fromfile(str(path), dtype=_np.uint8)
        if data.size == 0:
            return None
        import cv2 as _cv2
        return _cv2.imdecode(data, _cv2.IMREAD_COLOR)
    except Exception:
        return None


def export_pending(pending: list[dict], output_dir: Path, workdir: Path,
                   pages_dir: Path = None) -> None:
    """把未分类题的切图导出到 output/pending/, 并生成待判断清单。

    直接从页面图按题目 y 坐标裁剪, 不依赖 crop 的 q{global_id} 命名。
    """
    import cv2
    pending_dir = output_dir / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    for f in pending_dir.glob("*.png"):
        f.unlink()
    items = []
    for i, pd_ in enumerate(pending):
        dst = pending_dir / f"p{pd_['page']:02d}_q{pd_['num']:02d}_i{i:02d}.png"
        if pages_dir is not None:
            pg = pages_dir / f"page_{pd_['page']:02d}.png"
            if pg.exists():
                img = _imread_unicode(str(pg))
                if img is not None:
                    h, w = img.shape[:2]
                    y0 = max(0, int(pd_['y']) - 25)
                    y1 = min(h, int(pd_.get('next_y') or h))
                    roi = img[y0:y1, 0:w]
                    # cv2.imwrite 不支持中文路径, 用 imencode+tofile 替代
                    cv2.imencode('.png', roi)[1].tofile(str(dst))
                    items.append({"page": pd_["page"], "num": pd_["num"],
                                  "text": pd_.get("text", ""), "png": str(dst)})
                    continue
        # 兜底: 从 crop 未分类目录按序号查找
        q_dir = output_dir / "questions" / "未分类"
        cand = sorted(q_dir.glob("q*.png")) if q_dir.exists() else []
        if i < len(cand) and cand:
            import shutil
            shutil.copy2(str(cand[i]), str(dst))
            items.append({"page": pd_["page"], "num": pd_["num"],
                          "text": pd_.get("text", ""), "png": str(dst)})
        else:
            items.append({"page": pd_["page"], "num": pd_["num"],
                          "text": pd_.get("text", ""), "png": "(未找到切图)"})
    with open(output_dir / "pending_questions.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def apply_pending_types(markers_json: Path, meta_json: Path,
                        pending_types: str, markers: dict) -> None:
    """把 Agent 判定的题型写回 markers.json 与 meta.json 的未分类题。"""
    if not Path(pending_types).exists():
        print(f"[ERROR] 未找到 {pending_types}", file=sys.stderr)
        sys.exit(1)
    types = json.load(open(pending_types, encoding="utf-8"))
    key2type = {(t["page"], t["num"]): t["type"] for t in types}
    n = 0
    for q in markers.get("questions", []):
        if q.get("type") == "未分类" and (q["page"], q["num"]) in key2type:
            q["type"] = key2type[(q["page"], q["num"])]
            n += 1
    for p in markers.get("pages", []):
        for m in p.get("markers", []):
            if m.get("type") == "question" and m.get("qtype") == "未分类" \
                    and (p["page"], m["num"]) in key2type:
                m["qtype"] = key2type[(p["page"], m["num"])]
    markers["pending"] = []
    with open(markers_json, "w", encoding="utf-8") as f:
        json.dump(markers, f, ensure_ascii=False, indent=2)
    # 同步 meta.json
    meta = json.load(open(meta_json, encoding="utf-8"))
    for q in meta.get("questions", []):
        if q.get("type") == "未分类" and (q.get("page"), q.get("num")) in key2type:
            q["type"] = key2type[(q["page"], q["num"])]
    with open(meta_json, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 回填 {n} 道未分类题题型")


def main():
    ap = argparse.ArgumentParser(description="试卷/教材 OCR 切题 + 层级命名工作流")
    ap.add_argument("input_pdf", help="输入 PDF (试卷或教材)")
    ap.add_argument("--kind", choices=["textbook", "exam"], default="textbook",
                    help="输入类型: textbook=教材(启用层级), exam=试卷")
    ap.add_argument("--subject", default=None, help="学科提示, 如 数学")
    ap.add_argument("--toc-page", type=int, default=None, help="目录页页码(1-based)")
    ap.add_argument("--chapter", type=int, default=None, help="章号提示")
    ap.add_argument("--ocr-backend", choices=["auto", "textlayer", "paddle", "agent", "pixel",
                                              "precomputed"], default="auto",
                    help="OCR 方式: auto=有文字层用文字层否则自动检测 / textlayer=强制文字层 "
                         "/ paddle=强制PaddleOCR(GPU, 即使有文字层也走OCR)")
    ap.add_argument("--precomputed-dir", default=None, help="预计算 OCR 目录")
    ap.add_argument("--pending-types", default=None,
                    help="Agent 判定的未分类题型结果 JSON([{page,num,type},...]), 覆盖未分类题后继续归档")
    ap.add_argument("--workdir", default=None, help="工作目录")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--flat", action="store_true", help="平铺命名(不建层级目录)")
    ap.add_argument("--auto-margin", action="store_true", help="自动检测页面边界")
    args = ap.parse_args()

    pdf = str(Path(args.input_pdf).resolve())
    stem = Path(pdf).stem
    workdir = Path(args.workdir or (stem + "_work")).resolve()
    pages_dir = workdir / "pages"
    ocr_dir = workdir / "ocr"
    prompts_dir = workdir / "prompts"
    tree_json = workdir / "tree.json"
    markers_json = workdir / "markers.json"
    figures_json = workdir / "figures.json"
    output_dir = workdir / "output"
    output_hier = workdir / "output_hier"

    print(f"输入: {pdf}\n类型: {args.kind} | 学科: {args.subject or '-'} "
          f"| 目录页: {args.toc_page or '自动'} | 章号: {args.chapter or '-'}")

    # 1. PDF 渲染
    from pdf_render import render_pdf
    step("1/7 PDF 渲染")
    render_pdf(pdf, str(pages_dir), args.dpi)

    # 2. OCR
    step("2/7 OCR 文字识别")
    backend_arg = args.ocr_backend
    if backend_arg == "auto":
        # 智能选择优先级: GPU PaddleOCR → 文字层提取 → CPU PaddleOCR → Agent 视觉识别(备选)
        gpu_ok, gpu_msg = check_gpu()
        if gpu_ok:
            print(f"[OCR] GPU 正常 ({gpu_msg}) → 使用 PaddleOCR/GPU")
            from ocr import run_ocr
            run_ocr(str(pages_dir), str(ocr_dir), "paddleocr", None)
        elif has_text_layer(pdf):
            print("[OCR] 未检测到可用 GPU → 探测到文字层 → 文字层提取")
            from pdf_text_ocr import text_to_ocr
            text_to_ocr(pdf, str(ocr_dir), args.dpi)
        else:
            print("[OCR] 未检测到可用 GPU 且无文字层 → 尝试 CPU PaddleOCR")
            try:
                from ocr import run_ocr
                run_ocr(str(pages_dir), str(ocr_dir), "paddleocr", None)
            except ImportError:
                print("[OCR] CPU PaddleOCR 不可用 → 改用 Agent 视觉识别(备选)")
                from agent_ocr import build_batch_prompts
                build_batch_prompts(str(pages_dir), str(prompts_dir))
                print(f"""
  提示词已生成: {prompts_dir}
  请逐页识别 pages/page_XX.png, 用 agent_ocr.py parse 写入 {ocr_dir}, 然后:
  python run_workflow.py {Path(pdf).name} --kind {args.kind} --workdir {workdir} --ocr-backend precomputed --precomputed-dir {ocr_dir}
""")
                sys.exit(0)
    elif backend_arg == "textlayer":
        from pdf_text_ocr import text_to_ocr
        text_to_ocr(pdf, str(ocr_dir), args.dpi)
    elif backend_arg == "agent":
        from agent_ocr import build_batch_prompts
        build_batch_prompts(str(pages_dir), str(prompts_dir))
        print(f"""
  提示词已生成: {prompts_dir}
  请逐页识别 pages/page_XX.png, 用 agent_ocr.py parse 写入 {ocr_dir}, 然后:
  python run_workflow.py {Path(pdf).name} --kind {args.kind} --workdir {workdir} --ocr-backend precomputed --precomputed-dir {ocr_dir}
""")
        sys.exit(0)
    elif backend_arg == "pixel":
        from pixel_ocr import cmd_detect
        cmd_detect(str(pages_dir), str(ocr_dir), str(workdir / "question_types.json"))
        print(f"  像素投影已生成题型模板, 请填写后继续(参考底座说明)")
        sys.exit(0)
    else:
        # paddle(强制GPU) / precomputed(已有OCR结果)
        from ocr import run_ocr
        backend = "paddleocr" if backend_arg == "paddle" else backend_arg
        run_ocr(str(pages_dir), str(ocr_dir), backend, args.precomputed_dir)

    # 3. 目录解析 (仅教材)
    skip_pages = []
    if args.kind == "textbook":
        step("3/7 教材目录解析 -> 层级树")
        from toc_parser import extract_toc
        tree = extract_toc(pdf, args.toc_page, args.dpi)
        tree_json.parent.mkdir(parents=True, exist_ok=True)
        with open(tree_json, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)
        print(f"  来源: {tree['source']} | 目录页: {tree['toc_pages']} | "
              f"章数: {len(tree['tree'])} -> {tree_json}")
        skip_pages = tree.get("toc_pages", [])
    else:
        print("  跳过(试卷模式无目录层级)")

    # 4. 版面分析
    from layout_analysis import run_layout_analysis
    step("4/7 版面分析")
    run_layout_analysis(str(ocr_dir), str(markers_json), skip_pages=skip_pages,
                        pages_dir=str(pages_dir))

    # 5. 图形检测
    from figure_detection import run_figure_detection
    step("5/7 图形边界检测")
    run_figure_detection(str(pages_dir), str(ocr_dir), str(figures_json))

    # 6. 题目切分
    from crop import run_crop
    step("6/7 题目切分")
    run_crop(str(pages_dir), str(ocr_dir), str(markers_json),
             str(figures_json), str(output_dir), auto_margin=args.auto_margin)

    # 6.5 Agent 联动: 三步判断(选择→填空→解答)后仍无法确定的题, 导出切图交 Agent 视觉判断
    markers = json.load(open(markers_json, encoding="utf-8"))
    pending = markers.get("pending", [])
    if pending and not args.pending_types:
        export_pending(pending, output_dir, workdir, pages_dir=pages_dir)
        print(f"""
  ⚠ 有 {len(pending)} 道题经(选择→填空→解答)三步判断仍无法确定题型。
  已导出待判断切图: {output_dir / 'pending'}/
  请 Agent 逐张查看 {output_dir / 'pending_questions.json'} 中的图片并判断题型,
  填写 {workdir / 'pending_types.json'} (格式: [{{'page':页码,'num':题号,'type':'填空题'}},...]),
  然后重跑: python run_workflow.py {Path(pdf).name} --kind {args.kind} --workdir {workdir}
            --ocr-backend precomputed --precomputed-dir {ocr_dir} --pending-types {workdir / 'pending_types.json'}
""")
        sys.exit(0)
    if args.pending_types:
        apply_pending_types(markers_json, output_dir / "meta.json", args.pending_types, markers)
        markers = json.load(open(markers_json, encoding="utf-8"))
        print(f"  ✓ 已应用 Agent 判定: {args.pending_types}")

    # 7. 层级状态机 + 命名归档
    step("7/7 层级命名 + 归档")
    if args.kind == "textbook":
        from hierarchy_tracker import run_hierarchy_tracker
        tree_data = json.load(open(tree_json, encoding="utf-8")).get("tree", [])
        hierarchy_json = workdir / "hierarchy.json"
        run_hierarchy_tracker(str(markers_json), str(ocr_dir), str(hierarchy_json),
                              tree=tree_data, chapter_hint=args.chapter)
    else:
        # 试卷: 无层级, 构造空层级映射
        hierarchy_json = workdir / "hierarchy.json"
        markers = json.load(open(markers_json, encoding="utf-8"))
        empty = {"questions": [
            {"page": q["page"], "num": q["num"], "type": q.get("type", "未分类"),
             "y": q.get("y", 0), "path": {}} for q in markers.get("questions", [])]}
        with open(hierarchy_json, "w", encoding="utf-8") as f:
            json.dump(empty, f, ensure_ascii=False, indent=2)
        print(f"  试卷模式: 空层级映射 -> {hierarchy_json}")

    from naming import rename_organize
    rename_organize(str(output_dir / "meta.json"), str(hierarchy_json),
                    str(output_hier), organize=not args.flat)

    print(f"\n{'=' * 56}\n  全部完成!\n"
          f"  工作目录: {workdir}\n"
          f"  层级命名结果: {output_hier}\n"
          f"  final_meta.json: {output_hier / 'final_meta.json'}\n{'=' * 56}")


if __name__ == "__main__":
    main()
