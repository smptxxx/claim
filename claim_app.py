# ============================================================
#  TENCENT AUTO CLAIM - WINDOWS APP (GUI)
#  Fitur:
#   - Add / hapus akun (tersimpan di accounts.txt)
#   - Login otomatis semua akun (session tersimpan)
#   - Latihan claim COS (kapan saja)
#   - GAS claim 2C2G Lighthouse SEKARANG
#   - WAR terjadwal 23:00 (login 22:40, standby 22:55, gas 23:00)
#  Jalankan: python claim_app.py  atau  ClaimApp.exe
# ============================================================
import asyncio
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
from pathlib import Path

# ==== FIX Playwright di .exe (PyInstaller) ====
# Browser Chromium TIDAK dibundle di exe — arahkan ke folder
# ms-playwright beneran (yang sudah di-download via playwright install)
if getattr(sys, "frozen", False):
    _pw_dir = Path(os.path.expanduser("~")) / "AppData" / "Local" \
        / "ms-playwright"
    if _pw_dir.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_pw_dir)

from playwright.async_api import async_playwright

# ================== KONFIGURASI ==================
# FIX .exe (PyInstaller onefile): __file__ menunjuk folder TEMP yang
# kehapus saat app ditutup. Kalau frozen, pakai folder .exe-nya —
# biar accounts.txt / sessions / log nempel di folder yang benar.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
ACCOUNTS_FILE = BASE_DIR / "accounts.txt"
SESSION_DIR = BASE_DIR / "sessions"
FREE_TIER_URL = "https://www.tencentcloud.com/act/pro/FreeTier"
LOGIN_URL = "https://www.tencentcloud.com/account/login"

CLAIM_HOUR = 23
CLAIM_MINUTE = 0
PREPARE_SECONDS = 300   # browser kebuka H-5min (22:55)
RELOGIN_HOUR = 22       # login semua akun jam 22:40
RELOGIN_MINUTE = 40

SESSION_DIR.mkdir(exist_ok=True)
os.system("")  # aktifkan ANSI di console Windows

