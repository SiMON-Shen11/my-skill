#!/usr/bin/env python3
"""
中学试卷自动切题 - 主入口
串联五个模块: PDF渲染 → OCR → 版面分析 → 图形检测 → 切分

用法:
    # 标准模式 (自动检测 OCR 后端)
    python3 run_pipeline.py <input.pdf> --workdir ./exam_work

    # 像素投影 OCR 模式 (推荐多类型试卷/打卡册)
    python3 run_pipeline.py <input.pdf> --ocr-backend pixel --workdir ./exam_work
    # → 生成题型模板后暂停, Agent 视觉识别题型并填写, 再运行:
    python3 run_pipeline.py <input.pdf> --workdir ./exam_work --skip-ocr --auto-margin

    # Agent 视觉 OCR 模式 (完整文字识别)
    python3 run_pipeline.py <input.pdf> --ocr-backend agent --workdir ./exam_work

    # 预计算 OCR 模式
    python3 run_pipeline.py <input.pdf> --ocr-backend precomputed --precomputed-dir <dir>

    # 非标准试卷/打卡册 (自动边界检测)
    python3 run_pipeline.py <input.pdf> --auto-margin

输出:
    <workdir>/pages/page_XX.png
    <workdir>/ocr/ocr_page_XX.json
    <workdir>/question_types.json  (pixel 模式)
    <workdir>/prompts/prompt_page_XX.txt  (agent 模式)
    <workdir>/markers.json
    <workdir>/figures.json
    <workdir>/output/questions/选择题/q01.png ...
    <workdir>/output/meta.json
    <workdir>/output/overlay_page_XX.png
"""
import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def step(name, fn, *args, **kwargs):
    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}")
    return fn(*args, **kwargs)


def main():
    ap = argparse.ArgumentParser(description="中学试卷自动切题")
    ap.add_argument("pdf", help="输入试卷 PDF")
    ap.add_argument("--workdir", default="./exam_work", help="工作目录")
    ap.add_argument("--dpi", type=int, default=200, help="PDF 渲染 DPI")
    ap.add_argument("--ocr-backend", default="auto",
                    choices=["auto", "paddleocr", "easyocr", "tesseract",
                             "precomputed", "agent", "pixel"])
    ap.add_argument("--precomputed-dir", help="预计算 OCR JSON 目录")
    ap.add_argument("--auto-margin", action="store_true",
                    help="自动检测每页内容左右边界 (适配非标准试卷/打卡册)")
    ap.add_argument("--skip-ocr", action="store_true",
                    help="跳过 OCR 步骤 (pages 和 ocr 已存在时继续后续步骤)")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    pages_dir = workdir / "pages"
    ocr_dir = workdir / "ocr"
    prompts_dir = workdir / "prompts"
    markers_json = workdir / "markers.json"
    figures_json = workdir / "figures.json"
    output_dir = workdir / "output"

    # 模块1: PDF 渲染
    from pdf_render import render_pdf
    step("1/5 PDF 渲染", render_pdf, args.pdf, str(pages_dir), args.dpi)

    # 模块2: OCR
    if args.skip_ocr:
        print(f"\n{'='*50}")
        print("  2/5 OCR 文字识别 (跳过, 使用已有结果)")
        print(f"{'='*50}")
        if not ocr_dir.exists():
            print(f"[ERROR] OCR 目录不存在: {ocr_dir}", file=sys.stderr)
            sys.exit(1)

    elif args.ocr_backend == "pixel":
        # 像素投影 OCR 模式: 检测题号 + 生成题型标注模板
        from pixel_ocr import cmd_detect
        template_path = workdir / "question_types.json"
        step("2/5 像素投影 OCR — 检测题号 + 生成题型模板",
             cmd_detect, str(pages_dir), str(ocr_dir), str(template_path))
        print(f"""
{'='*50}
  像素投影 OCR 模式 (推荐多类型试卷/打卡册)
{'='*50}
  题号已检测, 题型标注模板已生成: {template_path}

  下一步 (Agent 视觉识别题型):
  1. 逐页读取 pages/page_XX.png
  2. 按以下规则判断题型:
     - 选择题: 题目以"（ ）"结尾, 后方有 A/B/C/D 四个选项
     - 填空题: 有"______"填空横线 (子问中也有横线)
     - 解答题: 有(1)(2)子问, 且含"求/求证/试说明/问"等关键字
  3. 填写 {template_path}:
     {{"1": {{"1": "选择题", "2": "填空题", ...}}, "2": {{...}}}}
  4. 基于模板重新生成 OCR:
     python3 pixel_ocr.py generate {pages_dir} {ocr_dir} --types {template_path}
  5. 继续后续流程:
     python3 run_pipeline.py {args.pdf} --workdir {workdir} --skip-ocr {'--auto-margin' if args.auto_margin else ''}
{'='*50}
""")
        sys.exit(0)

    elif args.ocr_backend == "agent":
        # Agent 视觉 OCR 模式: 生成提示词, 暂停等待 Agent 识别
        from agent_ocr import build_batch_prompts
        step("2/5 Agent 视觉 OCR — 生成提示词",
             build_batch_prompts, str(pages_dir), str(prompts_dir))
        print(f"""
{'='*50}
  Agent 视觉 OCR 模式
{'='*50}
  提示词已生成: {prompts_dir}
  下一步 (Agent 执行):
  1. 逐页读取 pages/page_XX.png + prompts/prompt_page_XX.txt
  2. 用视觉能力识别文字+坐标, 按提示词要求输出 JSON
  3. 用 agent_ocr.py parse 解析并校准坐标:
     python3 agent_ocr.py parse <agent返回文本> {ocr_dir}/ocr_page_XX.json --page XX --calibrate pages/page_XX.png
  4. 验证 OCR 质量:
     python3 agent_ocr.py validate {ocr_dir}
  OCR 结果就绪后, 继续运行:
  python3 run_pipeline.py {args.pdf} --workdir {workdir} --skip-ocr {'--auto-margin' if args.auto_margin else ''}
{'='*50}
""")
        sys.exit(0)

    else:
        from ocr import run_ocr
        step("2/5 OCR 文字识别", run_ocr,
             str(pages_dir), str(ocr_dir), args.ocr_backend, args.precomputed_dir)

    # OCR 质量验证
    if args.ocr_backend in ("agent", "precomputed") or args.skip_ocr:
        from agent_ocr import validate_ocr_dir
        print(f"\n{'='*50}")
        print("  OCR 质量检查")
        print(f"{'='*50}")
        reports = validate_ocr_dir(str(ocr_dir))
        total_warnings = sum(len(r["warnings"]) for r in reports)
        if total_warnings > 0:
            print(f"\n  ⚠ 共 {total_warnings} 个警告, 建议检查 OCR 结果后继续")

    # 模块3: 版面分析
    from layout_analysis import run_layout_analysis
    step("3/5 版面分析", run_layout_analysis, str(ocr_dir), str(markers_json))

    # 模块4: 图形检测
    from figure_detection import run_figure_detection
    step("4/5 图形边界检测", run_figure_detection,
         str(pages_dir), str(ocr_dir), str(figures_json))

    # 模块5: 切分
    from crop import run_crop
    step("5/5 题目切分", run_crop,
         str(pages_dir), str(ocr_dir), str(markers_json),
         str(figures_json), str(output_dir),
         auto_margin=args.auto_margin)

    print(f"\n{'='*50}")
    print(f"  全部完成! 工作目录: {workdir}")
    print(f"  题目图片: {output_dir / 'questions'}")
    print(f"  整页预览: {output_dir}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
