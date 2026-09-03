---
name: english-textbook-vocab-extractor
description: 英语教材 PDF 词汇表提取、清洗与例句生成工具。接收用户上传的英语教材 PDF 文件，自动定位并识别附录中的词汇表内容（如"Words and Expressions in Each Unit"），将提取出的单词、短语、词性、中文释义等结构化整理为 Excel 格式的词汇表文件，并可一键执行数据清洗（列结构调整、单元规范化、词性标准化映射）和例句自动生成（优先从教材正文提取原句，未匹配可用LLM兜底），输出最终可用的词汇表。当用户提到"提取英语教材词汇表""英语课本单词表转 Excel""从 PDF 提取单词""词汇表清洗""生成单词例句"等需求时触发此技能。
agent_created: true
version: 2.3.1
changelog: |
  v2.3.1 修复教材提取例句质量问题：(1) 增加例句后处理（修复PDF拆分单词如 diff erent→different、首字母大写）；(2) 增加例句质量评估（排除练习题指令、不完整句子、单词列表行），只返回高质量例句；(3) 新增 --llm-only 参数，支持全量使用LLM生成例句（跳过教材正文提取，保证例句质量统一）。经评估，教材PDF文本提取质量限制导致原句存在拆分单词、练习题混入、句子混乱等问题，建议优先使用 --llm-only 全量LLM生成。
  v2.3 新增例句自动生成功能：新增 generate_examples.py 脚本，优先从教材正文页提取包含目标单词的原句作为例句，支持词形变化匹配（动词时态/名词复数/形容词比较级）、PDF拆分单词匹配（如 diff erent→different）、短语核心词组合匹配；未匹配的单词可用 LLM API 生成兜底。clean_vocab.py 新增 --examples 参数，extract_vocab.py 新增 --examples 开关，一条命令完成提取→清洗→例句生成。经人教版九年级全一册验证，656条词汇正文例句覆盖率达96%，配合LLM兜底可达100%。
  v2.2.3 修复音标+词性粘连导致词性丢失的 bug：当音标与词性粘连在同一 token（如九年级 /helpfl/adj.、/krIsm@s/n.，七年级 PUA /hir/v.）时，is_ascii_phonetic/has_pua 将 token 识别为音标，但词性部分未被提取，导致这些单词词性被错误标为「其它」。修复：在 PUA 和 ASCII 两个音标分支中，移除 /音标/ 部分后检查剩余 token 是否为词性缩写，若是则设置 cur_pos。经人教版七/九年级验证，10个粘连词条全部正确分类（helpful→ADJ、Christmas→NOUN、pioneer→NOUN、burning→ADJ、alive→ADJ、airport→NOUN、responsible→ADJ、wear→VERB等），九年级 other 从203降至195，NOUN+4、ADJ+4。
  v2.2.2 修复 extract_vocab.py 两个提取 bug：(1) 短语占位符 …（U+2026 水平省略号）被 is_cjk_char 误判为中文字符，导致 connect … with 等短语被截断、后续英文词被跳过；修复：is_cjk_char 排除 U+2026。(2) 九年级 ASCII 音标 token 中全角右括号 ）（如 /li:vz/）叶）被同时处理为词形括号闭合和释义中文，导致释义以 ）开头；修复：ASCII 音标分支 cjk 提取排除全角右括号。注意 PUA 音标分支不排除全角括号（其中全角括号是释义括号的一部分，如 pron.（常用于否定）。经人教版七/九年级验证，两本教材相邻行重复=0、释义以括号开头=0、释义括号不平衡=0。
  v2.2.1 修复 clean_vocab.py 词性验证 bug：原合法词性集合 VALID_POS 只穷举了单项和两项组合，遇到三项及以上词性组合（如 adj. & adv. & n. → ADJ,ADV,NOUN，出现在人教版九年级 east 等词条）时自检误报"词性非法"。改为动态验证函数 is_valid_pos()，支持任意数量的逗号组合。经人教版九年级全一册验证，656条词汇清洗自检全部通过。
  v2.2 集成数据清洗能力：新增 clean_vocab.py 独立清洗脚本，实现列结构调整（单词|所属单元|词性|中文释义|例句）、单元纯数字规范化、词性标准化映射（n./v./adj./adv.→NOUN/VERB/ADJ/ADV，含&拆分用,连接，其余→other）、新增例句列、单sheet输出、质量自检与日志。extract_vocab.py 新增 --clean 参数，提取后自动串联清洗。保持v2.1通用化与v2.0 bug修复。
  v2.1 通用化改造：移除所有硬编码的本地路径（Windows managed venv路径、本地用户目录等），改为跨平台通用写法。新增"变量约定"section（{SKILL_ROOT}/PYTHON/PDF_PATH），提供Windows/macOS/Linux三平台依赖安装说明，修正脚本docstring中--cut默认值描述。保持v2.0的所有bug修复。
  v2.0 修复释义括号丢失问题：(1) 词性+全角左括号粘连时释义括号左括号丢失；(2) 英文+全角左括号粘连时释义括号左括号丢失；(3) 词形变化括号跨行闭合时全角右括号误入释义且新义项缺分号。经人教版七年级下册验证，478条词汇释义括号匹配率从97.7%提升至100%。
