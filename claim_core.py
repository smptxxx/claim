# ============================================================
#  TENCENT AUTO CLAIM - CORE ENGINE (v3)
#  Dipakai oleh war_claim.py (CLI) dan tg_bot.py (Telegram).
#  Semua state browser & job disimpan di sini supaya 1 sumber
#  kebenaran -> minim bug (tidak ada duplikasi logika).
# ============================================================

import asyncio
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

# ================== KONFIGURASI ==================
BASE_DIR = Path(__file__).parent
ACCOUNTS_FILE = BASE_DIR / "accounts.txt"
SESSION_DIR = BASE_DIR / "sessions"

FREE_TIER_URL = "https://www.tencentcloud.com/act/pro/FreeTier"
LOGIN_URL = "https://www.tencentcloud.com/account/login"

LOGIN_HOUR = 22          # login semua akun jam 22:40
LOGIN_MINUTE = 40
CLAIM_HOUR = 23          # gas claim jam 23:00:00
CLAIM_MINUTE = 0
FINAL_REFRESH_LEAD = 8   # refresh terakhir H-8 detik
STANDBY_RELOAD_EVERY = 240   # standby: reload tiap 4 menit biar session hangat
CLAIM_WINDOW = 120       # detik polling setelah jam target
HEADLESS = False         # WAJIB False: browser harus kelihatan & tidak ditutup
KEEP_OPEN_AFTER = 900    # browser dibiarkan terbuka 15 menit setelah claim
LOGIN_PARALLEL = 4       # max login bersamaan
# =================================================

SESSION_DIR.mkdir(exist_ok=True)

# Log tail global (dibaca oleh bot untuk /log)
LOG_LINES = []
LOG_MAX = 800


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG_LINES.append(line)
    if len(LOG_LINES) > LOG_MAX:
        del LOG_LINES[: len(LOG_LINES) - LOG_MAX]


def tail_log(n=30):
    return "\n".join(LOG_LINES[-n:])


# ================== AKUN ==================

def load_accounts():
    """Baca accounts.txt -> OrderedDict {email: password} (urut, unik)."""
    accounts = OrderedDict()
    if ACCOUNTS_FILE.exists():
        for line in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                log(f"[!] Baris tidak valid (skip): {line[:40]}")
                continue
            email, _, password = line.partition(":")
            accounts[email.strip()] = password.strip()
    return accounts


def save_accounts(accounts):
    """Simpan OrderedDict ke accounts.txt."""
    lines = [f"{e}:{p}" for e, p in accounts.items()]
    ACCOUNTS_FILE.write_text("\n".join(lines) + ("\n" if lines else ""),
                             encoding="utf-8")


def add_account(email, password):
    accounts = load_accounts()
    if email in accounts:
        accounts[email] = password  # update password
        save_accounts(accounts)
        return f"updated: {email}"
    accounts[email] = password
    save_accounts(accounts)
    return f"added: {email}"


def del_account(email):
    accounts = load_accounts()
    if email not in accounts:
        return False
    del accounts[email]
    save_accounts(accounts)
    sp = session_path(email)
    if sp.exists():
        try:
            sp.unlink()
        except Exception:
            pass
    return True


def session_path(email):
    safe = email.replace("@", "_at_").replace(".", "_")
    return SESSION_DIR / f"{safe}.json"


def accounts_status():
    """Status ringkas semua akun (teks untuk CLI & bot)."""
    accounts = load_accounts()
    if not accounts:
        return "Belum ada akun. Tambah via /add email:password"
    out = [f"Total {len(accounts)} akun:"]
    for email in accounts:
        sp = session_path(email)
        if sp.exists():
            age = time.time() - sp.stat().st_mtime
            umur = int(age // 3600)
            out.append(f"  [OK] {email} — session {umur} jam lalu")
        else:
            out.append(f"  [--] {email} — BELUM login")
    return "\n".join(out)


# ================== BROWSER HELPERS ==================

async def dismiss_cookie_dialog(page):
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

async def login_one(pw, email, password):
    """Login 1 akun di browser sendiri, simpan session. Return (ok, pesan)."""
    sp = session_path(email)
    browser = await pw.chromium.launch(headless=HEADLESS)
    ctx = await browser.new_context()
    page = await ctx.new_page()
    page._email = email
    try:
        log(f"    [{email}] buka halaman login...")
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1200)
        await dismiss_cookie_dialog(page)
        try:
            await page.fill('input[type="text"], input[placeholder*="mail" i]',
                            email)
            await page.fill('input[type="password"]', password)
            await page.click('button:has-text("Log in")')
        except Exception as e:
            log(f"    [{email}] GAGAL isi form: {e}")
        try:
            await page.wait_for_url(lambda u: "login" not in u, timeout=30000)
        except Exception:
            pass
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        await dismiss_cookie_dialog(page)
        content = await page.content()
        ok = not ("Sign Up Free" in content or "Log in with email" in content)
        if ok:
            await ctx.storage_state(path=str(sp))
            log(f"    [{email}] session tersimpan -> {sp.name}")
            return True, "login OK, session tersimpan"
        log(f"    [{email}] LOGIN GAGAL (captcha / password salah?)")
        await page.screenshot(
            path=str(BASE_DIR / f"loginfail_{email.split('@')[0]}.png"),
            full_page=True)
        return False, "LOGIN GAGAL — cek screenshot loginfail_*.png (captcha?)"
    except Exception as e:
        return False, f"error: {type(e).__name__}: {e}"
    finally:
        # Browser login BOLEH ditutup (session sudah tersimpan di json)
        try:
            await browser.close()
        except Exception:
            pass


