# ============================================================
#  TENCENT AUTO CLAIM - WAR EDITION (v2)
#  Alur otomatis penuh:
#    22:40  -> login SEMUA akun (1 akun = 1 browser Chromium terpisah)
#    22:41  -> browser STANDBY TERBUKA (tidak ditutup), reload berkala
#    22:59:52 -> refresh terakhir
#    23:00:00 -> Refresh -> Get Started -> Buy Now  (secepat mungkin)
#    Setelah Buy Now: Pay Now -> Confirm (best-effort)
#
#  Perintah:
#    python war_claim.py --login        # login semua akun sekarang
#    python war_claim.py --test         # latihan claim COS (langsung)
#    python war_claim.py --retry-now    # gas 2C2G langsung (tanpa jadwal)
#    python war_claim.py                # WAR penuh: 22:40 login, 23:00 gas
#    python war_claim.py --status       # cek status session per akun
#
#  Akun: file accounts.txt, format per baris:  email:password
# ============================================================

import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

# ================== KONFIGURASI ==================
BASE_DIR = Path(__file__).parent
ACCOUNTS_FILE = BASE_DIR / "accounts.txt"
SESSION_DIR = BASE_DIR / "sessions"

FREE_TIER_URL = "https://www.tencentcloud.com/act/pro/FreeTier"
LOGIN_URL = "https://www.tencentcloud.com/account/login"

LOGIN_HOUR = 22      # login semua akun jam 22:40
LOGIN_MINUTE = 40
CLAIM_HOUR = 23      # gas claim jam 23:00:00
CLAIM_MINUTE = 0
FINAL_REFRESH_LEAD = 8   # refresh terakhir H-8 detik
STANDBY_RELOAD_EVERY = 240  # saat standby, reload tiap 4 menit biar session hangat
CLAIM_WINDOW = 120       # detik polling setelah jam target
HEADLESS = False         # WAJIB False: browser harus kelihatan & tidak ditutup
KEEP_OPEN_AFTER = 900    # browser dibiarkan terbuka 15 menit setelah claim
# =================================================

SESSION_DIR.mkdir(exist_ok=True)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_accounts():
    """Baca accounts.txt -> list of (email, password)."""
    if not ACCOUNTS_FILE.exists():
        log(f"[!] File {ACCOUNTS_FILE} tidak ada!")
        log("    Buat file accounts.txt, format per baris: email:password")
        return []
    accounts = []
    for line in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            log(f"[!] Baris tidak valid (skip): {line}")
            continue
        email, _, password = line.partition(":")
        accounts.append((email.strip(), password.strip()))
    log(f"[+] {len(accounts)} akun dimuat dari {ACCOUNTS_FILE.name}")
    return accounts


def session_path(email):
    safe = email.replace("@", "_at_").replace(".", "_")
    return SESSION_DIR / f"{safe}.json"


# ================== COOKIE / POPUP HELPERS ==================

async def dismiss_cookie_dialog(page):
    """Tutup dialog cookies jika muncul."""
    for sel in [
        'button:has-text("Accept all optional cookies")',
        'button:has-text("Reject all optional cookies")',
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=600):
                await btn.click(timeout=1500)
                log(f"    [{page._email}] dialog cookies ditutup")
                await page.wait_for_timeout(500)
                return True
        except Exception:
            continue
    return False


async def dismiss_busy_popup(page):
    """Tutup popup 'The system is busy at the moment' jika muncul."""
    try:
        busy = page.locator('text=The system is busy').first
        if await busy.is_visible(timeout=400):
            log(f"    [{page._email}] popup 'system busy' -> tutup")
            for sel in ['button:has-text("Confirm")', 'button:has-text("OK")',
                        'button:has-text("确定")']:
                try:
                    await page.locator(sel).last.click(timeout=1200)
                    await page.wait_for_timeout(600)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


async def try_click(page, selectors, desc, timeout=2500):
    for sel in selectors:
        try:
            await page.locator(sel).first.click(timeout=timeout)
            log(f"    [{page._email}] {desc} -> OK")
            return True
        except Exception:
            continue
    log(f"    [{page._email}] {desc} -> GAGAL")
    return False


# ================== LOGIN ==================

