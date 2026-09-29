# ============================================================
#  WATCHDOG BOT TELEGRAM - pastikan bot online 24/7
#  Cek tiap 5 menit: kalau bot tidak merespon -> start ulang.
#  Jalankan SEKALI saja (otomatis via Task Scheduler saat logon):
#    pythonw watchdog_bot.py
# ============================================================

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent
TOKEN = (BASE_DIR / "token.txt").read_text(encoding="utf-8").strip()
CHECK_URL = f"https://api.telegram.org/bot{TOKEN}/getMe"
BOT_DIR = str(BASE_DIR)
PYW = str(Path(sys.executable).with_name("pythonw.exe"))
if not Path(PYW).exists():
    PYW = "pythonw.exe"


def bot_hidup():
    """Bot dianggap hidup kalau proses pythonw tg_bot ada DI MESI INI.
    (getMe cuma cek token, bukan proses; jadi pakai tasklist.)"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq pythonw.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=20).stdout.lower()
        return "pythonw.exe" in out
    except Exception:
        return False


def start_bot():
    subprocess.Popen(
        [PYW, "tg_bot.py"], cwd=BOT_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    print(f"[{time.strftime('%H:%M:%S')}] bot di-start", flush=True)


def main():
    print(f"[{time.strftime('%H:%M:%S')}] watchdog mulai (cek tiap 5 menit)",
          flush=True)
    time.sleep(20)  # kasih waktu bot start pertama kali
    while True:
        try:
            if not bot_hidup():
                print(f"[{time.strftime('%H:%M:%S')}] BOT MATI -> start ulang",
                      flush=True)
                start_bot()
        except Exception as e:
            print(f"[watchdog] error: {e}", flush=True)
        time.sleep(300)


if __name__ == "__main__":
    main()