# ================== LOG HELPER ==================
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        with open(BASE_DIR / "app_events.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    return line

# ================== UTIL ==================
def load_accounts():
    if not ACCOUNTS_FILE.exists():
        return []
    accounts = []
    for line in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        email, _, password = line.partition(":")
        accounts.append((email.strip(), password.strip()))
    return accounts

def save_accounts(accounts):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        f.write("# Daftar akun Tencent Cloud - BULK\n")
        f.write("# Format: email:password (satu akun per baris)\n\n")
        for email, password in accounts:
            f.write(f"{email}:{password}\n")

def session_path(email):
    safe = email.replace("@", "_at_").replace(".", "_")
    return SESSION_DIR / f"{safe}.json"

# ================== PLAYWRIGHT HELPERS ==================
async def dismiss_cookie_dialog(page):
    try:
        for sel in ['button:has-text("Accept all optional cookies")',
                    'button:has-text("Reject all optional cookies")',
                    'button:has-text("Accept all")',
                    'button:has-text("Reject all")',
                    'button:has-text("Accept")']:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False

async def dismiss_busy_popup(page):
    try:
        busy = page.locator('text=The system is busy').first
        if await busy.is_visible(timeout=500):
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

async def try_click(page, selectors, desc, timeout=3000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.click(timeout=timeout)
            log(f"[{page._email}] {desc} OK")
            return True
        except Exception:
            continue
    log(f"[{page._email}] {desc} GAGAL")
    return False

# ================== LOGIN ==================
async def login_one(playwright, email, password):
    sp = session_path(email)
    browser = await playwright.chromium.launch(headless=False)
    ctx = await browser.new_context()
    page = await ctx.new_page()
    page._email = email

    log(f"[{email}] Membuka login...")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)
    await dismiss_cookie_dialog(page)

    try:
        await page.fill('input[type="text"], input[placeholder*="mail" i]',
                        email)
        await page.fill('input[type="password"]', password)
        await page.click('button:has-text("Log in")')
    except Exception as e:
        log(f"[{email}] Gagal isi form: {e}")

    try:
        await page.wait_for_url(lambda u: "login" not in u, timeout=30000)
    except Exception:
        pass

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    await dismiss_cookie_dialog(page)

    content = await page.content()
    if "Sign Up Free" in content or "Log in with email" in content:
        log(f"[{email}] Butuh login manual! Login di browser lalu Enter "
            f"di jendela console...")
        input(f"    [{email}] Login manual di browser, lalu Enter...")
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await dismiss_cookie_dialog(page)

    await ctx.storage_state(path=str(sp))
    log(f"[{email}] Session tersimpan")
    await browser.close()

# ================== CLAIM ENGINE ==================
async def claim_product(page, mode, target_time=None):
    """mode: 'cos' (latihan) atau 'lighthouse' (2C2G war).
    target_time: datetime target war (None = langsung gas sekarang)."""
    email = page._email

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    await dismiss_cookie_dialog(page)

    # MODE TERJADWAL: standby reload + reload terakhir H-8s
    if target_time is not None:
        target_ts = target_time.timestamp()
        if time.time() < target_ts:
            log(f"[{email}] Standby reload sampai jam target")
            last_reload = 0.0
            while time.time() < target_ts - 8:
                if time.time() - last_reload > 4:
                    try:
                        await page.reload(wait_until="domcontentloaded")
                        await page.wait_for_timeout(800)
                        await dismiss_cookie_dialog(page)
                    except Exception:
                        pass
                    last_reload = time.time()
                await asyncio.sleep(0.2)
            try:
                await page.reload(wait_until="domcontentloaded")
                await dismiss_cookie_dialog(page)
            except Exception:
                pass
            while time.time() < target_ts:
                await asyncio.sleep(0.02)
            log(f"[{email}] JAM TARGET! Refresh + GAS!")

    needle = "object storage" if mode == "cos" else "lighthouse"
    clicked = False

    if target_time is not None:
        # ===== MODE WAR: refresh cepat + polling klik 50ms =====
        try:
            await page.reload(wait_until="commit")
        except Exception:
            pass
        target_ts = target_time.timestamp()
        deadline = max(target_ts, time.time()) + 120
        last_reload = 0.0
        sold_out_count = 0
        while time.time() < deadline and not clicked:
            try:
                res = await page.evaluate(r"""(mode) => {
                    const needle = mode === 'cos' ? 'object storage'
                                                  : 'lighthouse';
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
                        let match = false;
                        if (needle === 'lighthouse') {
                            const is2c2g = /2\s*c\s*2\s*g/.test(txt)
                                || txt.includes('2 core')
                                || txt.includes('2vcpu')
                                || txt.includes('2 vcpu')
                                || txt.includes('2 vcore')
                                || txt.includes('2-core');
                            match = txt.includes('lighthouse') && is2c2g;
                        } else {
                            match = txt.includes(needle);
                        }
                        if (match) {
                            if (txt.includes('sold out')
                                || txt.includes('售罄')) return 'soldout';
                            const dis = b.disabled
                                || b.getAttribute('disabled') !== null
                                || b.getAttribute('aria-disabled') === 'true'
                                || (b.className || '').toLowerCase()
                                    .includes('disabled');
                            if (dis) return 'disabled';
                            b.scrollIntoView({block: 'center'});
                            b.click();
                            return 'clicked';
                        }
                    }
                    return 'none';
                }""", mode)
                if res == "clicked":
                    log(f"[{email}] GET STARTED DIKLIK (polling 50ms)!")
                    try:
                        await page.wait_for_selector(
                            'button:has-text("Buy Now"), '
                            'button:has-text("立即购买")',
                            timeout=1500)
                        clicked = True
                        break
                    except Exception:
                        log(f"[{email}] Dialog belum muncul, klik ulang...")
                        await asyncio.sleep(0.5)
                if res in ("soldout", "disabled") \
                        and time.time() - last_reload > 3:
                    sold_out_count += 1
                    if sold_out_count <= 5:
                        log(f"[{email}] 2C2G SOLD OUT/DISABLED — reload "
                            f"cari stok #{sold_out_count}")
                    try:
                        await page.reload(wait_until="domcontentloaded")
                        await dismiss_cookie_dialog(page)
                    except Exception:
                        pass
                    last_reload = time.time()
            except Exception:
                pass
            await asyncio.sleep(0.05)

    if not clicked:
        try:
            await page.wait_for_selector('button:has-text("Get Started")',
                                         timeout=15000)
        except Exception:
            log(f"[{email}] Get Started belum muncul (tunggu 15s)")

    for round_ in range(3):
        if clicked:
            break
        try:
            n_matches = await page.evaluate(
                r"""(needle) => {
                    window.__gsMatches = [];
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
                            if (txt.includes('lighthouse') && is2c2g) {
                                window.__gsMatches.push(b);
                            }
                        } else if (txt.includes(needle)) {
                            window.__gsMatches.push(b);
                        }
                    }
                    return window.__gsMatches.length;
                }""", needle)
        except Exception as e:
            log(f"[{email}] JS search error: {e}")
            n_matches = 0

        if n_matches == 0:
            await page.wait_for_timeout(1500)
            continue

        log(f"[{email}] {n_matches} kartu cocok, klik satu-per-satu")
        for idx in range(n_matches):
            try:
                await page.evaluate(
                    """(idx) => {
                        const b = window.__gsMatches[idx];
                        b.scrollIntoView({block: 'center'});
                        b.click();
                    }""", idx)
                log(f"[{email}] Get Started #{idx + 1} diklik")
            except Exception:
                break
            try:
                await page.wait_for_selector(
                    'button:has-text("Buy Now"), button:has-text("立即购买")',
                    timeout=5000)
                clicked = True
                break
            except Exception:
                log(f"[{email}] Kartu #{idx + 1} salah, coba berikutnya")
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                await page.wait_for_timeout(1000)
        if clicked:
            break
        await page.wait_for_timeout(1500)

    if not clicked:
        log(f"[{email}] Get Started tidak ditemukan!")
        try:
            await page.screenshot(
                path=str(BASE_DIR / f"debug_{email.split('@')[0]}_{mode}.png"),
                full_page=True)
        except Exception:
            pass
        return False

    # ===== BUY NOW =====
    try:
        await page.wait_for_selector(
            'button:has-text("Buy Now"), button:has-text("立即购买")',
            timeout=10000)
    except Exception:
        log(f"[{email}] Dialog Buy Now tidak muncul!")
        return False
    await page.wait_for_timeout(300)

    buy_now_ok = False
    try:
        js_ok = await page.evaluate(
            """() => {
                const b = [...document.querySelectorAll('button')]
                    .find(x => /buy now|立即购买/i.test(x.textContent || ''));
                if (b) { b.click(); return true; }
                return false;
            }""")
        if js_ok:
            buy_now_ok = True
            log(f"[{email}] BUY NOW diklik (JS instan)")
    except Exception:
        pass
    if not buy_now_ok:
        buy_now_ok = await try_click(page, [
            'button:has-text("Buy Now")',
            'button:has-text("立即购买")',
        ], "Buy Now", timeout=1500)

    if buy_now_ok:
        log(f"[{email}] BUY NOW TERKLIK = SUKSES!")

    await page.wait_for_timeout(1500)
    await dismiss_busy_popup(page)
    if not buy_now_ok:
        return False

    # ===== PAY NOW (best-effort) =====
    try:
        await page.wait_for_url(
            lambda u: ("intlprepay" in u.lower()) or ("order" in u.lower()),
            timeout=10000)
    except Exception:
        log(f"[{email}] Tidak pindah ke halaman order")

    await try_click(page, [
        'button:has-text("立即支付")',
        'button:has-text("Pay Now")',
    ], "Pay Now")
    await page.wait_for_timeout(1500)
    await dismiss_busy_popup(page)

    await try_click(page, [
        'button:has-text("确认支付")',
        'button:has-text("Confirm")',
    ], "Confirm Payment")

    await page.wait_for_timeout(3000)
    try:
        await page.screenshot(
            path=str(BASE_DIR / f"claim_{email.split('@')[0]}_{mode}.png"),
            full_page=True)
    except Exception:
        pass
    return True

async def claim_and_verify(ctx, email, password, mode, target_time=None):
    sp = session_path(email)
    if not sp.exists():
        log(f"[{email}] Belum ada session! Login dulu.")
        return False

    browser = await ctx.chromium.launch(headless=False)
    context = await browser.new_context(storage_state=str(sp))
    page = await context.new_page()
    page._email = email

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await dismiss_cookie_dialog(page)
    content = await page.content()
    if "Sign Up Free" in content or "Log in with email" in content:
        log(f"[{email}] Session expired, login ulang...")
        await context.close()
        await browser.close()
        async with async_playwright() as p2:
            await login_one(p2, email, password)
        browser = await ctx.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=str(sp))
        page = await context.new_page()
        page._email = email
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await dismiss_cookie_dialog(page)

    success = False
    for attempt in range(1, 4):
        log(f"[{email}] Percobaan {attempt}")
        try:
            ok = await claim_product(page, mode, target_time)
        except Exception as e:
            log(f"[{email}] ERROR percobaan {attempt}: "
                f"{type(e).__name__}: {e}")
            ok = False
        if ok:
            log(f"[{email}] CLAIM BERHASIL! (Buy Now terklik)")
            success = True
            break
        try:
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    # Browser DIBIARKAN TERBUKA — bukti claim & bisa dicek manual
    try:
        await page.wait_for_timeout(15000)
    except Exception:
        pass
    return success