async def login_one(pw, email, password, keep_open=False):
    """Login satu akun di browser sendiri, simpan session json."""
    sp = session_path(email)
    browser = await pw.chromium.launch(headless=HEADLESS)
    ctx = await browser.new_context()
    page = await ctx.new_page()
    page._email = email

    log(f"    [{email}] buka halaman login...")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1200)
    await dismiss_cookie_dialog(page)

    try:
        await page.fill('input[type="text"], input[placeholder*="mail" i]', email)
        await page.fill('input[type="password"]', password)
        await page.click('button:has-text("Log in")')
    except Exception as e:
        log(f"    [{email}] GAGAL isi form: {e}")

    # Tunggu keluar dari halaman login
    try:
        await page.wait_for_url(lambda u: "login" not in u, timeout=30000)
        log(f"    [{email}] login OK")
    except Exception:
        log(f"    [{email}] belum terkonfirmasi keluar dari login (cek manual)")

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    await dismiss_cookie_dialog(page)

    content = await page.content()
    ok = not ("Sign Up Free" in content or "Log in with email" in content)
    if ok:
        await ctx.storage_state(path=str(sp))
        log(f"    [{email}] session tersimpan -> {sp.name}")
    else:
        log(f"    [{email}] LOGIN GAGAL (captcha / password salah?)")

    if keep_open:
        # Biarkan browser terbuka, kembalikan objeknya (dipakai mode war)
        return browser, ctx, page, ok
    await browser.close()
    return ok


async def login_all():
    accounts = load_accounts()
    if not accounts:
        return
    async with async_playwright() as pw:
        for i, (email, password) in enumerate(accounts, 1):
            log(f"=== LOGIN {i}/{len(accounts)}: {email} ===")
            await login_one(pw, email, password)
    log(f"[+] SELESAI login {len(accounts)} akun")


# ================== JS FIND-AND-CLICK (dipakai saat WAR) ==================

JS_WAR_CLICK = r"""
(mode) => {
    const needle = mode === 'cos' ? 'object storage' : 'lighthouse';
    const isGS = el => (el.textContent || '').trim().includes('Get Started');
    const btns = [...document.querySelectorAll('button, a')].filter(isGS);
    for (const b of btns) {
        let el = b, card = b.parentElement || b;
        for (let i = 0; i < 15 && el; i++) {
            const parent = el.parentElement;
            if (!parent) break;
            const gsCount = [...parent.querySelectorAll('button, a')]
                .filter(isGS).length;
            if (gsCount > 1) break;
            card = parent;
            el = parent;
        }
        const txt = (card.innerText || '').toLowerCase().replace(/\s+/g, ' ');
        let match = false;
        if (needle === 'lighthouse') {
            const is2c2g = /2\s*c\s*2\s*g/.test(txt) || txt.includes('2 core')
                || txt.includes('2vcpu') || txt.includes('2 vcpu')
                || txt.includes('2 vcore') || txt.includes('2-core');
            match = txt.includes('lighthouse') && is2c2g;
        } else {
            match = txt.includes(needle);
        }
        if (match) {
            if (txt.includes('sold out') || txt.includes('售罄'))
                return 'soldout';
            const dis = b.disabled || b.getAttribute('disabled') !== null
                || b.getAttribute('aria-disabled') === 'true'
                || (b.className || '').toLowerCase().includes('disabled');
            if (dis) return 'disabled';
            b.scrollIntoView({block: 'center'});
            b.click();
            return 'clicked';
        }
    }
    return 'none';
}
"""


# ================== CLAIM PER AKUN ==================

