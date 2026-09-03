@echo off
REM ============================================================
REM  试卷/教材 OCR 切题 + 层级命名工作流 启动器（测试版）
REM  用法:  run_workflow.bat <输入PDF> [--kind textbook|exam] [选项...]
REM  示例:  run_workflow.bat samples\2026年4月广州市初三一模数学试卷.pdf --kind exam
REM         run_workflow.bat samples\勤学早...pdf --kind textbook --toc-page 3
REM  输出:  当前目录下 <文件名>_work\output_hier\ (按层级命名归档)
REM ============================================================
set VENV_PY=D:\skillDiy\exam-question-workflow\.venv\Scripts\python.exe
"%VENV_PY%" "%~dp0upgrades\run_workflow.py" %*