async def run_claim_all(mode, target_time=None, progress_cb=None):
    accounts = load_accounts()
    if not accounts:
        log("Tidak ada akun! Add akun dulu.")
        return
    log(f"Claim {len(accounts)} akun paralel ({mode})")
    async with async_playwright() as p:
        tasks = [claim_and_verify(p, email, password, mode, target_time)
                 for email, password in accounts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        log(f"SELESAI: {ok}/{len(accounts)} akun sukses ({mode})")
        if progress_cb:
            progress_cb(ok, len(accounts))

async def relogin_all():
    accounts = load_accounts()
    if not accounts:
        log("Tidak ada akun! Add akun dulu.")
        return
    log(f"Login {len(accounts)} akun...")
    async with async_playwright() as p:
        for i, (email, password) in enumerate(accounts, 1):
            log(f"Login {i}/{len(accounts)}: {email}")
            await login_one(p, email, password)
    log(f"SEMUA AKUN SELESAI LOGIN ({len(accounts)})")

# ================== WAR SCHEDULER ==================
async def war_scheduler(status_cb):
    """Login 22:40 → standby 22:55 → gas 23:00."""
    accounts = load_accounts()
    if not accounts:
        log("Tidak ada akun! Add akun dulu.")
        status_cb("TIDAK ADA AKUN")
        return
    now = datetime.now()
    relogin_t = now.replace(hour=RELOGIN_HOUR, minute=RELOGIN_MINUTE,
                            second=0, microsecond=0)
    target_t = now.replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE,
                           second=0, microsecond=0)
    if target_t <= now:
        target_t += timedelta(days=1)
    # relogin hanya kalau masih JAUH dari target (> 2 jam)
    if (target_t - now).total_seconds() > 7200 and now < relogin_t:
        status_cb(f"LOGIN OTOMATIS {relogin_t.strftime('%H:%M')}")
        log(f"Login semua akun jam {relogin_t.strftime('%H:%M')}...")
        while datetime.now() < relogin_t:
            await asyncio.sleep(0.5)
        await relogin_all()
    else:
        log("Dekat jam target, skip login (session terakhir dipakai)")

    status_cb(f"STANDBY — WAR {target_t.strftime('%H:%M')}")
    await run_claim_all("lighthouse", target_time=target_t)
    status_cb("WAR SELESAI")