async def claim_product(page, mode, target_time=None):
    """Alur claim 1 akun. target_time=None -> langsung gas sekarang."""
    email = page._email

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1200)
    await dismiss_cookie_dialog(page)

    # ---- STANDBY TERJADWAL: reload berkala, browser TIDAK ditutup ----
    if target_time is not None:
        target_ts = target_time.timestamp()
        if time.time() < target_ts - FINAL_REFRESH_LEAD:
            log(f"    [{email}] standby (browser tetap terbuka)...")
            last_reload = time.time()
            while time.time() < target_ts - FINAL_REFRESH_LEAD:
                if time.time() - last_reload > STANDBY_RELOAD_EVERY:
                    try:
                        await page.reload(wait_until="domcontentloaded")
                        await dismiss_cookie_dialog(page)
                    except Exception:
                        pass
                    last_reload = time.time()
                await asyncio.sleep(0.25)
        # ---- Refresh terakhir H-8 dtk ----
        try:
            log(f"    [{email}] refresh terakhir (H-{FINAL_REFRESH_LEAD}s)...")
            await page.reload(wait_until="domcontentloaded")
            await dismiss_cookie_dialog(page)
        except Exception:
            pass
        while time.time() < target_ts:
            await asyncio.sleep(0.02)
        log(f"    [{email}] >>> JAM TARGET! REFRESH + GAS! <<<")

    # ---- WAR: refresh + polling klik Get Started tiap 50ms ----
    needle = "cos" if mode == "cos" else "lighthouse"
    clicked = False
    try:
        await page.reload(wait_until="commit")
    except Exception:
        pass
    deadline = time.time() + CLAIM_WINDOW
    last_reload = 0.0
    sold_out_count = 0
    while time.time() < deadline and not clicked:
        try:
            res = await page.evaluate(JS_WAR_CLICK, mode)
            if res == "clicked":
                log(f"    [{email}] GET STARTED DIKLIK!")
                try:
                    await page.wait_for_selector(
                        'button:has-text("Buy Now"), button:has-text("立即购买")',
                        timeout=1500)
                    clicked = True
                    break
                except Exception:
                    log(f"    [{email}] dialog belum muncul, klik ulang...")
                    await asyncio.sleep(0.4)
            if res in ("soldout", "disabled") and time.time() - last_reload > 3:
                sold_out_count += 1
                if sold_out_count <= 5:
                    log(f"    [{email}] SOLD OUT/DISABLED -> reload cari stok #{sold_out_count}")
                try:
                    await page.reload(wait_until="domcontentloaded")
                    await dismiss_cookie_dialog(page)
                except Exception:
                    pass
                last_reload = time.time()
        except Exception:
            pass
        await asyncio.sleep(0.05)

    # ---- Fallback: pencarian kartu + klik satu-per-satu ----
    if not clicked:
        try:
            await page.wait_for_selector('button:has-text("Get Started")',
                                         timeout=8000)
        except Exception:
            pass
        for round_ in range(3):
            if clicked:
                break
            try:
                n = await page.evaluate(r"""
                    (needle) => {
                        window.__gs = [];
                        const isGS = el => (el.textContent || '').trim()
                            .includes('Get Started');
                        const btns = [...document.querySelectorAll('button, a')]
                            .filter(isGS);
                        for (const b of btns) {
                            let el = b, card = b.parentElement || b;
                            for (let i = 0; i < 15 && el; i++) {
                                const parent = el.parentElement;
                                if (!parent) break;
                                const gsCount = [...parent.querySelectorAll(
                                    'button, a')].filter(isGS).length;
                                if (gsCount > 1) break;
                                card = parent;
                                el = parent;
                            }
                            const txt = (card.innerText || '').toLowerCase()
                                .replace(/\s+/g, ' ');
                            if (needle === 'lighthouse') {
                                const is2c2g = /2\s*c\s*2\s*g/.test(txt)
                                    || txt.includes('2 core')
                                    || txt.includes('2vcpu')
                                    || txt.includes('2 vcpu')
                                    || txt.includes('2 vcore')
                                    || txt.includes('2-core');
                                if (txt.includes('lighthouse') && is2c2g)
                                    window.__gs.push(b);
                            } else if (txt.includes('object storage')) {
                                window.__gs.push(b);
                            }
                        }
                        return window.__gs.length;
                    }
                """, needle)
            except Exception:
                n = 0
            if n == 0:
                await page.wait_for_timeout(1200)
                continue
            for idx in range(n):
                try:
                    await page.evaluate(
                        """(idx) => { const b = window.__gs[idx];
                           b.scrollIntoView({block:'center'}); b.click(); }""",
                        idx)
                except Exception:
                    break
                try:
                    await page.wait_for_selector(
                        'button:has-text("Buy Now"), button:has-text("立即购买")',
                        timeout=4000)
                    clicked = True
                    break
                except Exception:
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
                    await page.wait_for_timeout(800)
            if clicked:
                break
            await page.wait_for_timeout(1200)

    if not clicked:
        log(f"    [{email}] [!] Get Started tidak ditemukan!")
        try:
            await page.screenshot(
                path=str(BASE_DIR / f"debug_{email.split('@')[0]}_{mode}.png"),
                full_page=True)
        except Exception:
            pass
        return False

    # ---- BUY NOW (secepat mungkin, JS instan dulu) ----
    try:
        await page.wait_for_selector(
            'button:has-text("Buy Now"), button:has-text("立即购买")',
            timeout=8000)
    except Exception:
        log(f"    [{email}] dialog Buy Now tidak muncul!")
        return False
    await page.wait_for_timeout(250)

    buy_now_ok = False
    try:
        buy_now_ok = await page.evaluate(
            """() => { const b = [...document.querySelectorAll('button')]
                       .find(x => /buy now|立即购买/i.test(x.textContent || ''));
                 if (b) { b.click(); return true; } return false; }""")
    except Exception:
        buy_now_ok = False
    if not buy_now_ok:
        buy_now_ok = await try_click(page, [
            'button:has-text("Buy Now")', 'button:has-text("立即购买")',
        ], "Buy Now", timeout=1500)
    if buy_now_ok:
        log(f"    [{email}] >>> BUY NOW TERKLIK = SUKSES! <<<")

    # ---- PAY NOW + CONFIRM (best-effort) ----
    await page.wait_for_timeout(1200)
    await dismiss_busy_popup(page)
    try:
        await page.wait_for_url(
            lambda u: ("intlprepay" in u.lower()) or ("order" in u.lower()),
            timeout=8000)
        log(f"    [{email}] di halaman order")
    except Exception:
        pass
    await try_click(page, [
        'button:has-text("立即支付")', 'button:has-text("Pay Now")',
    ], "Pay Now")
    await page.wait_for_timeout(1200)
    await dismiss_busy_popup(page)
    await try_click(page, [
        'button:has-text("确认支付")', 'button:has-text("Confirm")',
    ], "Confirm Payment")

    await page.wait_for_timeout(2500)
    try:
        await page.screenshot(
            path=str(BASE_DIR / f"claim_{email.split('@')[0]}_{mode}.png"),
            full_page=True)
    except Exception:
        pass
    return buy_now_ok


