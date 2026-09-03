---
name: exam-question-cutter
description: "多类型中学试卷自动切题工具。将上传的试卷 PDF/图片按题号自动切割为单题图片，按选择题/填空题/解答题分类输出。支持标准统考试卷、打卡册、练习册等多种格式。触发场景：用户上传试卷并要求'切题''按题目分割''把每道题截出来''试卷拆分'，或需要将整卷拆分为单题用于组卷、错题本、在线题库等。支持像素投影+Agent视觉题型标注（推荐）、Agent视觉OCR、图形边界检测、自动页面边界检测、跨页题合并、完整性优先（允许相邻题目在图形区域重叠，保证每题自身内容不被截断）。"
---
# 中学试卷自动切题
将试卷 PDF 端到端切分为单题图片，按题型分类。
## 快速开始
```bash
# 推荐: 像素投影 OCR + Agent 视觉题型标注 (多类型试卷/打卡册)
python3 scripts/run_pipeline.py <试卷.pdf> --workdir ./exam_work --ocr-backend pixel --auto-margin
# → 生成题型模板后暂停, Agent 视觉识别每页题型并填写 question_types.json
# → 基于模板重新生成 OCR, 再继续后续流程

# 标准统考试卷 (自动检测 OCR 后端)
python3 scripts/run_pipeline.py <试卷.pdf> --workdir ./exam_work

# 非标准试卷/打卡册 (自动检测内容边界)
python3 scripts/run_pipeline.py <打卡册.pdf> --workdir ./exam_work --auto-margin
```
输出在 `./exam_work/output/questions/` 下，按 `选择题/`、`填空题/`、`解答题/` 分目录。
**文件命名规则**：
- 标准试卷（无 DAY 信息）：`q001.png` ~ `qNNN.png`（全局唯一 ID）
- 打卡册（含 DAY 信息）：`day1_q01.png`、`day2_q01.png`（DAY+题号复合主键，避免不同 DAY 同号覆盖）
## 工作流程（五模块）
所有脚本在 `scripts/` 下，可独立运行也可串联。
### 1. PDF 渲染 — `pdf_render.py`
将 PDF 每页渲染为高清 PNG（默认 200 DPI）。
```bash
python3 scripts/pdf_render.py input.pdf pages/ --dpi 200
```
### 2. OCR — 三种模式
#### 模式A: 像素投影 + Agent 视觉题型标注（推荐，`pixel_ocr.py`）
基于像素投影精确定位题号和文本段，配合 Agent 视觉识别的题型标注生成 OCR JSON。
**适用场景**：纯像素投影无法区分选择题选项行(A.)和解答题子问行((1))，需要 Agent 视觉辅助标注题型。
```bash
# 步骤1: 像素投影检测题号 + 生成题型标注模板
python3 scripts/pixel_ocr.py detect pages/ ocr/ --template question_types.json
# 步骤2: (Agent 视觉) 逐页读取 pages/page_XX.png, 判断题型, 填写模板
#        题型判断规则:
#        - 选择题: 题目以"（ ）"结尾, 后方有 A/B/C/D 四个选项
#        - 填空题: 有"______"填空横线 (子问中也有横线)
#        - 解答题: 有(1)(2)子问, 且含"求/求证/试说明/问"等关键字
# 步骤3: 基于题型标注生成最终 OCR JSON
python3 scripts/pixel_ocr.py generate pages/ ocr/ --types question_types.json --day-map day_map.json
# 一步完成 (使用像素特征兜底分类, 准确率较低, 不推荐)
python3 scripts/pixel_ocr.py auto pages/ ocr/
```
输出格式：`{"ocr_result": [{"content", "type", "question_type"(可选), "top_left_x", "top_left_y", "bottom_right_x", "bottom_right_y"}]}`
#### 模式B: Agent 视觉 OCR（`agent_ocr.py`）
Agent 用视觉能力读取页面图片，输出结构化 OCR JSON，无需安装 OCR 后端。
```bash
# 生成提示词
python3 scripts/agent_ocr.py batch-prompt pages/ prompts/
# 解析 Agent 返回的 JSON (可选像素投影校准 y 坐标)
python3 scripts/agent_ocr.py parse agent_page1.txt ocr/ocr_page_01.json --page 1 --calibrate pages/page_01.png
# 验证 OCR 质量
python3 scripts/agent_ocr.py validate ocr/
```
#### 模式C: 本地 OCR 引擎（`ocr.py`）
自动检测 paddleocr / easyocr / tesseract，也支持预计算结果。
```bash
python3 scripts/ocr.py pages/ ocr/
python3 scripts/ocr.py pages/ ocr/ --backend precomputed --precomputed-dir ./existing_ocr
```
### 3. 版面分析 — `layout_analysis.py`
识别大题标题、题号、页脚，跨页追踪题型分类。优先使用 OCR 中标注的 `question_type` 字段。
```bash
python3 scripts/layout_analysis.py ocr/ markers.json
```
- 大题标题正则：`第X部分` / `一、` `二、` / `期末打卡 DAY N`
- 题号正则：`数字.` 且 x < 350（排除右侧图形标签）
- 排除选项 `(A)`、子题 `(1)`、圈号 `①` 等误匹配
- **题型优先级**：OCR `question_type` 字段 > 大题标题继承 > 内容特征兜底
### 4. 图形检测 — `figure_detection.py`
通过"图N"标题定位图形，用形态学闭运算（垂直核 25px）连接图形内分散点线，再找离标题最近的连通域顶部作为真实边界。
```bash
python3 scripts/figure_detection.py pages/ ocr/ figures.json
```
### 5. 切分 — `crop.py`
根据版面分析和图形检测结果切割每题，生成单题图片 + 整页预览 + meta.json。
```bash
python3 scripts/crop.py pages/ ocr/ markers.json figures.json output/
python3 scripts/crop.py pages/ ocr/ markers.json figures.json output/ --auto-margin
```
`--auto-margin`：自动检测每页内容左右边界（基于像素投影），适配页面边距非标准的打卡册/练习册。
**跨页题合并**：自动检测跨页题（末题接近页底且下页首题 y>200），将上页从题号到页底与下页从页顶到下一题题号前垂直拼接，保证题目完整。
## 核心边界规则（完整性优先）
这是切分质量的关键，修改时需谨慎：
| 边界 | 规则 |
|------|------|
| **上边界** | 题号行 − 28px；若本题图形顶部高于题号行，向上延伸到图形顶部 − 10px |
| **上边界约束** | 不进入前一个大题标题区域（标题底部 + 8px） |
| **下边界** | 本题范围内所有 OCR 内容最大 y + 14px（**不被下一题图形收紧**） |
| **下边界约束** | 不超过下一题题号 − 2px、页脚 − 4px |
| **重叠策略** | 相邻题目在图形区域允许重叠，优先保证每题自身内容完整 |
| **跨页合并** | 末题 y > 页高−400 且下页首题 y > 200 → 跨页，垂直拼接两页内容 |
## 依赖
- Python 3.10+
- PyMuPDF (`pip install pymupdf`) — PDF 渲染
- OpenCV + NumPy (`pip install opencv-python numpy`) — 像素投影、图形检测和切分
- OCR 后端三选一：paddleocr / easyocr / pytesseract（或使用 Agent 视觉模式，无需安装）
## 多试卷类型适配
| 试卷类型 | 大题标题格式 | 选项格式 | 题号规则 | 适配方式 |
|----------|-------------|----------|----------|----------|
| 标准统考 | 一、选择题 / 第二部分 | （A）（B） | 1-25 连续 | 默认支持 |
| 打卡册 | 期末打卡 DAY N | A. B. | 每个 DAY 重新编号 | `--ocr-backend pixel --auto-margin` + DAY复合主键 |
| 练习册 | 无大题标题 | A. B. | 按页编号 | `--ocr-backend pixel` + Agent题型标注 |
| 双栏试卷 | 同标准 | 同标准 | 双栏排列 | 需调整 `QUESTION_X_MAX` |
## 调参参考
| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| PADDING | crop.py | 28 | 题号上方留白，试卷字号大时可增大 |
| PAGE_LEFT / PAGE_RIGHT | crop.py | 150 / 1510 | 内容区左右边界，`--auto-margin` 时自动检测覆盖 |
| AUTO_MARGIN_PAD | crop.py | 12 | 自动边界检测的额外留白 |
| CONTENT_MARGIN | crop.py | 14 | 内容底部留白 |
| CROSS_PAGE_THRESHOLD | crop.py | 400 | 跨页检测: 末题距页底小于此值怀疑跨页 |
| CROSS_NEXT_PAGE_TOP | crop.py | 200 | 跨页检测: 下页首题y大于此值说明页首有延续 |
| QUESTION_X_MAX | layout_analysis.py | 350 | 题号行 x 上限，双栏试卷需调整 |
| QUESTION_LEFT_MAX | pixel_ocr.py | 130 | 像素投影题号检测: 左侧内容最大x |
| QUESTION_H_MIN/MAX | pixel_ocr.py | 15 / 120 | 像素投影题号检测: 题号行高度范围 |
| MORPH_KERNEL_H | figure_detection.py | 25 | 图形闭运算核高，图形元素分散时增大 |
