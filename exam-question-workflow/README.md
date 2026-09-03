# 试卷 / 教材 OCR 切题 + 层级命名工作流（测试版）

> 基于 `exam-question-cutter` 底座迭代升级的隔离测试工作区。
> **生产版本**位于 `.user_skills/exam-question-cutter`（未改动），
> **本测试版**在 `D:\skillDiy\exam-question-workflow`（可自由迭代）。
> **运行环境**：本工作区自带独立 Python 虚拟环境 `.venv`（含 PaddleOCR），与系统环境隔离。

## 零、克隆本仓库后如何运行（必读）

> 本仓库**只包含工作流的代码与文档**。为控制体积、规避 GitHub 单文件 100MB 限制，
> 以下两项**未随仓库发布**，需自行准备：

| 缺失项 | 体积 | 说明 | 准备方式 |
| --- | --- | --- | --- |
| `.venv/`（Python 虚拟环境） | 约 4.4GB | 含 PaddleOCR / PyMuPDF / OpenCV 等依赖 | 用本仓库 `requirements.txt` 重建（见下方步骤） |
| `samples/`（样例 + 真实材料） | 约 448MB（含 128MB PDF） | 第三章快速开始里引用的示例 PDF | **自备任意试卷 / 教材 PDF**，把路径传给 `run_workflow.bat` 即可 |

### 从零运行步骤（Windows）

```bat
:: 1) 在 exam-question-workflow/ 目录下创建隔离虚拟环境
python -m venv .venv

:: 2) 安装依赖（requirements.txt 已锁定版本，见仓库根）
.venv\Scripts\python -m pip install -r requirements.txt

:: 3) （可选，GPU 加速）本机有 NVIDIA 显卡时，把 paddlepaddle 换成 GPU 版:
.venv\Scripts\python -m pip uninstall -y paddlepaddle
.venv\Scripts\python -m pip install paddlepaddle-gpu==3.3.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/

:: 4) 用自己的 PDF 跑（samples/ 不在仓库里，用你自己的文件路径）:
run_workflow.bat "你的试卷.pdf" --kind exam
run_workflow.bat "你的教材.pdf" --kind textbook --toc-page 5 --chapter 25 --subject 数学
```

> - `run_workflow.bat` 通过 `%~dp0.venv\Scripts\python.exe` 调用本目录虚拟环境，**与克隆位置无关**；`.venv` 未创建时会明确报错并提示安装命令。
> - CPU 与 GPU 产物完全一致，无 GPU 也能跑（仅速度差异，详见第六章实测）。
> - `samples/` 内的 `make_sample.py`（合成测试教材生成器）未随仓库发布；如想零素材自测，自备一张试卷 PDF 即可走通全流程。

## 一、目录结构

```
D:\skillDiy\exam-question-workflow\
├── .venv\                        # 独立 Python 环境(已装 PaddleOCR/pymupdf/opencv)
├── run_workflow.bat              # ★ 双击/命令行启动器(自动用 .venv 运行)
├── exam-question-cutter\         # 复制的切题底座(已做最小兼容修改: 见下方说明)
│   └── scripts\
│       ├── pdf_render.py         # ① PDF 渲染
│       ├── ocr.py / pixel_ocr.py / agent_ocr.py   # ② OCR(本地引擎/像素投影/Agent视觉)
│       ├── layout_analysis.py    # ④ 版面分析(已扩展教材层级标题+板块+题型判定)
│       ├── figure_detection.py   # ⑤ 图形边界检测
│       └── crop.py               # ⑥ 题目切分(已修复 Windows 中文路径乱码)
├── upgrades\                     # ★ 升级模块(本工作流新增)
│   ├── pdf_text_ocr.py           # ② 文字层OCR: 电子版教材直接提取文本+坐标+字号
│   ├── toc_parser.py             # ③ 教材目录解析 -> 层级树(书签/目录页文本/扫描版OCR兜底)
│   ├── hierarchy_tracker.py      # ⑦ 章节层级状态机: 每道题归属 章→节→小节→课时→板块
│   ├── naming.py                 # ⑧ 层级命名 + 按层级归档
│   └── run_workflow.py           # ★ 端到端编排器(统一入口, 已支持跳过目录页)
├── samples\                      # 样例 + 你的真实材料
│   ├── make_sample.py            # 合成测试教材生成器
│   ├── sample_textbook.pdf       # 合成教材(7页)
│   ├── 2026年4月广州市初三一模数学试卷.pdf   # 你的真实试卷
│   ├── 勤学早 同步课时导练 数学九年级上 RJ版 上册.pdf  # 你的真实教材(扫描版)
│   ├── exam_real_work\           # 真实试卷端到端结果
│   └── book_work_full\           # 真实教材端到端结果
└── _docs\                        # 参考资料(教材目录页示例图)
```

