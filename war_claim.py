# ============================================================
#  TENCENT AUTO CLAIM - WAR EDITION (v3, CLI tipis)
#  Logika ada di claim_core.py. File ini hanya CLI:
#
#    python war_claim.py --login        # login semua akun sekarang
#    python war_claim.py --test         # latihan claim COS (langsung)
#    python war_claim.py --retry-now    # gas 2C2G langsung (tanpa jadwal)
#    python war_claim.py                # WAR penuh: 22:40 login, 23:00 gas
#    python war_claim.py --status       # cek status session per akun
#
#  Akun: file accounts.txt, format per baris:  email:password
#  Remote via Telegram: python tg_bot.py
# ============================================================

import asyncio
import sys

from claim_core import JM, accounts_status


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "--login":
        print(await JM.login_all())
    elif mode == "--status":
        print(accounts_status())
    elif mode == "--test":
        print("MODE TEST: latihan claim COS")
        print(await JM.start_instant("cos"))
        if JM.job_task:
            await JM.job_task
    elif mode == "--retry-now":
        print("MODE RETRY: gas 2C2G langsung")
        print(await JM.start_instant("lighthouse"))
        if JM.job_task:
            await JM.job_task
    elif mode == "run":
        print(await JM.start_war())
        if JM.job_task:
            await JM.job_task
    else:
        print(__doc__)
        return
    await JM.shutdown()
    print("\nSelesai.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Dihentikan. Browser standby masih terbuka — tutup manual jika perlu.")
