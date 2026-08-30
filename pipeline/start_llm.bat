@echo off
title LLM Analysis - 8 workers
cd /d D:\dataset\server\local
set PROJECT_ROOT=D:\dataset\server\local
set PYTHONIOENCODING=utf-8
echo [start] PROJECT_ROOT=%PROJECT_ROOT%
python -u batch_llm.py --all --workers 8
echo.
echo [exited] press any key to close
pause >nul
