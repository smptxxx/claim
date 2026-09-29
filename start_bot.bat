@echo off
REM ==== TENCENT CLAIM BOT - START DETACHED ====
REM Menjalankan bot dengan pythonw (tanpa window, lepas dari sesi apapun).
cd /d "%~dp0"
for /f "delims=" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%i
if not exist "%PYW%" set PYW=pythonw.exe
start "TencentBot" /b "%PYW%" tg_bot.py
exit
