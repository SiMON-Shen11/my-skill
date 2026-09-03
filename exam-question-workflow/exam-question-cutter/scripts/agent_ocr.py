#!/usr/bin/env python3
"""
Agent 视觉 OCR 辅助模块
========================
用于 Agent 调用场景: Agent 用视觉能力读取试卷页面图片, 本模块提供:
  1. 提示词生成器 — 生成结构化视觉识别提示词 (支持多种试卷类型)
  2. 结果解析器   — 解析 Agent 返回的 OCR 结果为标准 JSON
  3. 坐标校准器   — 用像素投影法校准 Agent 输出的 y 坐标精度
  4. 质量验证器   — 检查题号连续性、选项完整性、图形标题等

输出格式与 ocr.py 完全一致, 可直接供 layout_analysis / figure_detection / crop 使用。

用法:
  # 1. 生成提示词 (Agent 读取此提示词 + 页面图片后返回 OCR 结果)
  python3 agent_ocr.py prompt pages/page_01.png --page 1

  # 2. 解析 Agent 返回的文本为 OCR JSON
  python3 agent_ocr.py parse agent_response.txt ocr/ocr_page_01.json

  # 3. 校准坐标 (可选, 提高精度)
  python3 agent_ocr.py calibrate ocr/ocr_page_01.json pages/page_01.png

  # 4. 验证 OCR 质量
  python3 agent_ocr.py validate ocr/

  # 5. 一键生成所有页的提示词
  python3 agent_ocr.py batch-prompt pages/ prompts/
"""
import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

# ============================================================================
# 1. 提示词生成器
# ============================================================================

OCR_PROMPT_TEMPLATE = """你是一个精准的试卷 OCR 识别引擎。请识别这张试卷页面上的所有文字内容, 并按要求输出结构化数据。

## 页面信息
- 页码: 第 __PAGE_NUM__ 页
- 图片尺寸: __WIDTH__ x __HEIGHT__ 像素
- 坐标系: 左上角为 (0,0), x 向右增大, y 向下增大, 单位为像素

## 识别要求

### 必须识别的内容类型
请将每一行文字标注为以下类型之一:

| 类型标签 | 说明 | 示例 |
|----------|------|------|
| `section` | 大题/页面标题 | "一、选择题"、"第二部分 非选择题"、"期末打卡 DAY 1" |
| `question` | 题号行 (以数字+点开头) | "1. 已知..."、"12. 如图..." |
| `option` | 选择题选项 | "A. ..."、"（B）..." |
| `subquestion` | 解答题子问 | "（1）..."、"①..." |
| `figure_caption` | 图形标题 | "图1"、"图 4"、"（备用图）" |
| `footer` | 页脚 | "数学试卷 第1页（共7页）" |
| `text` | 其他正文内容 | 题干续行、说明文字等 |

### 坐标要求
- 每个文字行给出精确的边界框: top_left_x, top_left_y, bottom_right_x, bottom_right_y
- 坐标必须是 0 到 __WIDTH__/__HEIGHT__ 之间的整数
- 题号行的 top_left_x 应包含题号数字本身 (不要从题干开始)
- 选项行的 top_left_x 应包含选项标记 (A/B/C/D 或 （A）等)
- 如果一行文字跨越多列, 按实际视觉行分割

### 数学内容
- 完整识别数学公式、符号、上下标
- 分数、根号、希腊字母等用可读文本表示 (如 "x²"、"√3"、"α")
- 方程组用文字描述大括号范围 (如 "大括号{7x=y+4, 9x=y-8}")

### 特别注意
1. **题号行必须完整识别**, 包括题号数字和题干开头
2. **选项行必须识别选项标记** (A. B. C. D. 或 （A）（B）（C）（D）)
3. **图形标题"图N"必须识别**, 这是图形检测的关键
4. **页脚必须识别**, 用于下边界夹紧
5. 如果页面是双栏布局, 按从上到下、从左到右的阅读顺序排列
6. 不要遗漏任何一行文字, 包括小字说明

## 输出格式
严格输出以下 JSON 格式 (不要输出其他文字):

```json
{
  "page": __PAGE_NUM__,
  "width": __WIDTH__,
  "height": __HEIGHT__,
  "lines": [
    {
      "content": "文字内容",
      "type": "question|option|subquestion|section|figure_caption|footer|text",
      "top_left_x": 100,
      "top_left_y": 259,
      "bottom_right_x": 1064,
      "bottom_right_y": 290
    }
  ]
}
```

## 质量检查 (输出前自检)
- [ ] 所有题号行都标注为 `question` 类型
- [ ] 所有选项行都标注为 `option` 类型且包含 A/B/C/D 标记
- [ ] 所有"图N"标题都标注为 `figure_caption` 类型
- [ ] 页脚标注为 `footer` 类型
- [ ] 坐标在图片尺寸范围内
- [ ] 没有遗漏可见文字行
"""


