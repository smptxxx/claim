@echo off
REM ============================================
REM  Fix Firewall untuk Auto Claim Bot (Tencent)
REM  Klik kanan file ini -> Run as administrator
REM ============================================

echo.
echo [1/3] Menambah rule firewall INBOUND untuk Chromium Playwright...
netsh advfirewall firewall add rule name="Playwright Chromium Bot" dir=in action=allow program="C:\Users\NEXUSDEV\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe" enable=yes profile=any

echo [2/3] Menambah rule firewall OUTBOUND untuk Chromium Playwright...
netsh advfirewall firewall add rule name="Playwright Chromium Bot" dir=out action=allow program="C:\Users\NEXUSDEV\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe" enable=yes profile=any

echo [3/4] Menambah rule firewall untuk chrome_proxy.exe (helper Chromium)...
netsh advfirewall firewall add rule name="Playwright Chromium Proxy" dir=in action=allow program="C:\Users\NEXUSDEV\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome_proxy.exe" enable=yes profile=any
netsh advfirewall firewall add rule name="Playwright Chromium Proxy" dir=out action=allow program="C:\Users\NEXUSDEV\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome_proxy.exe" enable=yes profile=any

echo [3b/4] Menambah rule firewall untuk chrome_pwa_launcher.exe (helper PWA)...
netsh advfirewall firewall add rule name="Playwright Chromium PWA" dir=in action=allow program="C:\Users\NEXUSDEV\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome_pwa_launcher.exe" enable=yes profile=any
netsh advfirewall firewall add rule name="Playwright Chromium PWA" dir=out action=allow program="C:\Users\NEXUSDEV\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome_pwa_launcher.exe" enable=yes profile=any

echo [4/4] Mengubah jaringan Wi-Fi dari Public ke Private (mengurangi popup firewall)...
powershell -Command "Set-NetConnectionProfile -InterfaceAlias 'Wi-Fi' -NetworkCategory Private"

echo.
echo ============================================
echo  SELESAI! Popup firewall tidak akan muncul
echo  lagi saat bot jalan.
echo ============================================
pause
