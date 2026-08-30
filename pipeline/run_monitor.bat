@echo off
set PROJECT_ROOT=D:\dataset\server\local
set MONITOR_PASSWORD=yuanlai2026
cd /d D:\dataset\server\local
python status_server.py --port 8080 >> "%PROJECT_ROOT%\monitor.log" 2>&1
