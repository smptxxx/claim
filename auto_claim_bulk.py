# ============================================================
#  AUTO CLAIM TENCENT CLOUD - BULK EDITION
#  Multi-akun, browser terpisah per akun, claim bersamaan 23:00
# ============================================================
#  Cara pakai:
#    1. Isi daftar akun di file accounts.txt (format: email:password per baris)
#    2. Login semua akun sekaligus : python auto_claim_bulk.py --login
#    3. Jalankan bot claim        : python auto_claim_bulk.py
#    4. Test claim latihan (COS)  : python auto_claim_bulk.py --test
#    5. Claim langsung sekarang   : python auto_claim_bulk.py --retry-now
# ============================================================

import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

# ================== KONFIGURASI ==================
BASE_DIR = Path(__file__).parent
ACCOUNTS_FILE = BASE_DIR / "accounts.txt"          # daftar akun bulk
SESSION_DIR = BASE_DIR / "sessions"                # session per akun
FREE_TIER_URL = "https://www.tencentcloud.com/act/pro/FreeTier"
LOGIN_URL = "https://www.tencentcloud.com/account/login"

CLAIM_HOUR = 23
CLAIM_MINUTE = 0
PREPARE_SECONDS = 30  # siap 30 detik sebelumnya

# Mode claim: "lighthouse" (2C2G 3 bulan) atau "cos" (Cloud Object Storage, latihan)
CLAIM_MODE = "lighthouse"
# =================================================

SESSION_DIR.mkdir(exist_ok=True)


def load_accounts():
    """Baca accounts.txt -> list of (email, password)."""
    if not ACCOUNTS_FILE.exists():
        print(f"[!] File {ACCOUNTS_FILE} tidak ada. Buat dulu!")
        print("    Format per baris: email:password")
        print("    Contoh:")
        print("      evi548@gitech.app:Buka@122")
        print("      akun2@mail.com:Password123")
        return []
    accounts = []
    for line in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            print(f"[!] Baris tidak valid (skip): {line}")
            continue
        email, _, password = line.partition(":")
        accounts.append((email.strip(), password.strip()))
    print(f"[+] {len(accounts)} akun dimuat dari {ACCOUNTS_FILE.name}")
    return accounts


def session_path(email):
    """Path session json per akun."""
    safe = email.replace("@", "_at_").replace(".", "_")
    return SESSION_DIR / f"{safe}.json"


# ================== LOGIN BULK ==================

async def dismiss_cookie_dialog(page):
    """Tutup dialog cookies (Accept/Reject) jika muncul."""
    try:
        for sel in [
            'button:has-text("Accept all optional cookies")',
            'button:has-text("Reject all optional cookies")',
            'button:has-text("Accept all")',
            'button:has-text("Reject all")',
            'button:has-text("Accept")',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click(timeout=2000)
                    print(f"    [{page._email}] Dialog cookies ditutup ({sel})")
                    await page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False

async def login_one(playwright, email, password):
    """Login satu akun, simpan session ke file terpisah."""
    sp = session_path(email)
    browser = await playwright.chromium.launch(headless=False)
    ctx = await browser.new_context()
    page = await ctx.new_page()
    page._email = email

    print(f"    [{email}] Membuka halaman login...")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)

    # Tutup dialog cookies dulu kalau muncul (bisa nutupin form login!)
    await dismiss_cookie_dialog(page)

    try:
        await page.fill('input[type="text"], input[placeholder*="mail" i]', email)
        await page.fill('input[type="password"]', password)
        await page.click('button:has-text("Log in")')
    except Exception as e:
        print(f"    [{email}] GAGAL isi form: {e}")

    # Tunggu redirect keluar dari halaman login
    try:
        await page.wait_for_url(lambda u: "login" not in u, timeout=30000)
    except Exception:
        pass

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    await dismiss_cookie_dialog(page)

    content = await page.content()
    # Logged out = header masih ada "Sign Up Free" / "Log in with email"
    if "Sign Up Free" in content or "Log in with email" in content:
        print(f"    [{email}] Login GAGAL / butuh captcha -> login manual di browser!")
        input(f"    [{email}] Tekan Enter setelah login manual...")
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await dismiss_cookie_dialog(page)

    await ctx.storage_state(path=str(sp))
    print(f"    [{email}] Session tersimpan -> {sp.name}")
    await browser.close()