---

# English Textbook Vocab Extractor

## Overview

从英语教材 PDF 电子课本中自动定位并提取附录词汇表，输出为结构化 Excel 词汇表文件，并可一键执行数据清洗和例句自动生成，输出最终可用格式。核心能力包括：PDF 双栏版式解析、PUA 私有区音标字体处理、ASCII 音标识别（九年级教材）、词性识别与规范化、中文释义提取、含特殊符号单词/短语的完整识别（如 `o'clock`、`help (sb) with sth`、`tooth (pl. teeth)`、`fly (flew)` 等）、按单元（Unit）分组、跨行词形变化合并（如 `steal (stole, stolen)`）、**数据清洗（列结构调整、单元规范化、词性标准化映射）**、**例句自动生成（优先从教材正文提取原句，支持词形变化/拆分单词/短语匹配，未匹配可用LLM兜底）**。

## When to Use

- 用户上传英语教材 PDF，要求提取其中的词汇表/单词表
- 用户要求将教材附录的单词表转为 Excel
- 用户提到"从英语课本 PDF 提取词汇""词汇表转 Excel""单词表整理"等
- 用户需要按单元（Unit）分组的结构化词汇数据

## 重要：定位"按单元词汇表"而非"词汇索引表"

教材 PDF 可能同时包含两类词汇章节，**必须提取按单元分组的 "Words and Expressions in Each Unit"**（如人教版九年级 p170-184），**不要提取 A-Z 字母序的 "Vocabulary Index"**（如 p185-197）。

### 词汇表页的三个判断条件

自动扫描（`--scan-only`）综合以下三个信号定位词汇表页：

1. **位置条件**：词汇表一般位于教材**倒数前 50 页**内（附录/词表区）。
2. **结构条件**：词汇表内容按单元（Unit）分组，页面含 `Unit N` 标题行。
3. **标题条件**：章节通常以 `Words and Expressions in Each Unit`（或 `Word List` / `Vocabulary` / `词汇表` 等）标题开篇。

### 评分算法

对每页按三条件加权打分，然后聚类取分最高的连续段：

- **标题**（必需）：优先标题（`Words and Expressions in Each Unit` / `Vocabulary in Each Unit`）+6；通用标题（`Word List` / `Vocabulary` / `词汇表` 等）+3。**无标题页不得独立入选**（正文页眉 `UNIT N` 会干扰），只能作为标题段两侧的紧邻扩展。
- **位置**：位于教材倒数前 50 页内 +2。
- **结构**：含 `Unit N` 分组标题 +1。
- **排除**：命中 `Vocabulary Index` / `Index` 索引表 → -1000，直接剔除。

段落选择：标题页聚成连续主干段，每段向两侧扩展吸收含 `Unit N` 的紧邻无标题页（每侧最多 8 页），段得分 = 标题页得分和 + 扩展页×0.5，取最高分段。

这样可同时排除：① 目录页对词汇表的引用（孤立、不在末尾区）；② Vocabulary Index 索引表；③ 正文页眉 `UNIT N` 的干扰。

## Quick Start

### 环境要求
- Python 3.8+
- 依赖包：`pdfplumber`（PDF 解析）、`openpyxl`（Excel 生成）

