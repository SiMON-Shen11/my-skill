# my-skill

个人自建 Skill / 工作流的版本管理仓库（GitHub: `SiMON-Shen11/my-skill`）。

## 收录清单

| 目录 | 类型 | 说明 | 自带文档 |
| --- | --- | --- | --- |
| `english-textbook-vocab-extractor_v2` | Skill | 英语教材 PDF 词汇表提取：定位附录词汇表，结构化输出单词/词性/中文释义为 Excel | `SKILL.md` |
| `zengying-style` | Skill | 曾颖文风写作 skill：模仿特定文风的写作风格与措辞规范 | `SKILL.md` |
| `exam-question-workflow` | 工作流项目 | 试卷切题工作流：PDF 渲染 → 版面分析 → OCR → 切题，含 `run_workflow` 与升级脚本 | `README.md`（内部）、`exam-question-cutter/SKILL.md` |

## 目录约定

- 每个 skill / 工作流以独立顶层文件夹存放，结构与本地 `.agents/skills/` 或项目目录保持一致。
- skill 入口说明统一用 `SKILL.md`（标准约定），不再额外加 `README.md` 造成冗余——三份内容均已自带说明文档。

## exam-question-workflow 的版本管理范围

该目录是完整工作流项目。为控制仓库体积、避免触碰 GitHub 单文件 100MB 限制，已通过 `exam-question-workflow/.gitignore` 排除以下部分（不纳入版本库）：

| 排除项 | 原因 |
| --- | --- |
| `.venv/` | Python 虚拟环境（约 4.4GB，可由依赖文件重建） |
| `samples/` | 样例数据（约 448MB，含单文件 128MB 的 PDF，超 GitHub 单文件限制） |
| `output/` | 运行产物目录 |
| `__pycache__/`、`*.pyc`、`*.bak` | 编译缓存与备份文件 |

克隆后如需本地运行，需自行 `pip install` 依赖并准备样例数据。

## 使用方式

- **Skill**：将对应文件夹复制到 WorkBuddy 的 skills 目录（用户级 `~/.workbuddy/skills/` 或项目级 `.workbuddy/skills/`）。
- **工作流**：进入 `exam-question-workflow`，参考其内部 `README.md` 与 `run_workflow.bat`。