## 二、底座兼容性修改（均为必要修复，生产版零改动）

| 文件 | 修改 | 原因 |
|---|---|---|
| `layout_analysis.py` | `RE_SECTION` 增加教材层级标题（第X章 / 25.1 / 25.2.1 / 第N课时 / 知识点N / 板块）+ 打卡册/试卷标题（期末打卡 DAY / 第X部分 / 一、）；`RE_OPTION` 支持 "A.1个" 无空格选项；`RE_SOLVE` 含"解不等式"；**题型判定按老师标准重写**（见下表）；`--skip-pages` 跳过目录页；`cv2.imread` → `_imread_unicode`（中文路径安全）；**教材层级编号开头的长句不当作大题标题**；**子问像素横线检测起始 y 不侵入上一行文字**（`max(prev_bottom+4, sq.top-30)`，修汉字横画被误检为填空横线）；**跨页题合并时 page_img 垂直拼接下页图像**（修跨页填空题下页子问横线检测超出图像范围）；**`_is_text_stroke` 像素横线防误判**（横线上方0-3px紧邻笔画 / 左右6px内有笔画 → 排除汉字"一"/文字底横，修解答题被误判填空）；**表格页检测 `_is_table_page`**（左栏"类型一/二/三"+ 右栏"教材变式/母题"→ 整表作为一道解答题，跳过常规题号检测，修左栏子问编号被误识别为题号、右栏【教材变式N】漏检）；为每题补充 `content_bottom`，跨页题合并下页顶部内容一起判定题型 | 底座原只认试卷大题标题；教辅选项格式不同；目录页会误判为题号；PaddleOCR 全角点转半角点与教材层级标题冲突；子问检测区间侵入上一行文字把汉字横画误检为横线；跨页题下页子问横线检测超出单页图像；汉字"一"/文字底横满足横线几何特征被误检；表格页左栏"1.2.3."是类型子问不是题目，右栏"【教材变式N】"不匹配题号正则 |
| `crop.py` | `cv2.imwrite` → `cv2.imencode` + Python 原生字节写入；**上边界 clamp 到上一题下边界**（`prev_y2`）；切片坐标 int() 取整；`cv2.imread` → `_imread_unicode`；**左右边界取 (默认/auto-margin 边界) 与 (该页 OCR 文本范围) 的并集**；**跨页判定改用题目内容底 content_bottom 而非题号 y**；**下一题内容向上延伸检测**（大括号/分式分子比题号高时，上一题下边界夹紧到下一题内容顶部，修方程组分子被截断）；**分式检测 `_detect_fraction_range` + 边界扩展**（垂直堆叠的分子/分母 OCR 块对，含分式时上下边界扩展到分式实际范围，修分式分母被下一题题号裁掉）；**题号上方内容检测**（题号上方80px内有OCR内容时上边界扩展，修行列式首行/分式分子在题号上方被裁）；**整表题跳过跨页判定**（`is_table` 标记的题不触发跨页合并，避免表格底部距页底近被误判跨页） | OpenCV 在 Windows 写中文路径会乱码；原上边界残留上一题内容；文字层 OCR float 坐标切片崩溃；中文 workdir 读图失败；默认边界对宽版心过窄；跨页判定只看题号漏判；大括号/分式分子比题号高导致上一题混入下一题内容；分式分子/分母超出题号区间被裁；行列式首行在题号上方被裁；整表题 content_bottom 是预设表格底部距页底近被误判跨页 |
| `run_workflow.py` | 新增 `--ocr-backend paddle`（强制 PaddleOCR/GPU，即使有文字层也走 OCR，不自动走文字层） | 用户希望文字层 PDF 也走 GPU 加速的 PaddleOCR |
| `ocr.py` | PaddleOCR 3.x `predict()` 兼容 + `enable_mkldnn=False` + **引擎单例复用**（不再每页重建） | 规避 Paddle 3.x CPU 上 PP-OCRv6 的 oneDNN 算子问题；单例复用提速约 1.8 倍 |
| `figure_detection.py` | `cv2.imread` → `_imread_unicode` | 中文 workdir 读页面图失败 |

