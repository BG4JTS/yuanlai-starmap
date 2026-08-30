@echo off
set PROJECT_ROOT=D:\dataset\server\local
set MONITOR_PASSWORD=yuanlai2026
cd /d D:\dataset\server\local
python -u batch_llm.py --all --workers 3 >> "%PROJECT_ROOT%\llm_local.log" 2>&1