### 变量约定
本文档使用以下变量，使用时替换为实际值：
- `{SKILL_ROOT}`：本 Skill 所在目录的绝对路径（即包含 `SKILL.md` 的目录）
- `PYTHON`：Python 解释器命令，通常为 `python`（Windows）或 `python3`（macOS/Linux）
- `PDF_PATH`：用户上传的英语教材 PDF 的绝对路径

### 依赖安装
```bash
# 方式一：直接安装到当前 Python 环境（最简单）
pip install pdfplumber openpyxl

# 方式二：使用虚拟环境（推荐，避免依赖冲突）
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
pip install pdfplumber openpyxl
```

> **提示**：如果 `pip` 命令不可用，尝试 `python -m pip install pdfplumber openpyxl`。

### 工作流程

#### 步骤 1：扫描定位词汇表页码

如果用户未指定词汇表所在页码，先用 `--scan-only` 自动扫描：

```bash
SCRIPT="{SKILL_ROOT}/scripts/extract_vocab.py"
"$PYTHON" "$SCRIPT" "$PDF_PATH" --scan-only
```

输出格式为 `START-END`（1-based 闭区间）。如果自动扫描未命中，需人工查看 PDF 目录或翻阅定位词汇表章节，再用 `--pages` 指定。

#### 步骤 2：执行提取（可选自动清洗）
```bash
# 基础提取（仅输出原始提取格式）
"$PYTHON" "$SCRIPT" "$PDF_PATH" \
  --pages 106-114 \
  --output "词汇表.xlsx" \
  --json "vocab.json"   # 可选，输出中间 JSON 便于校验

# 提取 + 自动清洗（推荐，同时输出原始和清洗后两个文件）
"$PYTHON" "$SCRIPT" "$PDF_PATH" \
  --pages 106-114 \
  --output "词汇表.xlsx" \
  --clean               # 提取后自动清洗，生成 词汇表_清洗后.xlsx
```

关键参数：
- `--pages START-END`：词汇表页码范围（1-based 闭区间）
- `--cut X`：双栏切分 x 坐标（默认 **auto，按页动态检测**；部分教材奇数/偶数页右栏起始 x0 不同，固定 cut 会导致右栏词头被误分到左栏）
- `--top-skip Y`：页眉跳过高度（默认 52.0）
- `--output PATH`：输出 Excel 路径
- `--unit-header TEXT`：单元标题关键词（默认 `Unit`）
- `--json PATH`：同时输出中间 JSON
- `--clean`：提取完成后自动执行数据清洗，在输出目录生成 `<原文件名>_清洗后.xlsx`（清洗规则见下方「数据清洗」section）
- `--examples`：清洗后自动为每个单词生成例句（需配合 `--clean` 使用），例句优先从本教材正文页提取，未匹配的单词留空（可配置 `--llm-api-key` 用 LLM 生成兜底）
- `--llm-api-key KEY`：LLM API key（OpenAI 兼容接口），用于未匹配单词的例句生成兜底
- `--llm-base-url URL`：LLM API 基础地址（默认 `https://api.openai.com/v1`）
- `--llm-model MODEL`：LLM 模型名（默认 `gpt-4o-mini`）

#### 步骤 3：质量校验

脚本运行时自动输出质检结果，关注以下指标：
- `英文异常` 应为 0（英文词头不应为空或含中文字符）
- `释义含PUA` 应为 0（中文释义不应残留音标乱码）
- `括号不平衡` 应为 0（如 `fly (flew` 缺右括号）

如发现异常，阅读脚本 stderr 输出的 `BAD-ENG` / `PUA` / `括号不平衡` 条目，针对性排查。常见问题参见下方 Troubleshooting。

#### 步骤 4：交付 Excel
用 `present_files` 工具将生成的 `.xlsx` 文件交付给用户。
- 若使用了 `--clean`，优先交付 `*_清洗后.xlsx`（最终可用格式），原始提取文件可作为中间产物保留。
- 若使用了 `--examples`，清洗后的 Excel 中「例句」列已填充从教材正文提取的原句；未匹配的单词例句留空，可告知用户覆盖率并建议手动补充或配置 LLM API key。

## Output Format

Excel 包含两个 Sheet：

**Sheet 1「词汇表」**