# ================== CLAIM (JS WAR) ==================

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

JS_COLLECT_CARDS = r"""
(needle) => {
    window.__gs = [];
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
        if (needle === 'lighthouse') {
            const is2c2g = /2\s*c\s*2\s*g/.test(txt) || txt.includes('2 core')
                || txt.includes('2vcpu') || txt.includes('2 vcpu')
                || txt.includes('2 vcore') || txt.includes('2-core');
            if (txt.includes('lighthouse') && is2c2g) window.__gs.push(b);
        } else if (txt.includes('object storage')) {
            window.__gs.push(b);
        }
    }
    return window.__gs.length;
}
"""

JS_CLICK_CARD = ("(idx) => { const b = window.__gs[idx]; "
                 "b.scrollIntoView({block:'center'}); b.click(); }")


async def claim_product(page, mode, target_time=None):
    """Alur claim 1 akun. target_time=None -> langsung gas sekarang.
    Return True kalau Get Started + Buy Now terklik."""
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
        try:
            log(f"    [{email}] refresh terakhir (H-{FINAL_REFRESH_LEAD}s)...")
            await page.reload(wait_until="domcontentloaded")
            await dismiss_cookie_dialog(page)
        except Exception:
            pass
        while time.time() < target_ts:
            await asyncio.sleep(0.02)
        log(f"    [{email}] >>> JAM TARGET! REFRESH + GAS! <<<")

    # ---- WAR: polling klik Get Started tiap 50ms ----
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

    # ---- Fallback: kumpulkan kartu cocok, klik satu-per-satu ----
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
                n = await page.evaluate(JS_COLLECT_CARDS, mode)
            except Exception:
                n = 0
            if n == 0:
                await page.wait_for_timeout(1200)
                continue
            for idx in range(n):
                try:
                    await page.evaluate(JS_CLICK_CARD, idx)
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

    # ---- BUY NOW (JS instan dulu) ----
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


# ================== JOB MANAGER (CLI & Telegram) ==================

