"""
Auto Claim Tencent Cloud Free Tier - Lighthouse 2C2G 3 Months
==============================================================
Strategi:
- Jam 22:59:30 script siap di halaman FreeTier
- Jam 23:00:00 langsung refresh -> Get Started -> Buy Now -> Pay Now -> Confirm

Cara pakai:
1. Install: pip install playwright python-dotenv
2. playwright install chromium
3. Login sekali untuk simpan session: python auto_claim.py --login
4. Jalankan auto claim: python auto_claim.py
"""

import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

# ============ KONFIGURASI ============
EMAIL = "evi548@gitech.app"
PASSWORD = "Buka@122"
FREE_TIER_URL = "https://www.tencentcloud.com/act/pro/FreeTier"
LOGIN_URL = "https://www.tencentcloud.com/account/login"
STORAGE_STATE = Path("tencent_session.json")

# Target waktu claim (jam lokal komputer)
CLAIM_HOUR = 23
CLAIM_MINUTE = 0
PREPARE_SECONDS = 30  # siap 30 detik sebelumnya

# Keyword produk yang dicari (Lighthouse 2C2G)
PRODUCT_KEYWORDS = ["lighthouse", "2c2g"]
# =====================================


async def login_and_save(playwright):
    """Login sekali dan simpan session cookies."""
    browser = await playwright.chromium.launch(headless=False)
    ctx = await browser.new_context()
    page = await ctx.new_page()

    print("[*] Membuka halaman login...")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")

    # Isi email & password
    await page.fill('input[type="text"], input[placeholder*="mail" i]', EMAIL)
    await page.fill('input[type="password"]', PASSWORD)
    await page.click('button:has-text("Log in")')

    # Tunggu login sukses (redirect ke halaman utama)
    try:
        await page.wait_for_url("**/account/login**", wait_until="domcontentloaded", timeout=15000)
        # kadang ada redirect token, tunggu lagi
        await page.wait_for_url(lambda u: "login" not in u, timeout=30000)
    except Exception:
        pass

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Verifikasi login: cek apakah masih ada form login
    content = await page.content()
    if "Log in with email" in content:
        print("[!] Login GAGAL - cek email/password atau ada captcha")
        input("Tekan Enter setelah login manual di browser...")
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")

    await ctx.storage_state(path=str(STORAGE_STATE))
    print(f"[+] Session tersimpan ke {STORAGE_STATE}")
    await browser.close()


def wait_until_target():
    """Tunggu sampai mendekati jam target (22:59:30)."""
    now = datetime.now()
    target = now.replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    prepare_at = target - timedelta(seconds=PREPARE_SECONDS)
    print(f"[*] Target claim : {target.strftime('%H:%M:%S')}")
    print(f"[*] Siap di jam  : {prepare_at.strftime('%H:%M:%S')}")
    print("[*] Menunggu... (Ctrl+C untuk batal)")

    while True:
        now = datetime.now()
        if now >= prepare_at:
            break
        remaining = (prepare_at - now).total_seconds()
        if remaining > 60:
            print(f"    {int(remaining//60)} menit lagi...", flush=True)
            time.sleep(min(30, remaining - 30))
        else:
            time.sleep(0.5)

    # Countdown presisi sampai tepat jam target
    target_ts = datetime.now().replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE,
                                       second=0, microsecond=0).timestamp()
    while time.time() < target_ts:
        time.sleep(0.05)
    print("[+] JAM 23:00! MENJALANKAN CLAIM!")