| 列 | 内容 | 说明 |
|----|------|------|
| 单元 | `Unit N` | 单元编号 |
| 英文单词/短语 | `guitar` / `help (sb) with sth` / `o'clock` | 含特殊符号的单词/短语完整保留 |
| 词性 | `n.` / `v. & n.` / `其它` | 仅 n./v./adj./adv. 原样保留并用 `&` 连接，其余统一「其它」 |
| 中文释义 | `吉他` / `在某方面帮助某人` | 纯中文，多义项用中文分号 `；` 连接 |

**Sheet 2「单元统计」**

| 列 | 内容 |
|----|------|
| 单元 | `Unit 1` ... |
| 单词/短语数量 | 该单元条目数 |
| 末行 | 合计 |

### 清洗后格式（使用 `--clean` 时额外输出）

使用 `--clean` 参数时，在原始提取文件之外额外生成 `<原文件名>_清洗后.xlsx`，仅含一个 Sheet「词汇表」：

| 列 | 内容 | 说明 |
|----|------|------|
| 单词 | `guitar` / `help (sb) with sth` | 原「英文单词/短语」列，移至首列 |
| 所属单元 | `1` / `12` | 纯数字，去除所有非数字字符 |
| 词性 | `NOUN` / `VERB,NOUN` / `other` | 标准化映射（详见「数据清洗」section） |
| 中文释义 | `吉他` / `在某方面帮助某人` | 保持不变 |
| 例句 | （空） | 新增列，全部留空待填充 |

## Technical Details

### 提取算法要点

1. **双栏切分（按页动态）**：教材词汇表通常为双栏排版，按 `x0 < cut` 切左右栏分别处理。`cut` 默认**按页自动检测**（`detect_page_cut`）：收集词头候选（英文开头、非词性、非JUNK、非音标、非页码）的 x0，左右两簇间的最大间隙即分界；再取 `(左栏所有token最大x0 + 右栏词头最小x0)/2`。部分教材（如人教版九年级）奇数页/偶数页的右栏起始 x0 不同（289 vs 266.5），固定 `page.width/2` 会把右栏词头误分到左栏。
2. **行聚类**：用相邻 `top` 坐标差 ≤ 6px 聚类还原阅读顺序，避免同词条的词头与释义因基线偏差被错分到不同行。
3. **词头判定**：行最左 token + 在栏左边距窗口内 + 纯英文开头 + 非 JUNK/页码/词性缩写。额外排除：右括号结尾（跨行词形续词如 `burned)`）、含 `/` 音标。
4. **PUA 音标处理**：部分教材（如七年级）用私有区（PUA）字体编码音标。脚本通过 `decode_pua`（codepoint − 0xF000）还原其中粘连的拉丁字母，用于提取括号内的过去式/复数词（如 `(fed)`/`(grew)`），并丢弃纯音标符号。
5. **ASCII 音标处理**：部分教材（如九年级）用自定义 ASCII 字体编码音标（如 `/sti:l/`、`/st@Ul/`、`/b3:(r)n/`）。`is_ascii_phonetic` 通过音标特征字符（`:@{}` 或大写 `IUVQNSDTZ3`）识别，支持跨行拆分的音标片段（如 `kA:nv@rseISn/`）。音标内可选音 `(r)` 会被丢弃（区别于词形变化括号如 `(stole)`）。
6. **特殊符号保留**：
   - 弯撇号 `’`（U+2019）归一化为直撇 `'`（如 `o'clock`）
   - 括号用法说明保留（如 `help (sb) with sth`、`tooth (pl. teeth)`）
   - 短语占位符 `...` 保留（如 `either ... or ...`）
7. **词性规范化**：词性识别支持中英文标点粘连（如 `adv（.` → `adv.`），仅 `n./v./adj./adv.` 原样保留，`modal v.`/`prep.`/无词性短语等统一标「其它」。
8. **释义提取**：按词性切分义项，用中文分号 `；` 连接；`is_cjk_char` 丢弃 ASCII 与 PUA，保证释义纯中文。
9. **Unit 标题预扫描**：整页范围内扫描 "Unit N"（跨栏，不依赖栏内相邻），记录 `(top, unit_num)`；主循环**仅在当前 token 是 "Unit" 标题本身时精确触发切换**（不用 top 容差归属）。解决两个问题：① "Unit" 与数字被切分线割裂到不同栏；② 新单元标题与上一单元最后一行同行高（如左栏 o'clock 释义与右栏 Unit 3 标题同 top），容差会误切导致上一单元释义丢失。
10. **跨行续词保护**：
    - 当前条目含未闭合括号（如 `steal (stole, ...`）→ 行首英文 token 是括号内续词，不作为新词头；
    - 同一行后续 token 含中文 且 当前条目尚无中文释义 → 释义续行（如 `Teresa` 下行的 `Lopez ... 特蕾莎`、`J. K. Rowling` 释义行的 `J. K. 罗琳（`），不作为新词头。
