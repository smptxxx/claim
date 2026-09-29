@echo off
REM ============================================
REM  Launcher Auto Claim TUI (jendela cmd penuh)
REM  Double-click file ini untuk menjalankan bot
REM  dengan dashboard live.
REM ============================================
title Tencent Auto Claim TUI
cd /d "%~dp0"

echo.
echo  Pilih mode:
echo    [1] Test claim COS (latihan)
echo    [2] Claim langsung sekarang (Lighthouse)
echo    [3] WAR 23:00 — relogin 22:45, standby 22:55, gas 23:00 (2C2G)
echo    [4] Login semua akun dulu
echo.
set /p choice="Pilih (1/2/3/4): "

if "%choice%"=="1" py -X utf8 auto_claim_tui.py --test
if "%choice%"=="2" py -X utf8 auto_claim_tui.py --retry-now
if "%choice%"=="3" py -X utf8 auto_claim_tui.py
if "%choice%"=="4" py -X utf8 auto_claim_tui.py --login

echo.
echo Selesai. Tekan tombol apa saja untuk keluar...
pause >nul