def build_ocr_prompt(image_path: str, page_num: int = 1) -> str:
    """生成单页 OCR 视觉识别提示词。"""
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"无法读取图片: {image_path}")
    h, w = img.shape[:2]
    return (OCR_PROMPT_TEMPLATE
            .replace("__PAGE_NUM__", str(page_num))
            .replace("__WIDTH__", str(w))
            .replace("__HEIGHT__", str(h)))


def build_batch_prompts(pages_dir: str, output_dir: str) -> list[str]:
    """为所有页面生成提示词文件。"""
    pages_dir = Path(pages_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prompts = []
    for png in sorted(pages_dir.glob("page_*.png")):
        page_num = int(png.stem.split("_")[1])
        prompt = build_ocr_prompt(str(png), page_num)
        out_file = output_dir / f"prompt_page_{page_num:02d}.txt"
        out_file.write_text(prompt, encoding="utf-8")
        prompts.append(str(out_file))
        print(f"  生成提示词: {out_file.name}")
    return prompts


# ============================================================================
# 2. 结果解析器
# ============================================================================

def parse_agent_response(response_text: str) -> list[dict]:
    """解析 Agent 返回的 OCR 结果文本为标准格式。

    支持两种输入格式:
    1. 纯 JSON (Agent 严格按提示词输出)
    2. 包含 JSON 代码块的 Markdown 文本
    """
    text = response_text.strip()

    # 尝试提取 JSON 代码块
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试找到第一个 { 和最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start:end + 1])
        else:
            raise ValueError("无法解析 Agent 返回的 OCR 结果为 JSON")

    lines = data.get("lines", data.get("ocr_result", []))
    items = []
    for line in lines:
        content = line.get("content", "").strip()
        if not content:
            continue
        items.append({
            "content": content,
            "top_left_x": int(line.get("top_left_x", 0)),
            "top_left_y": int(line.get("top_left_y", 0)),
            "bottom_right_x": int(line.get("bottom_right_x", 0)),
            "bottom_right_y": int(line.get("bottom_right_y", 0)),
            "line_type": line.get("type", "text"),  # 辅助字段, 不影响后续模块
            "confidence": line.get("confidence", 1.0),
        })

    # 按 y 坐标排序
    items.sort(key=lambda r: (r["top_left_y"], r["top_left_x"]))
    return items