11. **全角/半角括号混用处理**：
    - 词性+全角左括号粘连（`v（.`、`v.（`、`n.（`、`adv（.`）：**peek 下一 token**——英文/音标 → 词形变化开括号（如 `deal v.（dealt)`），拆出 `(`；中文 → 释义括号（如 `Scrooge n.（非正式）吝啬鬼`、`kung fu n.（中国）功夫`），**将 `（` 加入释义**（v2 修复：原代码丢弃了释义括号的左括号，导致释义如 `中国）功夫` 缺左括号）。
    - 英文+全角左括号粘连（`of（`、`look up（`、`rather（`）：英文续词，**`（` 加入释义**（v2 修复：原代码丢弃了 `（`，导致 `kind of（非正式）` → 释义 `非正式）稍微；有点儿` 缺左括号）。
    - 音标 token 末尾的 `)`/`）`（如 `/li:vz/）`、`/st@Ul@n/)偷`）：闭合词形括号；音标内部 `(r)` 不闭合。
    - 英文+全角右括号+中文混合（`USA）美国；`）：paren_depth>0 时 `)` 进英文闭合、paren_depth==0 时 `）` 进释义（如 `rather）`）。
    - **词形变化括号跨行闭合**（如 `glass` → 上行 `（pl.`、下行 `glasses眼镜）`）：paren_depth>0 闭合词形括号时，rest 中的全角右括号 `）` 是词形括号闭合，**不进入释义**；后续中文（如 `眼镜`）是新义项，**已有释义时加分号 `；` 分隔**（v2 修复：原代码将 `眼镜）` 整体加入释义，导致 `玻璃；玻璃杯眼镜）` 缺分号且多右括号）。
    - 括号内缩写标记（`(pl.)`、`(sing.)`、`(abbr. ...)`）：保留为英文，不作词性处理。
    - 空括号清理：`by ()` → `by`（半角括号内是中文注释时）。
    - 人名缩写重复去重：`J. K. Rowling J. K.` → `J. K. Rowling`。
12. **页脚广告过滤**：**"关注" 可能是正常释义**（如 `注意；关注`），过滤正则应匹配组合关键词（`微信公众号`），不能匹配单个 `关注`，否则会误删正常释义（如 attention 条目释义变空）。

### 关键函数说明

- `scan_for_vocab_pages()`：按三条件（位置=末尾50页、结构=Unit分组、标题=Words and Expressions 等）综合评分定位词汇表页，排除 Vocabulary Index 索引表，取分最高的连续段。
- `_score_vocab_page()`：单页三条件加权评分（标题必需、位置+2、结构+1、索引排除）。
- `detect_page_cut()`：按页动态检测双栏切分线（词头 x0 两簇分界）。
- `is_ascii_phonetic()`：检测 ASCII 音标 token（含跨行拆分片段）。
- `parse_entry()`：核心解析函数，处理一个词头到下一个词头之间的所有 token，输出 `(english, pos, meaning)`。
- `is_cjk_char()`：判断字符是否为中文（排除 ASCII、PUA、弯引号），用于区分词头与释义。


## 数据清洗

使用 `--clean` 参数或独立运行 `clean_vocab.py` 时执行以下清洗规则：

### 列结构调整
1. 将「单元」列与「英文单词/短语」列互换位置，新列顺序为：**单词 | 所属单元 | 词性 | 中文释义 | 例句**。
2. 列改名：「英文单词/短语」→「单词」，「单元」→「所属单元」。
3. 输出文件仅保留一个 Sheet，确保为打开时的默认激活 Sheet。

### 所属单元规范化
去除所有非数字字符，仅保留阿拉伯数字。示例：`Unit 1` → `1`；`Unit 12` → `12`；`Unit 3A` → `3`。