### 题型判别标准（按老师标准实现，最终版）

判定顺序（**执行级短路**：每步只计算该步所需特征，命中即返回，不再执行后续判断——选择题不做像素横线检测，填空题不做解答关键词二次判断。判定前剔除页码/页脚行、剔除引号内问号）：

1. **选择题**：有 `A./B./C./D.` 或 `(A)(B)(C)(D)` 选项行（题目一般以（）结尾）→ **命中即返回，跳过填空/解答判断**
2. **填空题**（**只看横线特征**，不涉及解答关键词/问号；**命中即返回，跳过解答判断**）：
   - 有 `(1)(2)` 子问时：**每个子问都必须有横线**才判填空，任一子问无横线则继续走解答判定（子问横线像素检测起始 y 向上扩展 30px，覆盖 OCR 块上方的横线，如"(1) [π]=____"横线比 OCR 块顶高 28px）
   - 无子问时：题后有 `____`/`______` 填空横线（OCR 横线 **或像素级横线检测**——`cv2` OTSU 二值化 + 水平闭运算，判据 ww≥40 且 hh≤12 且 area>ww*0.4，专治 PP-OCR 丢下划线）
   - **即使题干有"求/计算/证明/问号"等，只要有横线就判填空**（如"求∠EOF的度数____""计算：…=____"是填空题）
3. **解答题**（**无横线时才用解答特征判断**，满足任一）：
   - 有 `(1)(2)` 子问（但子问不全横线——全横线已在第2步判填空）
   - 命中关键词 `求|证明|求证|化简|解方程|解不等式|列方程解|列方程并|画出|写出(过程|理由|结论|步骤等)|是否存在|试说明|是多少|请算|计算`（"是否存在"做了 OCR 分词容错，如"是否分别存在"；**"写出"仅限解答语境**——"写出一个…方程/值"这类填空不算）
   - 无子问时题目以问号结尾（引号内古籍引文问句不计）
4. **无法确定** → 标记 `pending`，**交 Agent 视觉判断**（导出切图到 `output/pending/` + `pending_questions.json`）

- "知识点N"等区块标题作为题目范围边界（避免下一知识点标题影响问号/横线判断）
- 判定前剔除页码行（`·22·`/`22`/`-22-`），避免页内最后一题的页码污染问号判断
- **像素横线检测边界**：上边界仅扩展 -4px（防止把上一题的填空横线算进本题，如 p41题5 的"求a的值"曾因此误判）；下边界严格不越过 next_y（防止把下一题横线算进本题，如 p9题7 曾因此误判）
- **重跑产物清理**：`crop.py` 每次重跑自动清空 `output/questions` 旧切图、`naming.py` 每次重跑自动清空 `output_hier` 旧归档，避免题型重判后旧分类文件残留

### Agent 联动（题型不确定时）

三步判断（选择→填空→解答）仍无法确定的题，`run_workflow.py` 会：
1. 把未分类题切图导出到 `<workdir>/output/pending/`（按题目 y 坐标直接从页面图裁剪，不依赖 crop 命名）
2. 生成 `<workdir>/output/pending_questions.json`（含 page/num/text/png 路径清单）
3. 打印提示，要求 Agent 逐张看图判断题型，填写 `<workdir>/pending_types.json`
4. 重跑时加 `--pending-types <workdir>/pending_types.json`（配合 `--ocr-backend precomputed --precomputed-dir <workdir>/ocr` 复用已生成 OCR，秒级重跑）回填题型，继续 crop + 层级归档