async def war_worker(pw, email, password, mode, target_time):
    """1 akun = 1 browser terpisah. Dipakai untuk mode --test / --retry-now
    (target_time=None, gas langsung). Mode WAR penuh memakai alur open_standby
    + gas di main() supaya browser standby tidak ditutup sama sekali."""
    sp = session_path(email)

    browser = await pw.chromium.launch(headless=HEADLESS)
    ctx = await browser.new_context(
        storage_state=str(sp) if sp.exists() else None)
    page = await ctx.new_page()
    page._email = email

    # Pastikan login valid; kalau session kosong/expired -> login di browser ini
    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await dismiss_cookie_dialog(page)
    content = await page.content()
    if "Sign Up Free" in content or "Log in with email" in content:
        log(f"    [{email}] session belum ada/expired -> login...")
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        await dismiss_cookie_dialog(page)
        try:
            await page.fill('input[type="text"], input[placeholder*="mail" i]',
                            email)
            await page.fill('input[type="password"]', password)
            await page.click('button:has-text("Log in")')
            await page.wait_for_url(lambda u: "login" not in u, timeout=30000)
        except Exception as e:
            log(f"    [{email}] login otomatis gagal: {e}")
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await dismiss_cookie_dialog(page)
        content = await page.content()
        if not ("Sign Up Free" in content or "Log in with email" in content):
            await ctx.storage_state(path=str(sp))
            log(f"    [{email}] session baru tersimpan")
        else:
            log(f"    [{email}] LOGIN GAGAL — akun ini dilewati")
            await page.screenshot(
                path=str(BASE_DIR / f"loginfail_{email.split('@')[0]}.png"),
                full_page=True)
            return False

    success = False
    for attempt in range(1, 4):
        log(f"    [{email}] === PERCOBAAN {attempt} ===")
        try:
            ok = await claim_product(page, mode, target_time)
        except Exception as e:
            log(f"    [{email}] ERROR: {type(e).__name__}: {e}")
            ok = False
        if ok:
            success = True
            log(f"    [{email}] [✓] SUKSES (Buy Now terklik)")
            break
        if target_time is not None:
            break  # jangan retry menabrak jadwal
        await page.wait_for_timeout(1500)

    # Browser DIBIARKAN TERBUKA (tidak close) sesuai permintaan
    log(f"    [{email}] selesai. Browser dibiarkan terbuka "
        f"{KEEP_OPEN_AFTER//60} menit (standby).")
    try:
        await asyncio.sleep(KEEP_OPEN_AFTER)
    except Exception:
        pass
    return success


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "--login":
        await login_all()
        return

    if mode == "--status":
        accounts = load_accounts()
        for email, _ in accounts:
            sp = session_path(email)
            umur = ""
            if sp.exists():
                age = time.time() - sp.stat().st_mtime
                umur = f"(session {int(age//3600)} jam lalu)"
            print(f"  {email}: {'OK ' + umur if sp.exists() else 'BELUM ADA SESSION'}")
        return

    if mode == "--test":
        log("[*] MODE TEST: latihan claim COS, langsung gas semua akun")
        accounts = load_accounts()
        if not accounts:
            return
        async with async_playwright() as pw:
            tasks = [war_worker(pw, e, p, "cos", None) for e, p in accounts]
            res = await asyncio.gather(*tasks, return_exceptions=True)
        _lapor(accounts, res)
        return

    if mode == "--retry-now":
        log("[*] MODE RETRY: gas 2C2G langsung tanpa nunggu jadwal")
        accounts = load_accounts()
        if not accounts:
            return
        async with async_playwright() as pw:
            tasks = [war_worker(pw, e, p, "lighthouse", None)
                     for e, p in accounts]
            res = await asyncio.gather(*tasks, return_exceptions=True)
        _lapor(accounts, res)
        return

    # ===== MODE WAR PENUH =====
    accounts = load_accounts()
    if not accounts:
        return
    now = datetime.now()
    login_t = now.replace(hour=LOGIN_HOUR, minute=LOGIN_MINUTE,
                          second=0, microsecond=0)
    target_t = now.replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE,
                           second=0, microsecond=0)
    if target_t <= now:
        target_t += timedelta(days=1)
        login_t += timedelta(days=1)

    log("=" * 55)
    log(f"  WAR MODE: login {login_t.strftime('%H:%M')} -> "
        f"standby -> GAS {target_t.strftime('%H:%M:%S')}")
    log(f"  {len(accounts)} akun, 1 akun = 1 browser, tanpa close")
    log("=" * 55)

    async with async_playwright() as pw:
        # 1) Tunggu jam login 22:40
        while datetime.now() < login_t:
            sisa = (login_t - datetime.now()).total_seconds()
            if int(sisa) % 60 == 0:
                log(f"    menunggu jam login... {int(sisa)//60} menit lagi")
                await asyncio.sleep(2)
            else:
                await asyncio.sleep(1)

        # 2) Login semua akun 22:40 (paralel terbatas, 1 akun 1 browser)
        log(f"[+] JAM {login_t.strftime('%H:%M')} -> LOGIN SEMUA AKUN")
        sem = asyncio.Semaphore(4)  # max 4 login bersamaan biar stabil

        async def login_task(e, pwd):
            async with sem:
                await login_one(pw, e, pwd)

        await asyncio.gather(*[login_task(e, p) for e, p in accounts])

        # 3) Buka browser semua akun dengan session baru -> STANDBY TERBUKA
        log("[+] Buka browser standby (tidak ditutup sampai WAR selesai)")
        open_browsers = {}

        async def open_standby(e, pwd):
            sp = session_path(e)
            if not sp.exists():
                log(f"    [{e}] session tidak ada setelah login, skip standby")
                return
            browser = await pw.chromium.launch(headless=HEADLESS)
            ctx = await browser.new_context(storage_state=str(sp))
            page = await ctx.new_page()
            page._email = e
            open_browsers[e] = (browser, ctx, page)
            await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            await dismiss_cookie_dialog(page)
            log(f"    [{e}] STANDBY terbuka di FreeTier")

        await asyncio.gather(*[open_standby(e, p) for e, p in accounts])

        # 4) Tunggu H-8 detik -> refresh terakhir -> 23:00:00 GAS paralel
        while time.time() < target_t.timestamp() - FINAL_REFRESH_LEAD:
            await asyncio.sleep(0.3)
        log(f"[+] H-{FINAL_REFRESH_LEAD}s -> refresh terakhir semua browser")

        async def final_refresh(e):
            bctx = open_browsers.get(e)
            if not bctx:
                return
            _, _, page = bctx
            try:
                await page.reload(wait_until="domcontentloaded")
                await dismiss_cookie_dialog(page)
                log(f"    [{e}] refresh final OK")
            except Exception as ex:
                log(f"    [{e}] refresh final error: {ex}")

        await asyncio.gather(*[final_refresh(e) for e in open_browsers])

        while time.time() < target_t.timestamp():
            await asyncio.sleep(0.02)
        log(f">>> JAM {target_t.strftime('%H:%M:%S')}! GAS SEMUA AKUN! <<<")

        # 5) Klik Get Started + Buy Now paralel di semua browser yang sama
        async def gas(e):
            bctx = open_browsers.get(e)
            if not bctx:
                return False
            _, _, page = bctx
            try:
                return await claim_product(page, "lighthouse", None)
            except Exception as ex:
                log(f"    [{e}] gas error: {ex}")
                return False

        results = await asyncio.gather(
            *[gas(e) for e, _ in accounts], return_exceptions=True)

        # Browser dibiarkan terbuka — TIDAK ADA browser.close() di sini.
        log("[+] WAR selesai. Semua browser dibiarkan TERBUKA (standby).")
        log("[+] Tekan Ctrl+C di sini kalau mau tutup semua browser manual.")

        try:
            await asyncio.sleep(KEEP_OPEN_AFTER)
        except KeyboardInterrupt:
            pass

    _lapor(accounts, results)


def _lapor(accounts, results):
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


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Dihentikan. Browser mungkin masih terbuka — tutup manual jika perlu.")