### 词性标准化映射
1. 若词性含 `&`（如 `n. & v.`），先按 `&` 拆分为多个单项，逐个映射后用英文逗号 `,` 连接（去重、保持原顺序）。
2. 单项映射表：`n.` → `NOUN`，`v.` → `VERB`，`adj.` → `ADJ`，`adv.` → `ADV`。
3. 其他所有未列出的值（空值、未知缩写、中文「其它」、短语类条目等）统一替换为 `other`。

示例：`n.` → `NOUN`；`v. & n.` → `VERB,NOUN`；`adj. & adv.` → `ADJ,ADV`；`prep.` → `other`。

### 新增例句列
在最右侧新增「例句」列，所有单元格初始留空，不做任何自动生成。

### 质量自检
清洗完成后自动执行自检并输出日志：
- 行数与源数据一致
- 所属单元全为纯数字
- 词性值全部合法（仅含 NOUN/VERB/ADJ/ADV/other 及其逗号组合）
- 无残留 `&`
- 输出词性分布统计与归为 `other` 的明细

### 独立调用 clean_vocab.py
```bash
# 从提取后的 Excel 清洗
"$PYTHON" "{SKILL_ROOT}/scripts/clean_vocab.py" "词汇表.xlsx" --output "词汇表_清洗后.xlsx"

# 从 JSON 清洗（extract_vocab.py --json 的输出）
"$PYTHON" "{SKILL_ROOT}/scripts/clean_vocab.py" "vocab.json" --output "词汇表_清洗后.xlsx"

# 清洗并自动生成例句（从教材正文提取）
"$PYTHON" "{SKILL_ROOT}/scripts/clean_vocab.py" "词汇表.xlsx" \
  --output "词汇表_清洗后.xlsx" \
  --examples "{PDF_PATH}" \
  --vocab-pages 170-184
```

## 例句生成

### 功能概述

为词汇表中每个单词/短语自动生成一条英文例句，填入「例句」列。例句**优先从教材正文页提取原句**（与教材难度匹配、学生已学过），未匹配的单词可用 LLM API 生成兜底。

经人教版九年级全一册验证，656 条词汇正文例句覆盖率达 **96%**，配合 LLM 兜底可达 **100%**。

### 例句提取原理

1. **正文页识别**：自动排除封面、版权、目录、词汇表页（含音标特征的页面），仅保留正文页。
2. **句子分割**：从正文文本中按 `.?!` 分割完整句子，过滤页眉页脚、练习题指令、单词列表行等非正文内容。
3. **单词匹配**：为每个词汇表单词在正文句子中查找包含该词的句子，取第一条匹配的句子作为例句。

### 匹配策略

为提高覆盖率，支持以下三种匹配方式：

1. **词形变化匹配**：自动生成单词的所有可能形式，包括：
   - 动词：第三人称单数、过去式、过去分词、现在分词（规则变化 + 内置 200+ 不规则动词表）
   - 名词：复数形式（规则变化 + 不规则名词如 child→children、leaf→leaves）
   - 形容词/副词：比较级、最高级
   - 例如正文出现 `helped` / `helps` / `helping` 都算 `help` 的例句

2. **PDF 拆分单词匹配**：教材 PDF 中部分单词因字间距被拆分为两部分（如 `diff erent`、`fi nd`、`Th ey`），自动为每个单词生成可能的拆分形式并匹配。

3. **短语核心词组合匹配**：对于短语条目（如 `play chess`、`pay attention to`、`connect ... with`），提取核心实词，匹配句子中同时出现所有核心词（或其变形）的句子。

### LLM 兜底与全量生成

对于正文未匹配到的单词（通常是专有名词、含所有格的短语、正文未出现的词），可配置 LLM API 生成兜底例句：

- 支持 OpenAI 兼容接口（`--llm-base-url` 可自定义）
- 批量生成（每批 20 个），降低 API 调用次数
- 生成的例句控制在初中水平、8-20 个单词、必须包含目标单词

**全量 LLM 生成（推荐）**：由于教材 PDF 文本提取质量限制，从正文提取的原句可能存在拆分单词（如 `diff erent`）、练习题指令混入、句子混乱等问题。建议使用 `--llm-only` 参数全量使用 LLM 生成例句，保证质量统一、格式规范：

