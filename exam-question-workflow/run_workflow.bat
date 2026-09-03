@echo off
REM ============================================================
REM  试卷/教材 OCR 切题 + 层级命名工作流 启动器（测试版）
REM  用法:  run_workflow.bat <输入PDF> [--kind textbook|exam] [选项...]
REM  示例:  run_workflow.bat samples\2026年4月广州市初三一模数学试卷.pdf --kind exam
REM         run_workflow.bat samples\勤学早...pdf --kind textbook --toc-page 3
REM  输出:  当前目录下 <文件名>_work\output_hier\ (按层级命名归档)
REM ============================================================
REM 虚拟环境路径相对本 bat 所在目录，克隆到任意位置均可（无需写死绝对路径）
set VENV_PY=%~dp0.venv\Scripts\python.exe
if not exist "%VENV_PY%" (
  echo [错误] 未找到 .venv 虚拟环境。请先在本目录创建并安装依赖:
  echo   python -m venv .venv
  echo   .venv\Scripts\python -m pip install -r requirements.txt
  echo   （详见本目录 README.md 第零章“克隆本仓库后如何运行”）
  exit /b 1
)
"%VENV_PY%" "%~dp0upgrades\run_workflow.py" %*
