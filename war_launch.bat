@echo off
REM ============================================
REM  LAUNCHER WAR TAHAN BANTING
REM  Kalau bot crash, jendela TETAP KEBUKA
REM  nampilin error (ga mati diam-diam)
REM ============================================
title WAR-2300
cd /d "%~dp0"
echo.
echo  [%time%] Meluncurkan bot WAR 23:00...
echo  Jadwal: relogin 22:45 - standby 22:55 - gas 23:00
echo.
"C:\Users\NEXUSDEV\AppData\Local\Programs\Python\Python312\python.exe" -X utf8 auto_claim_tui.py
echo.
echo ============================================
echo  BOT BERHENTI di %time% — lihat error di atas!
echo  JANGAN close jendela ini, foto dulu errornya.
echo ============================================
pause >nul