```bash
python generate_examples.py 词汇表.xlsx --llm-only --llm-api-key "sk-xxx" --output 词汇表_带例句.xlsx
```

### 使用方法

**方式一：提取 + 清洗 + 例句 一条命令完成（推荐）**
```bash
"$PYTHON" "{SKILL_ROOT}/scripts/extract_vocab.py" "{PDF_PATH}" \
  --output "词汇表.xlsx" \
  --clean \
  --examples
# 输出：词汇表_清洗后.xlsx（含例句列）
```

**方式二：清洗时生成例句**
```bash
"$PYTHON" "{SKILL_ROOT}/scripts/clean_vocab.py" "词汇表.xlsx" \
  --output "词汇表_清洗后.xlsx" \
  --examples "{PDF_PATH}" \
  --vocab-pages 170-184
```

**方式三：独立生成例句（对已有词汇表）**
```bash
"$PYTHON" "{SKILL_ROOT}/scripts/generate_examples.py" "词汇表_清洗后.xlsx" "{PDF_PATH}" \
  --output "词汇表_带例句.xlsx" \
  --vocab-pages 170-184 \
  --llm-api-key "sk-xxx"   # 可选，LLM兜底
```

### 覆盖率说明

脚本运行时输出例句覆盖率，例如：
```
正文匹配成功: 631/656 (96%)
例句覆盖率: 631/656 (96%)
未匹配单词: 25 个（可手动补充或配置--llm-api-key）
```

未匹配的单词例句列留空，可告知用户覆盖率，建议手动补充或配置 LLM API key 自动生成。

## Troubleshooting

### 词汇表未定位到

- 自动扫描依赖标题模式匹配，若教材标题不规范，需人工查看 PDF 并用 `--pages` 手动指定。
- 可先翻阅 PDF 目录页（通常前几页），找到"Words and Expressions"或"Vocabulary"对应页码。
- **注意区分**：按单元词汇表（Words and Expressions in Each Unit）与 A-Z 索引表（Vocabulary Index），只提取前者。

### 词头含中文 / 释义含英文

- 通常是栏切分位置 `--cut` 不准确，导致左右栏 token 混入。查看 PDF 实际版式，手动调整 `--cut`。
- 也可能是页眉区域 token 未跳过，调整 `--top-skip`。

### 右栏词头被误分到左栏（条目相互混入）

- 部分教材奇数/偶数页的右栏起始 x0 不同（如九年级：奇数页 289，偶数页 266.5）。固定 `page.width/2`（约 269）会把偶数页右栏词头（266.5）分到左栏。
- 修复：**不要手动指定 `--cut`**，让脚本按页动态检测（默认行为）。

### 括号不平衡（如 `fly (flew` 缺右括号）

- 右括号 `)` 常粘连在 PUA 音标 token 末尾（如 `/flaɪ/)飞`），PUA 分支需在 cjk 分支之前处理。
- 如仍出现问题，dump 该词的原始 token 检查 token 结构：
  ```bash
  "$PYTHON" -c "
  import pdfplumber
  with pdfplumber.open('$PDF_PATH') as pdf:
      for w in pdf.pages[PAGE].extract_words():
          if 'flew' in w['text'].lower() or any(0xE000<=ord(c)<=0xF8FF for c in w['text']):
              print(w['top'], w['x0'], repr(w['text']))
  "
  ```

### 单元分组不完整

- 检查 `--unit-header` 是否匹配教材的实际标题词（默认 `Unit`，部分教材可能用 `Lesson` 或中文）。
- 若某个单元整体缺失，检查该页 "Unit N" 是否被双栏切分线割裂（如 "Unit" 在左栏、"7" 在右栏）。脚本已通过整页预扫描解决，无需手工处理。

### 释义为空（如 attention、pay attention to）

- 检查主循环的页脚广告过滤正则是否误删了正常释义。**"关注" 可能是正常释义**（如 "注意；关注"），过滤正则应匹配组合关键词（`微信公众号`）而非单个 `关注`。

### 释义缺左括号（如 `中国）功夫`、`非正式）稍微`）
- **根因**：词性+全角左括号粘连（如 `n.（`）或英文+全角左括号粘连（如 `of（`）时，脚本判断为释义括号但未将 `（` 加入释义，导致左括号丢失。
- **修复（v2）**：两个分支均已将释义用全角左括号 `（` 加入 `cur_chars`。如仍出现此问题，检查该条目的 token 是否为其他粘连形式（如音标+全角左括号）。