def save_ocr_json(items: list[dict], output_path: str, page_num: int = 1):
    """保存为标准 OCR JSON 格式 (与 ocr.py 输出一致)。"""
    result = {
        "ocr_result": items,
        "page": page_num,
        "source": "agent_vision_ocr",
        "success": True,
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  保存 OCR: {out} ({len(items)} 行)")


# ============================================================================
# 3. 坐标校准器
# ============================================================================

def calibrate_coordinates(items: list[dict], image_path: str,
                          y_tolerance: int = 15) -> list[dict]:
    """用像素投影法校准 Agent 输出的 y 坐标。

    Agent 视觉识别的 y 坐标可能有 ±10px 偏差, 本函数在图像中找到
    对应 y 范围内的实际文字行边界, 校准 top_left_y / bottom_right_y。
    x 坐标不校准 (Agent 对水平位置的判断通常较准)。
    """
    img = cv2.imread(image_path)
    if img is None:
        print(f"  [WARN] 无法读取图片, 跳过坐标校准: {image_path}", file=sys.stderr)
        return items

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    row_proj = np.sum(binary, axis=1)  # 每行的非白像素数

    calibrated = []
    for item in items:
        y_center = (item["top_left_y"] + item["bottom_right_y"]) // 2
        search_top = max(0, y_center - y_tolerance - 20)
        search_bottom = min(h, y_center + y_tolerance + 20)

        # 在搜索范围内找到实际文字行的上下边界
        region = row_proj[search_top:search_bottom]
        text_rows = np.where(region > 0)[0]

        if len(text_rows) > 0:
            actual_top = int(search_top + text_rows[0])
            actual_bottom = int(search_top + text_rows[-1] + 1)
            # 只在偏差不大时校准, 避免匹配到错误的行
            if abs(actual_top - item["top_left_y"]) < y_tolerance * 2:
                item["top_left_y"] = max(0, actual_top - 2)
                item["bottom_right_y"] = min(h, actual_bottom + 2)

        calibrated.append(item)

    return calibrated


# ============================================================================
# 4. 质量验证器
# ============================================================================

RE_QUESTION = re.compile(r'^\s*(\d+)[.．]\s*')
RE_OPTION = re.compile(r'^\s*[（(][A-D][）)]|^\s*[A-D][.．]\s')
RE_FIGURE = re.compile(r'图\s*\d+')
RE_FOOTER = re.compile(r'第\d+页|共\d+页|试卷.*第')


def validate_ocr_page(items: list[dict], page_num: int) -> dict:
    """验证单页 OCR 质量, 返回检查报告。"""
    report = {
        "page": page_num,
        "total_lines": len(items),
        "questions": [],
        "options": 0,
        "figure_captions": [],
        "has_footer": False,
        "warnings": [],
    }

    for item in items:
        content = item["content"].strip()
        line_type = item.get("line_type", "text")

        if line_type == "question" or RE_QUESTION.match(content):
            m = RE_QUESTION.match(content)
            if m:
                report["questions"].append(int(m.group(1)))

        if line_type == "option" or RE_OPTION.match(content):
            report["options"] += 1

        if line_type == "figure_caption" or RE_FIGURE.search(content):
            report["figure_captions"].append(content[:20])

        if line_type == "footer" or RE_FOOTER.search(content):
            report["has_footer"] = True

    # 检查题号连续性
    if report["questions"]:
        qs = sorted(report["questions"])
        expected = list(range(qs[0], qs[-1] + 1))
        missing = [q for q in expected if q not in qs]
        if missing:
            report["warnings"].append(f"题号不连续, 缺失: {missing}")

    # 检查选项与题目比例 (选择题页应有较多选项)
    if report["questions"] and report["options"] == 0:
        report["warnings"].append("未检测到选项行, 请确认是否为选择题页或选项标记是否完整")

    # 检查页脚
    if not report["has_footer"] and page_num > 0:
        report["warnings"].append("未检测到页脚, 可能影响下边界夹紧")

    return report


def validate_ocr_dir(ocr_dir: str) -> list[dict]:
    """验证所有页的 OCR 质量。"""
    ocr_dir = Path(ocr_dir)
    reports = []
    for f in sorted(ocr_dir.glob("ocr_page_*.json")):
        page_num = int(re.search(r'ocr_page_(\d+)', f.name).group(1))
        data = json.load(open(f, encoding="utf-8"))
        items = data.get("ocr_result", [])
        report = validate_ocr_page(items, page_num)
        reports.append(report)
        status = "OK" if not report["warnings"] else "WARN"
        print(f"  page {page_num:2d}: {len(items):3d}行, "
              f"{len(report['questions'])}题, "
              f"{report['options']}选项, "
              f"{len(report['figure_captions'])}图标题, "
              f"页脚={'Y' if report['has_footer'] else 'N'} [{status}]")
        for w in report["warnings"]:
            print(f"    ⚠ {w}")
    return reports


# ============================================================================
# CLI
# ============================================================================

def main():
    ap = argparse.ArgumentParser(description="Agent 视觉 OCR 辅助工具")
    sub = ap.add_subparsers(dest="command", required=True)

    # prompt: 生成单页提示词
    p1 = sub.add_parser("prompt", help="生成单页 OCR 提示词")
    p1.add_argument("image", help="页面图片路径")
    p1.add_argument("--page", type=int, default=1, help="页码")
    p1.add_argument("--output", help="输出提示词文件 (默认输出到 stdout)")

    # batch-prompt: 批量生成提示词
    p2 = sub.add_parser("batch-prompt", help="批量生成所有页提示词")
    p2.add_argument("pages_dir", help="page_*.png 所在目录")
    p2.add_argument("output_dir", help="提示词输出目录")

    # parse: 解析 Agent 返回结果
    p3 = sub.add_parser("parse", help="解析 Agent 返回的 OCR 结果")
    p3.add_argument("input", help="Agent 返回的文本文件")
    p3.add_argument("output", help="输出 OCR JSON 路径")
    p3.add_argument("--page", type=int, default=1, help="页码")
    p3.add_argument("--calibrate", help="校准用的页面图片路径 (可选)")

    # calibrate: 校准已有 OCR 的坐标
    p4 = sub.add_parser("calibrate", help="校准 OCR 坐标")
    p4.add_argument("ocr_json", help="OCR JSON 文件")
    p4.add_argument("image", help="对应页面图片")

    # validate: 验证 OCR 质量
    p5 = sub.add_parser("validate", help="验证 OCR 质量")
    p5.add_argument("ocr_dir", help="ocr_page_*.json 所在目录")

    args = ap.parse_args()

    if args.command == "prompt":
        prompt = build_ocr_prompt(args.image, args.page)
        if args.output:
            Path(args.output).write_text(prompt, encoding="utf-8")
            print(f"提示词已保存: {args.output}")
        else:
            print(prompt)

    elif args.command == "batch-prompt":
        build_batch_prompts(args.pages_dir, args.output_dir)

    elif args.command == "parse":
        text = Path(args.input).read_text(encoding="utf-8")
        items = parse_agent_response(text)
        if args.calibrate:
            items = calibrate_coordinates(items, args.calibrate)
        save_ocr_json(items, args.output, args.page)

    elif args.command == "calibrate":
        data = json.load(open(args.ocr_json, encoding="utf-8"))
        items = data.get("ocr_result", [])
        items = calibrate_coordinates(items, args.image)
        data["ocr_result"] = items
        data["calibrated"] = True
        with open(args.ocr_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"坐标已校准: {args.ocr_json} ({len(items)} 行)")

    elif args.command == "validate":
        validate_ocr_dir(args.ocr_dir)


if __name__ == "__main__":
    main()