class JobManager:
    """Kelola 1 job besar (war/test/gas) + browser standby per akun."""

    def __init__(self):
        self.pw = None
        self.job_task = None
        self.job_name = None       # "WAR", "TEST COS", "GAS 2C2G"
        self.job_start = None
        self.stopping = False
        self.results = {}          # email -> "BERHASIL"/"GAGAL"/"ERROR: ..."
        self.standby_pages = {}    # email -> page (browser standby terbuka)
        self.lock = asyncio.Lock()

    @property
    def busy(self):
        return self.job_task is not None and not self.job_task.done()

    def job_desc(self):
        if not self.job_name:
            return "idle"
        sisa = ""
        if self.job_name == "WAR" and WAR_STATE["target"] is not None:
            sisa = f" — gas jam {WAR_STATE['target'].strftime('%H:%M:%S')}"
        return f"{self.job_name} (jalan {self._elapsed()}){sisa}"

    def _elapsed(self):
        d = int(time.time() - self.job_start)
        return f"{d//60}m{d%60:02d}s"

    async def ensure_pw(self):
        if self.pw is None:
            self.pw = await async_playwright().start()
        return self.pw

    async def shutdown(self):
        """Tutup playwright saat bot mati (browser ikut tertutup rapi)."""
        if self.pw is not None:
            try:
                await self.pw.stop()
            except Exception:
                pass
            self.pw = None

    # ---------- LOGIN ALL ----------

    async def login_all(self):
        accounts = load_accounts()
        if not accounts:
            return "Belum ada akun. /add dulu."
        pw = await self.ensure_pw()
        sem = asyncio.Semaphore(LOGIN_PARALLEL)
        hasil = {}

        async def one(e, p):
            async with sem:
                ok, msg = await login_one(pw, e, p)
                hasil[e] = msg

        log(f"[LOGIN-ALL] {len(accounts)} akun (max {LOGIN_PARALLEL} paralel)")
        await asyncio.gather(*[one(e, p) for e, p in accounts.items()])
        ok_n = sum(1 for m in hasil.values() if m.startswith("login OK"))
        baris = [f"Login selesai: {ok_n}/{len(accounts)} sukses"]
        for e, m in hasil.items():
            tanda = "✓" if m.startswith("login OK") else "✗"
            baris.append(f"  {tanda} {e} — {m}")
        return "\n".join(baris)

    # ---------- GAS SEMUA AKUN (mode instant: test/gas) ----------

    async def _gas_worker(self, pw, email, password, mode):
        """1 akun = 1 browser. Session invalid -> login dulu di browser ini."""
        sp = session_path(email)
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(
            storage_state=str(sp) if sp.exists() else None)
        page = await ctx.new_page()
        page._email = email
        try:
            await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await dismiss_cookie_dialog(page)
            content = await page.content()
            if "Sign Up Free" in content or "Log in with email" in content:
                log(f"    [{email}] session invalid -> login ulang...")
                ok, msg = await login_one(pw, email, password)
                if not ok:
                    self.results[email] = f"✗ {msg}"
                    return False
                # context baru dengan session baru
                await ctx.close()
                try:
                    await browser.close()
                except Exception:
                    pass
                browser = await pw.chromium.launch(headless=HEADLESS)
                ctx = await browser.new_context(storage_state=str(sp))
                page = await ctx.new_page()
                page._email = email

            success = False
            for attempt in range(1, 4):
                if self.stopping:
                    self.results[email] = "⏹ dibatalkan"
                    return False
                log(f"    [{email}] === PERCOBAAN {attempt} ===")
                try:
                    ok = await claim_product(page, mode)
                except Exception as e:
                    log(f"    [{email}] ERROR: {type(e).__name__}: {e}")
                    ok = False
                if ok:
                    success = True
                    break
                await page.wait_for_timeout(1500)
            self.results[email] = "✓ BERHASIL" if success else "✗ GAGAL"
            return success
        except Exception as e:
            self.results[email] = f"✗ ERROR: {type(e).__name__}: {e}"
            return False
        finally:
            # Browser DIBIARKAN TERBUKA (tidak close) sesuai strategi
            log(f"    [{email}] browser dibiarkan terbuka (standby).")
            try:
                self.standby_pages[email] = page
            except Exception:
                pass

    async def _run_instant(self, mode):
        """Gas semua akun paralel sekarang (mode cos/lighthouse)."""
        accounts = load_accounts()
        if not accounts:
            return "Belum ada akun. /add dulu."
        pw = await self.ensure_pw()
        self.results = {}
        log(f"[GAS] mode={mode} akun={len(accounts)} paralel")
        tasks = [self._gas_worker(pw, e, p, mode) for e, p in accounts.items()]
        await asyncio.gather(*tasks, return_exceptions=True)
        ok_n = sum(1 for v in self.results.values() if v.startswith("✓"))
        baris = [f"Selesai ({mode}): {ok_n}/{len(accounts)} sukses"]
        for e, v in self.results.items():
            baris.append(f"  {v} {e}")
        return "\n".join(baris)

    async def start_instant(self, mode):
        label = "TEST COS (latihan)" if mode == "cos" else "GAS 2C2G"
        if self.busy:
            return f"⛔ Masih ada job jalan: {self.job_desc()}. /stop dulu."
        self.stopping = False
        self.job_name = label
        self.job_start = time.time()
        self.job_task = asyncio.create_task(self._run_instant(mode))
        return (f"🚀 {label} DIMULAI untuk semua akun!\n"
                f"Lihat progres: /status, /log\nAkhiri: /stop")

    # ---------- WAR TERJADWAL (login 22:40 -> standby -> gas 23:00) ----------

    async def _run_war(self):
        accounts = load_accounts()
        if not accounts:
            self.results = {}
            log("[WAR] dibatalkan: tidak ada akun")
            return
        now = datetime.now()
        login_t = now.replace(hour=LOGIN_HOUR, minute=LOGIN_MINUTE,
                              second=0, microsecond=0)
        target_t = now.replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE,
                               second=0, microsecond=0)
        if target_t <= now:
            target_t += timedelta(days=1)
            login_t += timedelta(days=1)
        WAR_STATE["target"] = target_t

        log("=" * 55)
        log(f"  WAR: login {login_t.strftime('%H:%M')} -> standby -> "
            f"GAS {target_t.strftime('%H:%M:%S')}")
        log(f"  {len(accounts)} akun, 1 akun = 1 browser, tanpa close")
        log("=" * 55)

        pw = await self.ensure_pw()

        # 1) Tunggu jam login 22:40
        while datetime.now() < login_t and not self.stopping:
            await asyncio.sleep(1)
        if self.stopping:
            log("[WAR] dihentikan sebelum login")
            return

        # 2) Login semua akun (paralel terbatas)
        log(f"[+] JAM {login_t.strftime('%H:%M')} -> LOGIN SEMUA AKUN")
        sem = asyncio.Semaphore(LOGIN_PARALLEL)
        hasil = {}

        async def ltask(e, p):
            async with sem:
                ok, msg = await login_one(pw, e, p)
                hasil[e] = (ok, msg)

        await asyncio.gather(*[ltask(e, p) for e, p in accounts.items()])

        # 3) Buka browser standby TERBUKA sampai jam gas
        log("[+] Buka browser standby (tidak ditutup)")
        self.standby_pages = {}

        async def open_standby(e):
            if self.stopping:
                return
            sp = session_path(e)
            if not sp.exists():
                log(f"    [{e}] login gagal tadi, skip standby")
                return
            try:
                browser = await pw.chromium.launch(headless=HEADLESS)
                ctx = await browser.new_context(storage_state=str(sp))
                page = await ctx.new_page()
                page._email = e
                self.standby_pages[e] = page
                await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
                await dismiss_cookie_dialog(page)
                log(f"    [{e}] STANDBY terbuka di FreeTier")
            except Exception as ex:
                log(f"    [{e}] standby error: {ex}")

        await asyncio.gather(*[open_standby(e) for e in accounts])

        # 4) Tunggu H-8dtk -> refresh final -> tepat 23:00:00 GAS
        while (time.time() < target_t.timestamp() - FINAL_REFRESH_LEAD
               and not self.stopping):
            await asyncio.sleep(0.3)
        if self.stopping:
            log("[WAR] dihentikan saat standby")
            return
        log(f"[+] H-{FINAL_REFRESH_LEAD}s -> refresh final semua browser")

        async def refresh(e):
            page = self.standby_pages.get(e)
            if not page:
                return
            try:
                await page.reload(wait_until="domcontentloaded")
                await dismiss_cookie_dialog(page)
                log(f"    [{e}] refresh final OK")
            except Exception as ex:
                log(f"    [{e}] refresh final error: {ex}")

        await asyncio.gather(*[refresh(e) for e in list(self.standby_pages)])

        while time.time() < target_t.timestamp() and not self.stopping:
            await asyncio.sleep(0.02)
        if self.stopping:
            log("[WAR] dihentikan tepat sebelum gas")
            return
        log(f">>> JAM {target_t.strftime('%H:%M:%S')}! GAS SEMUA AKUN! <<<")

        # 5) Gas paralel di browser standby yang SAMA (tanpa buka baru)
        self.results = {}

        async def gas(e):
            page = self.standby_pages.get(e)
            if not page:
                self.results[e] = "✗ tidak ada browser standby"
                return
            try:
                ok = await claim_product(page, "lighthouse")
                self.results[e] = "✓ BERHASIL" if ok else "✗ GAGAL"
            except Exception as ex:
                self.results[e] = f"✗ ERROR: {type(ex).__name__}: {ex}"

        await asyncio.gather(*[gas(e) for e in accounts])
        WAR_STATE["target"] = None
        log("[+] WAR selesai. Semua browser dibiarkan TERBUKA.")

    async def start_war(self):
        if self.busy:
            return f"⛔ Masih ada job jalan: {self.job_desc()}. /stop dulu."
        self.stopping = False
        self.job_name = "WAR"
        self.job_start = time.time()
        self.job_task = asyncio.create_task(self._run_war())
        now = datetime.now()
        target = now.replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE, second=0,
                             microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (f"🚀 WAR TERJADWAL AKTIF!\n"
                f"  Login : {LOGIN_HOUR:02d}:{LOGIN_MINUTE:02d}\n"
                f"  GAS   : {target.strftime('%d %b %H:%M:%S')}\n"
                f"Cek: /status • /log • Batal: /stop")

    # ---------- STOP ----------

    async def stop(self):
        if not self.busy:
            return "Tidak ada job yang jalan."
        self.stopping = True
        task = self.job_task
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=30)
        except Exception:
            task.cancel()
            try:
                await task
            except Exception:
                pass
        self.job_name = None
        self.job_task = None
        return "⏹ Job dihentikan. Browser standby DIBIARKAN TERBUKA (tutup manual kalau mau)."


WAR_STATE = {"target": None}
JM = JobManager()