升级模块 `toc_parser.py` / `hierarchy_tracker.py` 扩展了教辅板块识别（基础题夯实 / 中档题运用 / 综合题探究 / 方法技巧 / 回归教材 / 题型研究 / 思想方法 / 数学活动 / 综合与实践 / 一题多法 / 一题练透 / 图形研究 / 实践操作 / 易错警示 等，含 A/B/C 前缀），支持扫描版教材目录页 OCR 兜底，并对板块名做**归一化**（如 "基础夯实"→"基础题夯实"，避免 OCR 漏字导致同板块分两个目录）。

### 切图边界规则（完整性优先，已固化到 crop.py）

切图的核心原则：**宁可相邻题目在图形/分式区域重叠，也不能让任何一道题自身内容被截断**。

| 边界 | 规则 | 修复的问题 |
|------|------|-----------|
| **上边界** | ① 题号 − 28px；② 有图形且图形顶部更高 → 延伸到图形顶部 − 10px；③ 不侵入上一大题标题（标题底 + 8px）；④ 不低于上一题下边界 `prev_y2`；⑤ **题号上方 80px 内有 OCR 内容（行列式首行/分式分子）→ 扩展到内容顶部 − 8px** | 行列式/分式分子在题号上方被裁 |
| **下边界** | ① 本题 OCR 内容最大 y + 50px；② 有下一题 → 夹紧到下一题题号 − 2px；③ 不越过大题标题/页脚；④ **下一题内容向上延伸（大括号/分式分子比题号高）→ 夹紧到下一题内容顶部 − 2px**；⑤ **本题含分式且分母在下一题题号下方 → 下边界取 max，最多延伸到下一题题号 + 50px** | 方程组分子被截断混入上一题；分式分母被下一题题号裁掉 |
| **左右边界** | 取 (默认/auto-margin 边界) 与 (本页 OCR 文本实际范围) 的并集，各加 10-15px 留白 | 宽版心打卡册左右边缘字符被裁 |
| **跨页合并** | 末题内容底 > 页高 − 400px 且下页首题 y > 200px → 上页从题号到页底 + 下页从页顶到下一题题号前，垂直拼接 | 跨页题题干/选项被分到两页 |
| **最小高度** | 不足 180px 的题用白底填充到 180px | 单行题图片过窄 |

**分式检测**：`_detect_fraction_range` 识别垂直堆叠的分子/分母 OCR 块对（间距 −2~14px、x 重叠 >4px、单块宽 <150px），搜索范围严格限制在本题（分子 top_left_y < 下一题题号），避免把后面题目的分式算进来导致过度扩展。

**像素横线防误判**：`_is_text_stroke` 在 `_detect_blank_lines` 检测到横线候选后，排除两类假横线：① 横线上方 0~3px 紧邻区域有笔画（文字底横，如"王""里"）；② 横线左右 6px 内有笔画（汉字"一"在词语中）。填空横线与上方文字有 >3px 行间距、左右是空白，不会被误排除。

### 表格页处理（镶嵌多个题目的大表格）

**检测条件**：页面 OCR 同时存在「类型一/二/三」分类标签（左栏）和「教材变式/教材母题」（右栏）→ 判定为表格页。

**处理方式**：
1. 跳过常规题号检测（避免左栏"1. 2. 3."类型子问被误识别为题号）
2. 将 section 标题（如"回归教材 根的判别式的运用"）+ 整个表格作为**一道解答题**整体切割
3. 上边界 = section 标题 y（`top_y-28` 自然包含标题），下边界 = 表格内容底部 + 20px
4. 标记 `is_table=True`，跳过跨页判定（避免表格底部距页底近被误判跨页）

**适用页面**：回归教材、方法技巧、数学活动等板块中左栏类型分类+右栏具体题目的表格布局页（教材中识别出 12 页）。

## 三、快速开始

> 以下示例假设本地存在 `samples/` 目录。**本仓库未包含 `samples/`**，请将示例中的 `samples\xxx.pdf` 替换为你自己的 PDF 路径（或从第零章的"从零运行步骤"复制命令）。