# ================== GUI ==================
class ClaimApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Tencent Auto Claim — WAR 23:00")
        self.root.geometry("780x620")
        self.root.configure(bg="#1e1e2e")
        self.loop = None
        self.busy = False

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10, "bold"),
                        padding=8)
        style.configure("War.TButton", foreground="white",
                        background="#e5484d")
        style.map("War.TButton",
                  background=[("active", "#ff6369")])

        # ---- Header ----
        hdr = tk.Label(root, text="⚡ TENCENT AUTO CLAIM",
                       font=("Segoe UI", 16, "bold"),
                       bg="#1e1e2e", fg="#89b4fa")
        hdr.pack(pady=(12, 2))
        self.status_lbl = tk.Label(root, text="SIAP",
                                   font=("Segoe UI", 11, "bold"),
                                   bg="#1e1e2e", fg="#a6e3a1")
        self.status_lbl.pack()

        # ---- Tombol aksi ----
        btns = tk.Frame(root, bg="#1e1e2e")
        btns.pack(pady=10)
        ttk.Button(btns, text="➕ Add Akun",
                   command=self.add_account).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="🗑 Hapus Terpilih",
                   command=self.del_account).grid(row=0, column=1, padx=4)
        ttk.Button(btns, text="🔑 Login Semua Akun",
                   command=self.do_login).grid(row=0, column=2, padx=4)
        ttk.Button(btns, text="🎓 Latihan COS",
                   command=lambda: self.do_claim("cos")).grid(
            row=0, column=3, padx=4)
        ttk.Button(btns, text="⚡ GAS 2C2G Sekarang",
                   command=lambda: self.do_claim("lighthouse")).grid(
            row=0, column=4, padx=4)
        ttk.Button(btns, text="🚀 WAR 23:00 (Otomatis)",
                   style="War.TButton",
                   command=self.do_war).grid(row=0, column=5, padx=4)

        # ---- Tabel akun ----
        cols = ("email", "session")
        self.tree = ttk.Treeview(root, columns=cols, show="headings",
                                 height=9)
        self.tree.heading("email", text="Email")
        self.tree.heading("session", text="Session")
        self.tree.column("email", width=420)
        self.tree.column("session", width=120, anchor="center")
        self.tree.pack(fill="x", padx=14, pady=6)

        # ---- Log ----
        log_frame = tk.LabelFrame(root, text=" Log Aktivitas ",
                                  bg="#1e1e2e", fg="#cdd6f4",
                                  font=("Segoe UI", 9, "bold"))
        log_frame.pack(fill="both", expand=True, padx=14, pady=(2, 12))
        self.log_txt = tk.Text(log_frame, height=12, bg="#11111b",
                               fg="#cdd6f4", font=("Consolas", 9),
                               state="disabled", wrap="word")
        self.log_txt.pack(fill="both", expand=True, padx=4, pady=4)

        self.refresh_tree()
        self.append_log("Aplikasi siap. Add akun → Login → GAS/WAR.")

    # ---------- GUI helpers ----------
    def append_log(self, msg):
        line = log(msg)
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", line + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def set_status(self, txt, color="#a6e3a1"):
        self.status_lbl.configure(text=txt, fg=color)

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for email, _ in load_accounts():
            has_sess = "✅" if session_path(email).exists() else "❌"
            self.tree.insert("", "end", values=(email, has_sess))

    def run_async(self, coro_factory, status_txt, color="#f9e2af"):
        if self.busy:
            messagebox.showwarning("Sibuk", "Ada proses jalan! Tunggu "
                                           "sampai selesai.")
            return
        self.busy = True
        self.set_status(status_txt, color)

        def worker():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(coro_factory())
            except Exception as e:
                self.append_log(f"ERROR: {type(e).__name__}: {e}")
            finally:
                self.loop.close()
                self.busy = False
                self.root.after(0, lambda: self.set_status(
                    "SIAP — proses selesai"))
                self.root.after(0, self.refresh_tree)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- Aksi ----------
    def add_account(self):
        win = tk.Toplevel(self.root)
        win.title("Add Akun")
        win.geometry("360x150")
        win.configure(bg="#1e1e2e")
        tk.Label(win, text="Email:", bg="#1e1e2e", fg="#cdd6f4").pack(
            pady=(12, 0))
        e1 = tk.Entry(win, width=40)
        e1.pack()
        tk.Label(win, text="Password:", bg="#1e1e2e", fg="#cdd6f4").pack()
        e2 = tk.Entry(win, width=40, show="•")
        e2.pack()

        def save():
            email, pwd = e1.get().strip(), e2.get().strip()
            if not email or not pwd or ":" in email:
                messagebox.showerror("Error", "Email/password tidak valid!")
                return
            accs = load_accounts()
            if any(a[0] == email for a in accs):
                messagebox.showwarning("Duplikat", "Akun sudah ada!")
                return
            accs.append((email, pwd))
            save_accounts(accs)
            self.refresh_tree()
            self.append_log(f"Akun ditambah: {email}")
            win.destroy()

        ttk.Button(win, text="💾 Simpan", command=save).pack(pady=10)

    def del_account(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Pilih akun dulu di tabel.")
            return
        email = self.tree.item(sel[0])["values"][0]
        accs = [a for a in load_accounts() if a[0] != email]
        save_accounts(accs)
        self.refresh_tree()
        self.append_log(f"Akun dihapus: {email}")

    def do_login(self):
        self.run_async(relogin_all, "🔑 LOGIN SEMUA AKUN...")

    def do_claim(self, mode):
        label = "🎓 LATIHAN COS..." if mode == "cos" \
            else "⚡ GAS 2C2G SEKARANG..."
        self.run_async(lambda: run_claim_all(mode), label)

    def do_war(self):
        if not messagebox.askyesno(
                "WAR 23:00",
                "Mulai mode WAR?\n\n"
                "• Login otomatis jam 22:40\n"
                "• Browser standby jam 22:55\n"
                "• GAS 2C2G tepat 23:00\n\n"
                "Browser akan terbuka & TETAP TERBUKA. Lanjut?"):
            return
        self.run_async(lambda: war_scheduler(
            lambda s: self.root.after(0, lambda: self.set_status(s, "#f38ba8"))),
            "🚀 WAR MODE AKTIF", "#f38ba8")

# ================== MAIN ==================
def main():
    root = tk.Tk()
    ClaimApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