### 词形变化跨行后释义多右括号或缺分号（如 `glass` → `玻璃；玻璃杯眼镜）`）
- **根因**：词形变化括号跨行（上行 `（pl.`、下行 `glasses眼镜）`），下行 token 中全角右括号与释义中文粘连，词形闭合时 `）` 被误加入释义，且新义项 `眼镜` 未加分号。
- **修复（v2）**：词形闭合分支（paren_depth>0）已过滤 rest 中的全角右括号，并将后续中文作为新义项加分号分隔。

## Resources

### scripts/

- `extract_vocab.py`：核心提取脚本，支持 CLI 参数化调用。含 `--clean` 参数可提取后自动串联清洗。
- `clean_vocab.py`：数据清洗脚本，可独立调用（接收 Excel 或 JSON），也可被 `extract_vocab.py --clean` 自动调用。实现列结构调整、单元规范化、词性标准化映射、质量自检与日志输出。支持 `--examples` 参数在清洗后自动生成例句。
- `generate_examples.py`：例句生成脚本，可独立调用，也可被 `clean_vocab.py --examples` 自动调用。优先从教材正文页提取包含目标单词的原句，支持词形变化匹配、PDF拆分单词匹配、短语核心词组合匹配；未匹配的单词可用 LLM API 生成兜底。

### references/

本技能无 references 文件。所有技术细节已包含在 SKILL.md 和脚本注释中。

### assets/

本技能无 assets 文件。

## Usage Example

用户上传 `七年级下册.pdf`，要求提取词汇表：

```bash
# 1. 确定环境（PYTHON 和 SCRIPT 变量参见前文"变量约定"）
# PYTHON="python"   # 或 python3
# SCRIPT="{SKILL_ROOT}/scripts/extract_vocab.py"

# 2. 扫描定位
"$PYTHON" "$SCRIPT" "/path/to/七年级下册.pdf" --scan-only
# → 输出: 106-114

# 3. 提取
"$PYTHON" "$SCRIPT" "/path/to/七年级下册.pdf" \
  --pages 106-114 \
  --output "七年级下册词汇表.xlsx" \
  --json "_vocab_entries.json"

# 4. 检查 stderr 质检输出，确认无异常后 present_files 交付
```

用户上传 `九年级全一册.pdf`，要求提取按单元词汇表：

```bash
# 2. 扫描定位（自动排除 Vocabulary Index 索引表）
"$PYTHON" "$SCRIPT" "/path/to/九年级全一册.pdf" --scan-only
# → 输出: 170-184

# 3. 提取（cut 默认按页动态检测，无需指定）
"$PYTHON" "$SCRIPT" "/path/to/九年级全一册.pdf" \
  --pages 170-184 \
  --output "九年级全一册词汇表_按单元.xlsx" \
  --json "_vocab9_unit_entries.json"

# 4. 检查 stderr 质检输出，确认无异常后 present_files 交付
```

用户上传 `七年级下册.pdf`，要求提取并直接返回清洗后的词汇表：

```bash
# 1. 扫描定位
"$PYTHON" "$SCRIPT" "/path/to/七年级下册.pdf" --scan-only
# → 输出: 106-114

# 2. 提取 + 自动清洗（一条命令完成）
"$PYTHON" "$SCRIPT" "/path/to/七年级下册.pdf" \
  --pages 106-114 \
  --output "七年级下册词汇表.xlsx" \
  --clean
# → 同时输出:
#   七年级下册词汇表.xlsx        （原始提取格式，2个Sheet）
#   七年级下册词汇表_清洗后.xlsx  （清洗后格式，1个Sheet：单词|所属单元|词性|中文释义|例句）

# 3. 检查 stderr 中的提取质检 + 清洗日志，确认无异常后
#    优先 present_files 交付 七年级下册词汇表_清洗后.xlsx
```

也可对已有的提取结果单独执行清洗：

```bash
"$PYTHON" "{SKILL_ROOT}/scripts/clean_vocab.py" "七年级下册词汇表.xlsx" --output "七年级下册词汇表_清洗后.xlsx"
```