```bat
:: 推荐: 用启动器(自动用 .venv 运行), 在当前目录执行:
run_workflow.bat "你的试卷.pdf" --kind exam

:: 扫描版教材(如勤学早): 自动 PaddleOCR, --toc-page 指定目录页(中位页码即可, 自动扩窗5页)
run_workflow.bat "samples\勤学早 同步课时导练 数学九年级上 RJ版 上册.pdf" --kind textbook --toc-page 5 --chapter 25 --subject 数学

:: 电子版教材(有文字层 → 自动用文字层OCR, 更快)
run_workflow.bat 教材.pdf --kind textbook --workdir ./work1

:: 平铺命名(不建层级目录)
run_workflow.bat 教材.pdf --kind textbook --flat
```

参数：
- `--kind textbook|exam`：教材（启用层级）/ 试卷（仅按题型）
- `--toc-page N`：教材目录页页码（1-based；指定后自动取 N±2 共 5 页窗口）
- `--chapter N` / `--subject 学科`：附加信息提示（提升层级准确率）
- `--workdir`：工作目录（默认 `<文件名>_work`）
- `--auto-margin`：自动检测页面左右边界（扫描书推荐）
- `--ocr-backend precomputed --precomputed-dir <workdir>/ocr`：复用已生成 OCR（秒级重跑，配合 `--pending-types` 使用）
- `--pending-types <workdir>/pending_types.json`：应用 Agent 判定的未分类题题型后继续归档

## 四、输出

```
<workdir>/pages/page_XX.png        渲染页
<workdir>/ocr/ocr_page_XX.json     OCR/文字层结果(含坐标+字号)
<workdir>/tree.json                教材层级树(章/节/小节/课时/板块)
<workdir>/markers.json             版面分析(题号/大题标题)
<workdir>/output/meta.json         切分结果
<workdir>/output_hier/             层级命名归档 + final_meta.json
```

命名规则（与目录页层级一一对应）：
```
第25章/第2节/第1小节/第1课时/基础题夯实/选择题_第01题.png   ← 教材完整路径
板块题(无小节/课时): 第25章/第1节/基础题夯实/选择题_第01题.png
试卷(无层级): 选择题/选择题_第01题.png
```

## 五、已验证

### 合成测试教材（7 页）
- 16 题全部识别，层级归属 16/16 精确，切图无截断，中文文件名无乱码。

### 真实教材（勤学早 同步课时导练 数学九年级上 RJ版，99 页，有文字层）
- 目录页 OCR 解析：识别出 6 章（25 一元二次方程 … 30 直线与圆）
- **全量 99 页端到端：391 题全部识别并归档，跨页合并 27 题**
- 题型分布（GPU 自动判定 + Agent 回填 18 道 pending）：选择题 77 / 填空题 184 / 解答题 130
- **表格页整表合并**：19 页"回归教材/方法技巧"表格页（左栏类型分类+子问步骤，右栏题目），每页合并为 1 道解答题，避免左栏"1.2.3."子问被误识别为题号、右栏题目漏检或只截半页
- 层级归属精确：章→节→小节→课时→板块 全链路正确，命名形如
  `第25章\第2节\第1小节\第1课时\中档题运用\填空题_第01题.png`
- **切图完整性验证**：分式（分子/分母）、行列式（首行在题号上方）、大括号方程组、跨页题、含图解答题、表格整表题均无截断；左右边缘字符完整
- 题型误判修复：p9_q08（列方程化一般形式，子问无横线）→ 解答题✓；p81_q14（跨页填空题三子问全横线）→ 填空题✓；汉字"一"/文字底横误检为填空横线 → 已排除；小节标题继承题型导致选择/填空被误判解答题 → 已修复（不含题型关键词的section返回"未分类"触发自动判定）

### 真实试卷（2026年4月广州市初三一模数学试卷，7 页）
- PaddleOCR 端到端：**25 小题全部识别**（与卷面"本试卷共25小题"一致）
- 题型分类正确：选择题10 / 填空题6 / 解答题9，25 张全归档
- 抽查切图：选择题第1题（题干+ABCD 完整）、压轴解答题第25题（题干+两问+图15+备用图完整）