async def login_all():
    """Login semua akun satu per satu (browser terpisah per akun)."""
    accounts = load_accounts()
    if not accounts:
        return
    async with async_playwright() as p:
        for i, (email, password) in enumerate(accounts, 1):
            print(f"\n=== LOGIN AKUN {i}/{len(accounts)}: {email} ===")
            await login_one(p, email, password)
    print(f"\n[+] SEMUA AKUN SELESAI LOGIN! ({len(accounts)} akun)")


# ================== CLAIM PER AKUN ==================

async def try_click(page, selectors, desc, timeout=3000):
    """Coba klik dengan beberapa selector alternatif."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.click(timeout=timeout)
            print(f"    [{page._email}] {desc} -> OK")
            return True
        except Exception:
            continue
    print(f"    [{page._email}] {desc} GAGAL")
    return False


async def dismiss_busy_popup(page):
    """Tutup popup 'The system is busy at the moment' jika muncul."""
    try:
        busy = page.locator('text=The system is busy').first
        if await busy.is_visible(timeout=500):
            print(f"    [{page._email}] Popup 'system busy' terdeteksi, tutup...")
            for sel in ['button:has-text("Confirm")', 'button:has-text("OK")',
                        'button:has-text("确定")']:
                try:
                    await page.locator(sel).last.click(timeout=1500)
                    await page.wait_for_timeout(800)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


async def claim_product(page):
    """Alur claim: refresh -> Get Started -> Buy Now -> Pay Now -> Confirm."""
    email = page._email
    mode = page._mode

    print(f"    [{email}] [1] Refresh halaman FreeTier...")
    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)

    # Tutup cookie dialog jika muncul
    await dismiss_cookie_dialog(page)

    # Cari kartu produk sesuai mode
    if mode == "cos":
        keywords = ["object storage"]
        print(f"    [{email}] [2] Cari produk Cloud Object Storage...")
    else:
        keywords = ["lighthouse"]
        print(f"    [{email}] [2] Cari produk Lighthouse 2C2G...")

    clicked = False
    for _ in range(3):
        # Cari SEMUA tombol Get Started, lalu cek teks kartu induknya
        # (xpath ancestor terdekat yang punya tombol = kartu produk)
        btns = page.locator('button:has-text("Get Started")')
        count = await btns.count()
        for i in range(count):
            btn = btns.nth(i)
            try:
                card = btn.locator('xpath=ancestor::div[.//button][1]')
                text = (await card.inner_text(timeout=1000)).lower()
                if mode == "cos":
                    match = "object storage" in text
                else:
                    match = ("lighthouse" in text and
                             ("2c2g" in text or "2c 2g" in text) and
                             "3 months" in text)
                if match:
                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=3000)
                    clicked = True
                    print(f"    [{email}] Get Started diklik! (kartu cocok)")
                    break
            except Exception:
                continue
        if clicked:
            break
        await page.wait_for_timeout(1000)

    if not clicked:
        print(f"    [{email}] [!] Tombol Get Started tidak ditemukan!")
        return False

    # TUNGU dialog konfigurasi benar-benar muncul (bukan delay tetap)
    try:
        await page.wait_for_selector(
            'button:has-text("Buy Now"), button:has-text("立即购买")',
            timeout=10000)
        print(f"    [{email}] Dialog konfigurasi muncul")
    except Exception:
        print(f"    [{email}] [!] Dialog Buy Now tidak muncul!")
        return False

    await page.wait_for_timeout(800)

    # Dialog konfigurasi muncul -> Buy Now
    print(f"    [{email}] [3] Klik Buy Now...")
    await try_click(page, ['button:has-text("Buy Now")'], "Buy Now")
    await page.wait_for_timeout(2500)

    # Handle popup 'system busy'
    await dismiss_busy_popup(page)

    # Tunggu pindah ke halaman order (intlPrepay)
    try:
        await page.wait_for_url(
            lambda u: ("intlprepay" in u.lower()) or ("order" in u.lower()),
            timeout=10000)
        print(f"    [{email}] Di halaman order")
    except Exception:
        print(f"    [{email}] [!] Tidak pindah ke halaman order (URL: {page.url[:60]})")

    # Halaman konfirmasi order -> Pay Now (立即支付)
    print(f"    [{email}] [4] Klik Pay Now (立即支付)...")
    await try_click(page, [
        'button:has-text("立即支付")',
        'button:has-text("Pay Now")',
    ], "Pay Now")
    await page.wait_for_timeout(1500)

    # Handle popup 'system busy' lagi
    await dismiss_busy_popup(page)

    # Dialog metode pembayaran -> Confirm (确认支付)
    print(f"    [{email}] [5] Klik Confirm Payment (确认支付)...")
    await try_click(page, [
        'button:has-text("确认支付")',
        'button:has-text("Confirm")',
    ], "Confirm Payment")

    await page.wait_for_timeout(3000)
    shot = BASE_DIR / f"claim_{email.split('@')[0]}_{mode}.png"
    await page.screenshot(path=str(shot), full_page=True)
    print(f"    [{email}] SELESAI! Screenshot: {shot.name}")
    return True


async def claim_and_verify(ctx, email, password, mode):
    """Buka browser untuk 1 akun, jalankan claim, verifikasi hasil."""
    sp = session_path(email)
    if not sp.exists():
        print(f"    [{email}] [!] Belum ada session! Jalankan --login dulu.")
        return False

    browser = await ctx.chromium.launch(headless=False)
    context = await browser.new_context(storage_state=str(sp))
    page = await context.new_page()
    page._email = email
    page._mode = mode

    # Buka FreeTier, cek session masih valid
    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await dismiss_cookie_dialog(page)
    content = await page.content()
    # Logged out = header masih ada "Sign Up Free" / "Log In"
    if "Sign Up Free" in content or "Log in with email" in content:
        print(f"    [{email}] Session expired, login ulang...")
        await context.close()
        await browser.close()
        # Login ulang otomatis
        async with async_playwright() as p2:
            await login_one(p2, email, password)
        # Buka browser lagi
        browser = await ctx.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=str(sp))
        page = await context.new_page()
        page._email = email
        page._mode = mode
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await dismiss_cookie_dialog(page)

    success = False
    for attempt in range(1, 4):
        print(f"    [{email}] === PERCOBAAN {attempt} ===")
        ok = await claim_product(page)
        if ok:
            content = await page.content()
            url = page.url
            # Sukses HANYA jika diarahkan ke halaman order selesai (done page)
            if ("intlPrepay/done" in url or "BigOrderIds" in url or "分配" in content) and \
               "The system is busy" not in content:
                print(f"    [{email}] [✓] CLAIM BERHASIL! URL: {url}")
                success = True
                break
            else:
                print(f"    [{email}] [!] Belum sukses (URL: {url[:60]}), retry...")
        await page.wait_for_timeout(2000)

    # Browser tetap terbuka 30 detik untuk verifikasi manual
    await page.wait_for_timeout(30000)
    await context.close()
    await browser.close()
    return success


async def run_claim_all(mode="lighthouse"):
    """Jalankan claim untuk SEMUA akun secara PARALEL (browser terpisah)."""
    accounts = load_accounts()
    if not accounts:
        return

    print(f"\n[*] Menjalankan claim untuk {len(accounts)} akun secara paralel...")
    print(f"[*] Mode: {mode.upper()}")
    print("[*] Setiap akun punya browser terpisah.\n")

    async with async_playwright() as p:
        tasks = [claim_and_verify(p, email, password, mode)
                 for email, password in accounts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    print("\n" + "=" * 50)
    print("HASIL CLAIM:")
    print("=" * 50)
    for (email, _), res in zip(accounts, results):
        if isinstance(res, Exception):
            print(f"  [✗] {email} -> ERROR: {res}")
        elif res:
            print(f"  [✓] {email} -> BERHASIL")
        else:
            print(f"  [✗] {email} -> GAGAL")


# ================== SCHEDULER ==================

def wait_until_target():
    """Tunggu sampai mendekati jam target (22:59:30)."""
    now = datetime.now()
    target = now.replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    prepare_at = target - timedelta(seconds=PREPARE_SECONDS)
    print(f"[*] Target claim : {target.strftime('%H:%M:%S')}")
    print(f"[*] Siap di jam  : {prepare_at.strftime('%H:%M:%S')}")
    print(f"[*] Akun         : {len(load_accounts())} akun (paralel)")
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
    print("[+] JAM 23:00! MENJALANKAN CLAIM SEMUA AKUN!")


# ================== MAIN ==================

async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "--login":
        await login_all()
        return

    if mode == "--test":
        print("[*] MODE TEST: claim Cloud Object Storage (latihan)")
        await run_claim_all(mode="cos")
        return

    if mode == "--retry-now":
        print("[*] MODE RETRY: claim langsung tanpa nunggu jam 23:00")
        await run_claim_all(mode="lighthouse")
        return

    # Mode normal: tunggu jam 23:00 lalu claim semua akun
    accounts = load_accounts()
    if not accounts:
        return
    print(f"[*] BULK EDITION - {len(accounts)} akun siap")
    wait_until_target()
    await run_claim_all(mode="lighthouse")


if __name__ == "__main__":
    asyncio.run(main())