async def try_click(page, selectors, desc, timeout=3000):
    """Coba klik dengan beberapa selector alternatif."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.click(timeout=timeout)
            print(f"[+] {desc} -> OK ({sel})")
            return True
        except Exception:
            continue
    print(f"[-] {desc} GAGAL")
    return False

async def dismiss_busy_popup(page):
    """Tutup popup 'The system is busy at the moment' jika muncul."""
    try:
        busy = page.locator('text=The system is busy').first
        if await busy.is_visible(timeout=500):
            print("[!] Popup 'system busy' terdeteksi, tutup...")
            # Klik tombol Confirm/OK di dialog yang sama
            for sel in ['button:has-text("Confirm")', 'button:has-text("OK")',
                        'button:has-text("确定")']:
                try:
                    await page.locator(sel).last.click(timeout=1500)
                    print("[+] Popup busy ditutup")
                    await page.wait_for_timeout(800)
                    return True
                except Exception:
                    continue
            # Fallback: klik tombol X close
            try:
                await page.locator('button:near(text=The system is busy)').click(timeout=1500)
            except Exception:
                pass
    except Exception:
        pass
    return False


async def claim_lighthouse(page):
    """Alur claim: refresh -> Get Started -> Buy Now -> Pay Now -> Confirm."""
    print("[1] Refresh halaman FreeTier...")
    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)

    # Tutup cookie dialog jika muncul
    await try_click(page, [
        'button:has-text("Accept all optional cookies")',
        'button:has-text("Reject all optional cookies")',
    ], "Tutup cookie dialog", timeout=2000)

    # Cari kartu produk Lighthouse 2C2G lalu klik Get Started di dalamnya
    print("[2] Cari produk Lighthouse 2C2G...")
    clicked = False
    for _ in range(3):
        # Coba cari card yang mengandung teks Lighthouse / 2C2G
        cards = page.locator('div:has-text("Lighthouse")')
        count = await cards.count()
        for i in range(count):
            card = cards.nth(i)
            try:
                text = await card.inner_text(timeout=1000)
                if ("2C2G" in text or "2C 2G" in text) and "3 months" in text.lower():
                    btn = card.locator('button:has-text("Get Started")').first
                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=3000)
                    clicked = True
                    print("[+] Get Started Lighthouse diklik!")
                    break
            except Exception:
                continue
        if clicked:
            break
        await page.wait_for_timeout(1000)

    if not clicked:
        # Fallback: klik Get Started pertama yang available (bukan Sold out)
        print("[*] Fallback: klik Get Started pertama...")
        btns = page.locator('button:has-text("Get Started")')
        n = await btns.count()
        for i in range(n):
            b = btns.nth(i)
            if await b.is_enabled() and await b.is_visible():
                await b.scroll_into_view_if_needed()
                await b.click()
                clicked = True
                print(f"[+] Get Started #{i} diklik")
                break

    if not clicked:
        print("[!] Tombol Get Started tidak ditemukan!")
        return False

    await page.wait_for_timeout(1500)

    # Dialog konfigurasi muncul -> Buy Now
    print("[3] Klik Buy Now...")
    await try_click(page, ['button:has-text("Buy Now")'], "Buy Now")
    await page.wait_for_timeout(2500)

    # Handle popup 'system busy' yang bisa muncul setelah Buy Now
    await dismiss_busy_popup(page)

    # Halaman konfirmasi order -> Pay Now (立即支付)
    print("[4] Klik Pay Now (立即支付)...")
    await try_click(page, [
        'button:has-text("立即支付")',
        'button:has-text("Pay Now")',
    ], "Pay Now")
    await page.wait_for_timeout(1500)

    # Handle popup 'system busy' lagi
    await dismiss_busy_popup(page)

    # Dialog metode pembayaran -> Confirm (确认支付)
    print("[5] Klik Confirm Payment (确认支付)...")
    await try_click(page, [
        'button:has-text("确认支付")',
        'button:has-text("Confirm")',
    ], "Confirm Payment")

    await page.wait_for_timeout(3000)
    print("[+] SELESAI! Cek screenshot & halaman untuk verifikasi.")
    await page.screenshot(path="claim_result.png", full_page=True)
    return True


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    async with async_playwright() as p:
        if mode == "--login":
            await login_and_save(p)
            return

        if not STORAGE_STATE.exists():
            print("[!] Belum ada session. Jalankan dulu: python auto_claim.py --login")
            return

        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(storage_state=str(STORAGE_STATE))
        page = await ctx.new_page()

        # Buka halaman FreeTier dulu, pastikan login masih valid
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
        content = await page.content()
        if "Log in with email" in content:
            print("[!] Session expired, login ulang: python auto_claim.py --login")
            await browser.close()
            return

        print("[+] Login valid. Browser siap di halaman FreeTier.")

        # Mode --retry-now: langsung claim tanpa nunggu jam target
        if "--retry-now" in sys.argv:
            print("[*] MODE RETRY LANGSUNG!")
            for attempt in range(1, 6):
                print(f"\n=== PERCOBAAN {attempt} ===")
                ok = await claim_lighthouse(page)
                if ok:
                    content = await page.content()
                    url = page.url
                    # Sukses HANYA jika diarahkan ke halaman order selesai
                    if ("intlPrepay/done" in url or "BigOrderIds" in url or "分配" in content) and \
                       "The system is busy" not in content:
                        print("[✓] CLAIM BERHASIL!")
                        break
                    else:
                        print("[!] Belum sukses (popup busy / halaman salah), retry...")
                await page.wait_for_timeout(2000)
            print("\n[*] Browser tetap terbuka 60 detik untuk verifikasi...")
            await page.wait_for_timeout(60000)
            await browser.close()
            return

        # Tunggu sampai jam target
        wait_until_target()

        # Jalankan claim (dengan retry 3x jika gagal)
        for attempt in range(1, 4):
            print(f"\n=== PERCOBAAN {attempt} ===")
            ok = await claim_lighthouse(page)
            if ok:
                content = await page.content()
                url = page.url
                # Sukses hanya jika di halaman order selesai (done page), BUKAN popup busy
                if ("intlPrepay/done" in url or "BigOrderIds" in url or "分配" in content) and \
                   "The system is busy" not in content:
                    print("[✓] CLAIM BERHASIL!")
                    break
                else:
                    print("[!] Belum sukses (popup busy / halaman salah), retry...")
            await page.wait_for_timeout(1000)

        print("\n[*] Browser tetap terbuka 60 detik untuk verifikasi...")
        await page.wait_for_timeout(60000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