### 真实打卡册（期末打卡.pdf，20 页，有文字层）
- **101 题全部识别**（跨页合并 7 题），题型分布：选择题 49 / 填空题 40 / 解答题 12
- 自动识别"期末打卡 DAY N"大题标题，切图按 `dayX_qNN` 复合主键命名（避免不同 DAY 同号覆盖）
- 文字层 PDF 默认走文字层 OCR（更快更准）；**加 `--ocr-backend paddle` 可强制走 PaddleOCR/GPU**
- **OCR 智能分流（auto）**：GPU 检测 → PaddleOCR/GPU → 无 GPU → 文字层提取 → 无文字层 → CPU PaddleOCR → 都没有 → Agent 视觉识别备选
- 切图完整性修复：day1_q05/q06（大括号方程组分子被截断）→ 下一题内容向上延伸检测✓；day9_q03（行列式首行在题号上方被裁）→ 题号上方内容检测✓；分式分子/分母被裁 → 分式检测+边界扩展✓

## 六、OCR 引擎（PaddleOCR）安装说明

安装在**当前工作区虚拟环境** `.venv` 中（与系统 Python 隔离）。
本机已装 **GPU 版**（paddlepaddle-gpu 3.3.1，cu118，支持 RTX 3050）：

- 因 Windows 长路径限制（modelscope 目录层级过深超过 260 字符），**不能装到系统 Python**，
  需装在短路径虚拟环境。仓库已提供 `requirements.txt`（版本已锁定），直接安装即可：
  ```
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
  ```
- **GPU 版安装**（已执行，约 2.4GB，含 CUDA 运行时）：
  ```
  D:\skillDiy\exam-question-workflow\.venv\Scripts\python -m pip uninstall -y paddlepaddle
  D:\skillDiy\exam-question-workflow\.venv\Scripts\python -m pip install paddlepaddle-gpu==3.3.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
  ```
  - 版本选择：驱动 546.30（CUDA 12.3）用 **cu118** 最稳（wheel 自带 CUDA 11.8 运行时，驱动 ≥450 即可）；
    若驱动 ≥560 可换 cu126 源
  - 验证：`python -c "import paddle; print(paddle.device.is_compiled_with_cuda(), paddle.device.cuda.device_count())"`
    → 应输出 `True 1`（GPU 生效）
- 已装：paddleocr 3.7.0（PP-OCRv6 模型，首次运行自动下载约 140MB 到 `C:\Users\<用户>\.paddlex\official_models\`）
- 注意：**不要**同时安装 `opencv-python`（会与 paddleocr 依赖的 `opencv-contrib-python` 冲突损坏 cv2），只用 `opencv-contrib-python`
- 若在别的电脑重装：按上面命令 `pip install -r requirements.txt` 重建 `.venv` 即可（直接复制 `.venv` 目录也行，但跨机不保证可用）

### GPU 提速实测（本机 RTX 3050）

| 任务 | CPU | GPU | 提速 |
|---|---|---|---|
| 真实试卷 7 页端到端 | ~5 分钟（含首载） | **17.5 秒** | ~17× |
| 教材 99 页端到端 | ~70 分钟 | **334 秒（5.6 分钟）** | ~13× |

GPU 与 CPU 产物完全一致（试卷 25 题、教材 440 题，题型/章节分布全同）。`run_workflow.bat` 已指向 `.venv`，装好 GPU 版后自动走 GPU，无需改参数。

## 七、下一步路线

1. 公式识别增强：PaddleOCR-VL（`paddleocr_vl`）版面输出校准，复杂公式页识别优化
2. 目录页码→PDF 页码映射：当前层级状态机从正文页标题识别（不依赖目录页码），
   如需精确到"书内页码"需加页脚 `·N·` 识别
3. 若升级通过，将 diff 回灌生产版 `exam-question-cutter`
4. 多学科适配：物理/化学公式与图形题进一步调参（当前数学已验证）

## 八、已知限制

- 目录页自动检测对异常版式需 `--toc-page` 显式指定（扫描书推荐传中位目录页）
- 三步规则判定（选择→填空→解答）无法确定的题会进入 `pending` 交 Agent 看图判断，不兜底猜测
- 双栏教材需调整 `QUESTION_X_MAX`（crop 参数）
