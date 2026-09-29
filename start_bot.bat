@echo off
REM ==== TENCENT CLAIM BOT - AUTO START ====
REM Jalankan bot secara detached (pythonw, tanpa window), cegah dobel.
cd /d "%~dp0"
start "" /b pythonw tg_bot.py
exit
