# ============================================================
#  AUTO CLAIM TENCENT CLOUD - TUI EDITION (Dashboard Live)
#  Tampilan dashboard seperti monitoring tool + jam realtime
# ============================================================
#  Cara pakai:
#    1. Isi daftar akun di accounts.txt (format: email:password)
#    2. Login semua akun  : python auto_claim_tui.py --login
#    3. Test claim (COS)  : python auto_claim_tui.py --test
#    4. Claim langsung    : python auto_claim_tui.py --retry-now
#    5. Mode normal 23:00 : python auto_claim_tui.py
# ============================================================

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.progress_bar import ProgressBar

# ================== KONFIGURASI ==================
BASE_DIR = Path(__file__).parent
ACCOUNTS_FILE = BASE_DIR / "accounts.txt"
SESSION_DIR = BASE_DIR / "sessions"
FREE_TIER_URL = "https://www.tencentcloud.com/act/pro/FreeTier"
LOGIN_URL = "https://www.tencentcloud.com/account/login"

CLAIM_HOUR = 23
CLAIM_MINUTE = 0
PREPARE_SECONDS = 300  # browser kebuka H-5min (22:55), reload terakhir 22:59:52
RELOGIN_HOUR = 22       # login SEMUA akun jam 22:40 (session segar sebelum war)
RELOGIN_MINUTE = 40

CLAIM_MODE = "lighthouse"   # "lighthouse" atau "cos"
# =================================================

SESSION_DIR.mkdir(exist_ok=True)

# ==== FIX WARNA ANSI di cmd Windows ====
# Tanpa ini, kode warna (<[34m dll) muncul sebagai teks aneh, bukan warna
os.environ.setdefault("ANSICON", "1")
os.environ.setdefault("Rich_Live", "1")
os.system("")  # trik dikenal: mengaktifkan ANSI di console Windows
console = Console(legacy_windows=False, force_terminal=True, color_system="truecolor")  # warna ANSI dipaksa aktif
LOG_FILE = BASE_DIR / "tui_events.log"

APP_NAME = "Tencent Auto Claim TUI v1.0"

# ================== STATE GLOBAL (untuk dashboard) ==================
class State:
    def __init__(self):
        self.accounts = []          # list of dict per akun
        self.events = []            # event log (max 14 baris)
        self.success = 0
        self.failed = 0
        self.retry = 0
        self.running = 0
        self.queue = 0
        self.start_time = None
        self.ip = "---"
        self.mode_label = "IDLE"
        self.target_time = None
        self.finished = False

    def log(self, msg, style="white"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.events.append((ts, msg, style))
        if len(self.events) > 14:
            self.events = self.events[-14:]
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def account(self, email):
        for a in self.accounts:
            if a["email"] == email:
                return a
        a = {"email": email, "stage": "Queue", "status": "WAITING",
             "progress": 0, "retry": "0/3", "ms": "---", "worker": "-"}
        self.accounts.append(a)
        return a

STATE = State()

# ================== UTIL ==================
def load_accounts():
    if not ACCOUNTS_FILE.exists():
        STATE.log(f"File {ACCOUNTS_FILE.name} tidak ada!", "red")
        return []
    accounts = []
    for line in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        email, _, password = line.partition(":")
        accounts.append((email.strip(), password.strip()))
    STATE.log(f"{len(accounts)} akun dimuat", "cyan")
    return accounts

def session_path(email):
    safe = email.replace("@", "_at_").replace(".", "_")
    return SESSION_DIR / f"{safe}.json"

# ================== DASHBOARD RENDER ==================
def render_dashboard():
    now = datetime.now()

    # ---- Header ----
    elapsed = ""
    if STATE.start_time:
        el = now - STATE.start_time
        elapsed = f"Elapsed: {str(el).split('.')[0][:8]}"

    if STATE.target_time and not STATE.finished:
        remain = STATE.target_time - now
        total_s = max(0, int(remain.total_seconds()))
        h, m, s = total_s // 3600, (total_s % 3600) // 60, total_s % 60
        countdown = f"Countdown: {h:02d}:{m:02d}:{s:02d}"
        if total_s <= 60:
            countdown = f"[bold red]{countdown}[/bold red]"
        elif total_s <= 300:
            countdown = f"[bold yellow]{countdown}[/bold yellow]"
        else:
            countdown = f"[bold green]{countdown}[/bold green]"
    else:
        countdown = "Countdown: --:--:--"

    header = Table.grid(padding=(0, 2))
    header.add_row(Text(APP_NAME, style="bold cyan", justify="center"))
    info = Table.grid(padding=(0, 3))
    info.add_row(
        Text(f"Jam: {now.strftime('%H:%M:%S')}", style="bold white"),
        Text(f"Tanggal: {now.strftime('%Y-%m-%d')}", style="white"),
        Text(countdown),
        Text(f"Mode: {STATE.mode_label}", style="magenta"),
        Text(elapsed, style="white"),
        Text(f"IP: {STATE.ip}", style="yellow"),
    )
    header.add_row(info)

    # ---- Tabel akun ----
    acc_table = Table(show_lines=False, expand=True)
    acc_table.add_column("#", justify="right", width=4)
    acc_table.add_column("Email", ratio=3)
    acc_table.add_column("Work.", justify="right", width=6)
    acc_table.add_column("Stage", ratio=2)
    acc_table.add_column("Status", width=12)
    acc_table.add_column("Progress", width=14)
    acc_table.add_column("Retry", justify="center", width=6)
    acc_table.add_column("MS", justify="right", width=8)

    for i, a in enumerate(STATE.accounts, 1):
        status_style = {
            "WAITING": "dim",
            "PROCESSING": "cyan",
            "SUCCESS": "bold green",
            "FAILED": "bold red",
            "RETRYING": "yellow",
        }.get(a["status"], "white")
        acc_table.add_row(
            str(i), a["email"], a["worker"], a["stage"],
            Text(a["status"], style=status_style),
            ProgressBar(completed=a["progress"], total=100),
            a["retry"], str(a["ms"]),
        )

    # ---- Event log ----
    log_table = Table.grid(padding=(0, 1))
    log_table.add_column(width=10)
    log_table.add_column(ratio=1)
    for ts, msg, style in STATE.events[-14:]:
        log_table.add_row(Text(ts, style="dim"), Text(msg, style=style))

    # ---- Error summary + performance ----
    total = STATE.success + STATE.failed
    rate = f"{(STATE.success / total * 100):.1f}%" if total else "--"
    bottom = Table.grid(padding=(0, 2))
    bottom.add_row(
        Panel(Text(f"Failed: {STATE.failed}  Retry: {STATE.retry}",
                   style="red"), title="Error Summary", width=40),
        Panel(Text(f"Success: {STATE.success}   Rate: {rate}",
                   style="green"), title="Performance", width=40),
    )

    # ---- Overall progress ----
    done = STATE.success + STATE.failed
    overall = int(done / len(STATE.accounts) * 100) if STATE.accounts else 0
    overall_grid = Table.grid(padding=(0, 1))
    overall_grid.add_row(
        ProgressBar(completed=overall, total=100, width=60),
        Text(f" {overall}%", style="bold"),
    )
    overall_panel = Panel(overall_grid, title="Overall Progress")

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=4),
        Layout(name="accounts", ratio=5),
        Layout(name="log", ratio=6),
        Layout(name="bottom", size=5),
        Layout(name="overall", size=3),
    )
    layout["header"].update(Panel(header, border_style="yellow"))
    layout["accounts"].update(Panel(acc_table, title="Accounts",
                                    border_style="yellow"))
    layout["log"].update(Panel(log_table, title="Recent Events",
                               border_style="blue"))
    layout["bottom"].update(Panel(bottom, border_style="green"))
    layout["overall"].update(overall_panel)
    return layout

# ================== PLAYWRIGHT HELPERS ==================
async def dismiss_cookie_dialog(page):
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
                    STATE.log(f"[{page._email}] Cookies ditutup", "dim")
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
            STATE.log(f"[{page._email}] Popup 'system busy'!", "red")
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
            STATE.log(f"[{page._email}] {desc} OK", "green")
            return True
        except Exception:
            continue
    STATE.log(f"[{page._email}] {desc} GAGAL", "red")
    return False

# ================== LOGIN ==================
async def login_one(playwright, email, password):
    sp = session_path(email)
    browser = await playwright.chromium.launch(headless=False)
    ctx = await browser.new_context()
    page = await ctx.new_page()
    page._email = email

    STATE.log(f"[{email}] Membuka login...", "cyan")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)
    await dismiss_cookie_dialog(page)

    try:
        await page.fill('input[type="text"], input[placeholder*="mail" i]', email)
        await page.fill('input[type="password"]', password)
        await page.click('button:has-text("Log in")')
    except Exception as e:
        STATE.log(f"[{email}] Gagal isi form: {e}", "red")

    try:
        await page.wait_for_url(lambda u: "login" not in u, timeout=30000)
    except Exception:
        pass

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    await dismiss_cookie_dialog(page)

    content = await page.content()
    if "Sign Up Free" in content or "Log in with email" in content:
        STATE.log(f"[{email}] Butuh login manual!", "yellow")
        input(f"    [{email}] Login manual di browser, lalu Enter...")
        await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await dismiss_cookie_dialog(page)

    await ctx.storage_state(path=str(sp))
    STATE.log(f"[{email}] Session tersimpan", "green")
    await browser.close()

async def login_all():
    accounts = load_accounts()
    if not accounts:
        return
    STATE.mode_label = "LOGIN"
    async with async_playwright() as p:
        for i, (email, password) in enumerate(accounts, 1):
            STATE.log(f"Login {i}/{len(accounts)}: {email}", "cyan")
            await login_one(p, email, password)
    STATE.log(f"SEMUA AKUN SELESAI LOGIN ({len(accounts)})", "bold green")
    print("\n[+] Semua akun selesai login!")

async def relogin_all_if_needed():
    """Relogin SEMUA akun (termasuk baru di-add) jam 22:45 —
    session dijamin segar sebelum war."""
    accounts = load_accounts()
    if not accounts:
        return
    STATE.mode_label = "RELOGIN"
    STATE.log(f"Relogin {len(accounts)} akun (jaga-jaga session exp)",
              "bold cyan")
    async with async_playwright() as p:
        for i, (email, password) in enumerate(accounts, 1):
            STATE.log(f"Relogin {i}/{len(accounts)}: {email}", "cyan")
            await login_one(p, email, password)
    STATE.log(f"SEMUA AKUN SEGAR ({len(accounts)}) — siap war!", "bold green")

# ================== CLAIM ==================
async def claim_product(page):
    email = page._email
    mode = page._mode
    acc = STATE.account(email)

    acc["stage"] = "Refresh"
    acc["progress"] = 10
    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    await dismiss_cookie_dialog(page)

    # MODE TERJADWAL (23:00): reload berkala, klik GAS tepat di jam target
    if STATE.target_time is not None:
        target_ts = STATE.target_time.timestamp()
        if time.time() < target_ts:
            acc["stage"] = "Standby"
            acc["progress"] = 20
            STATE.log(f"[{email}] Standby reload sampai jam target", "cyan")
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
            # Reload TERAKHIR H-8s — halaman sudah kebuka SEBELUM jam target
            # (reload tepat 23:00 bikin telat ~19 detik karena server ramai)
            try:
                await page.reload(wait_until="domcontentloaded")
                await dismiss_cookie_dialog(page)
            except Exception:
                pass
            # Presisi sampai jam target
            while time.time() < target_ts:
                await asyncio.sleep(0.02)
            STATE.log(f"[{email}] JAM TARGET! Refresh + GAS!", "bold green")

    # Cari tombol Get Started pada kartu TERKETAT yang cocok (anti salah klik)
    acc["stage"] = "Find Card"
    acc["progress"] = 25
    needle = "object storage" if mode == "cos" else "lighthouse"
    clicked = False

    if STATE.target_time is not None:
        # ===== MODE WAR: refresh cepat + polling klik 50ms =====
        # Deteksi + klik dalam SATU panggilan JS = nol delay deteksi-klik.
        try:
            await page.reload(wait_until="commit")
        except Exception:
            pass
        target_ts = STATE.target_time.timestamp()
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
                    STATE.log(f"[{email}] GET STARTED DIKLIK (polling 50ms)!",
                              "bold green")
                    # Klik bisa nyangkut di tombol disabled (stok belum
                    # release) — WAJIB verifikasi dialog Buy Now muncul.
                    # Belum muncul = lanjut polling + klik ulang.
                    try:
                        await page.wait_for_selector(
                            'button:has-text("Buy Now"), '
                            'button:has-text("立即购买")',
                            timeout=1500)
                        clicked = True
                        break
                    except Exception:
                        STATE.log(f"[{email}] Dialog belum muncul, "
                                  f"klik ulang...", "yellow")
                        await asyncio.sleep(0.5)
                if res in ("soldout", "disabled") \
                        and time.time() - last_reload > 3:
                    sold_out_count += 1
                    if sold_out_count <= 5:
                        STATE.log(f"[{email}] 2C2G SOLD OUT/DISABLED — "
                                  f"reload cari stok #{sold_out_count}",
                                  "yellow")
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
            STATE.log(f"[{email}] Get Started belum muncul (tunggu 15s)",
                      "yellow")

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
                        // naik ke kartu terketat: berhenti jika parent
                        // memuat >1 tombol Get Started (grid semua kartu)
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
                            // WAJIB 2C2G — jangan sampe salah produk!
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
            STATE.log(f"[{email}] JS search error: {e}", "red")
            n_matches = 0

        if n_matches == 0:
            await page.wait_for_timeout(1500)
            continue

        STATE.log(f"[{email}] {n_matches} kartu cocok, clik satu-per-satu",
                  "cyan")
        for idx in range(n_matches):
            try:
                await page.evaluate(
                    """(idx) => {
                        const b = window.__gsMatches[idx];
                        b.scrollIntoView({block: 'center'});
                        b.click();
                    }""", idx)
                STATE.log(f"[{email}] Get Started #{idx + 1} diklik", "green")
            except Exception:
                break
            # Verifikasi dialog Buy Now benar-benar muncul
            try:
                await page.wait_for_selector(
                    'button:has-text("Buy Now"), button:has-text("立即购买")',
                    timeout=5000)
                clicked = True
                break
            except Exception:
                STATE.log(f"[{email}] Kartu #{idx + 1} salah, coba berikutnya",
                          "yellow")
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                await page.wait_for_timeout(1000)
        if clicked:
            break
        await page.wait_for_timeout(1500)

    if not clicked:
        STATE.log(f"[{email}] Get Started tidak ditemukan!", "red")
        try:
            await page.screenshot(
                path=str(BASE_DIR / f"debug_{email.split('@')[0]}_{mode}.png"),
                full_page=True)
        except Exception:
            pass
        return False

    # Tunggu dialog konfigurasi
    acc["stage"] = "Buy Now"
    acc["progress"] = 45
    try:
        await page.wait_for_selector(
            'button:has-text("Buy Now"), button:has-text("立即购买")',
            timeout=10000)
    except Exception:
        STATE.log(f"[{email}] Dialog Buy Now tidak muncul!", "red")
        try:
            await page.screenshot(
                path=str(BASE_DIR / f"debug_{email.split('@')[0]}_{mode}.png"),
                full_page=True)
        except Exception:
            pass
        return False
    await page.wait_for_timeout(300)
    # Verifikasi produk di dialog (soft: kartu sudah dipastikan benar)
    try:
        dlg_txt = (await page.evaluate(
            "() => document.body.innerText")).lower()
        aliases = (["object storage", "cos"] if mode == "cos"
                   else ["lighthouse", "轻量"])
        if any(a in dlg_txt for a in aliases):
            STATE.log(f"[{email}] Dialog sesuai produk ({mode})", "green")
        else:
            STATE.log(f"[{email}] Dialog tak terverifikasi, lanjut (kartu OK)",
                      "yellow")
    except Exception:
        pass
    # KLIK BUY NOW SECEPAT KILAT: JS klik instan DULU (0 detik tunggu) —
    # button sudah pasti ada karena dialog sudah diverifikasi di atas.
    # Kalau JS gagal (aneh), baru fallback selector dengan timeout pendek.
    # Buy Now terklik = SUKSES (lanjut Pay Now = success)
    buy_now_ok = False
    try:
        js_ok = await page.evaluate(
            """() => {
                const b = [...document.querySelectorAll('button')]
                    .find(x => /buy now|立即购买/i
                            .test(x.textContent || ''));
                if (b) { b.click(); return true; }
                return false;
            }""")
        if js_ok:
            buy_now_ok = True
            STATE.log(f"[{email}] BUY NOW diklik (JS instan)", "green")
    except Exception:
        pass
    if not buy_now_ok:
        ok_buy = await try_click(page, [
            'button:has-text("Buy Now")',
            'button:has-text("立即购买")',
        ], "Buy Now", timeout=1500)
        buy_now_ok = ok_buy
        if buy_now_ok:
            STATE.log(f"[{email}] BUY NOW diklik (selector)", "green")

    if buy_now_ok:
        STATE.log(f"[{email}] BUY NOW TERKLIK = SUKSES! "
                  f"(lanjut Pay/Confirm best-effort)", "bold green")
        acc["progress"] = 90

    await page.wait_for_timeout(1500)
    await dismiss_busy_popup(page)

    if not buy_now_ok:
        return False  # Buy Now gagal total → retry cepat

    # Tunggu halaman order
    acc["stage"] = "Pay Now"
    acc["progress"] = 65
    try:
        await page.wait_for_url(
            lambda u: ("intlprepay" in u.lower()) or ("order" in u.lower()),
            timeout=10000)
    except Exception:
        STATE.log(f"[{email}] Tidak pindah ke halaman order", "yellow")

    t0 = time.time()
    await try_click(page, [
        'button:has-text("立即支付")',
        'button:has-text("Pay Now")',
    ], "Pay Now")
    await page.wait_for_timeout(1500)
    await dismiss_busy_popup(page)

    # Confirm
    acc["stage"] = "Confirm"
    acc["progress"] = 95
    await try_click(page, [
        'button:has-text("确认支付")',
        'button:has-text("Confirm")',
    ], "Confirm Payment")

    await page.wait_for_timeout(3000)
    try:
        shot = BASE_DIR / f"claim_{email.split('@')[0]}_{mode}.png"
        await page.screenshot(path=str(shot), full_page=True)
    except Exception:
        pass

    # SUKSES ditentukan oleh Buy Now terklik — Pay/Confirm cuma bonus
    acc["ms"] = int((time.time() - t0) * 1000)
    acc["progress"] = 100
    return True

async def claim_and_verify(ctx, email, password, mode):
    sp = session_path(email)
    if not sp.exists():
        STATE.log(f"[{email}] Belum ada session! --login dulu", "red")
        acc = STATE.account(email)
        acc["status"] = "FAILED"
        STATE.failed += 1
        return False

    acc = STATE.account(email)
    acc["status"] = "PROCESSING"
    acc["stage"] = "Open Browser"
    acc["worker"] = "1"
    STATE.running += 1
    STATE.queue = max(0, STATE.queue - 1)

    browser = await ctx.chromium.launch(headless=False)
    context = await browser.new_context(storage_state=str(sp))
    page = await context.new_page()
    page._email = email
    page._mode = mode

    await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await dismiss_cookie_dialog(page)
    content = await page.content()
    if "Sign Up Free" in content or "Log in with email" in content:
        STATE.log(f"[{email}] Session expired, login ulang...", "yellow")
        await context.close()
        await browser.close()
        async with async_playwright() as p2:
            await login_one(p2, email, password)
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
        acc["retry"] = f"{attempt - 1}/3"
        STATE.log(f"[{email}] Percobaan {attempt}", "cyan")

        # Cek page masih hidup — kalau mati, restart browser
        try:
            _ = page.url
        except Exception:
            STATE.log(f"[{email}] Browser/page mati, restart...", "yellow")
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            browser = await ctx.chromium.launch(headless=False)
            context = await browser.new_context(storage_state=str(sp))
            page = await context.new_page()
            page._email = email
            page._mode = mode
            await page.goto(FREE_TIER_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await dismiss_cookie_dialog(page)

        try:
            ok = await claim_product(page)
        except Exception as e:
            STATE.log(f"[{email}] ERROR percobaan {attempt}: "
                      f"{type(e).__name__}: {e}", "red")
            ok = False
        if ok:
            # Buy Now sudah terklik di claim_product → LANGSUNG SUKSES.
            # Tidak perlu verifikasi URL/konten, tidak perlu retry.
            acc["status"] = "SUCCESS"
            STATE.success += 1
            STATE.log(f"[{email}] CLAIM BERHASIL! (Buy Now terklik)",
                      "bold green")
            success = True
            break
        else:
            acc["status"] = "RETRYING"
            STATE.retry += 1
        try:
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    if not success:
        acc["status"] = "FAILED"
        STATE.failed += 1
        STATE.log(f"[{email}] CLAIM GAGAL (3x percobaan)", "bold red")

    STATE.running = max(0, STATE.running - 1)
    # Browser DIBIARKAN TERBUKA — bukti claim & bisa dicek manual.
    # JANGAN close browser/context — tetap hidup sampai Ctrl+C.
    try:
        await page.wait_for_timeout(15000)
    except Exception:
        pass
    return success

async def run_claim_all(mode="lighthouse"):
    accounts = load_accounts()
    if not accounts:
        return

    STATE.mode_label = f"CLAIM {mode.upper()}"
    STATE.start_time = datetime.now()
    STATE.queue = len(accounts)
    STATE.accounts = []
    for email, _ in accounts:
        STATE.account(email)

    STATE.log(f"Claim {len(accounts)} akun paralel ({mode})", "bold cyan")

    async with async_playwright() as p:
        tasks = [claim_and_verify(p, email, password, mode)
                 for email, password in accounts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException) and not isinstance(r, Exception):
                raise r
            if isinstance(r, Exception):
                STATE.log(f"WORKER ERROR: {type(r).__name__}: {r}", "red")

# ================== SCHEDULER ==================
async def wait_until_target():
    now = datetime.now()
    target = now.replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE,
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    STATE.target_time = target
    STATE.mode_label = "WAITING"

    prepare_at = target - timedelta(seconds=PREPARE_SECONDS)
    STATE.log(f"Target claim: {target.strftime('%H:%M:%S')}", "cyan")

    # Tunggu hanya sampai H-40s — browser & halaman harus SIAP duluan.
    # Reload presisi + klik GAS tepat jam target dilakukan di claim_product
    while datetime.now() < prepare_at:
        await asyncio.sleep(0.5)
    STATE.log(f"H-{PREPARE_SECONDS}s: siapkan browser + standby...", "yellow")

# ================== MAIN LOOP DENGAN DASHBOARD ==================
async def ui_loop(refresh=0.5):
    # refresh 2x/detik cukup mulus & TIDAK berkedip di cmd
    with Live(render_dashboard(), refresh_per_second=2,
              console=console, screen=True) as live:
        while True:
            live.update(render_dashboard())
            await asyncio.sleep(refresh)

async def app(mode):
    ui = asyncio.create_task(ui_loop())

    if mode == "--login":
        await login_all()
    elif mode == "--test":
        await run_claim_all(mode="cos")
    elif mode == "--retry-now":
        await run_claim_all(mode="lighthouse")
    else:
        # Mode default: login 22:40 → standby 22:55 → war 23:00
        # (browser kebuka 22:55 & TETAP TERBUKA sampai war selesai)
        accounts = load_accounts()
        if accounts:
            now = datetime.now()
            relogin_t = now.replace(hour=RELOGIN_HOUR,
                                    minute=RELOGIN_MINUTE,
                                    second=0, microsecond=0)
            target_t = now.replace(hour=CLAIM_HOUR, minute=CLAIM_MINUTE,
                                   second=0, microsecond=0)
            if target_t <= now:
                target_t += timedelta(days=1)
            # Relogin hanya kalau masih JAUH dari target (> 2 jam);
            # kalau bot di-restart menjelang jam war, relogin di-skip
            # supaya standby + war tetap tepat waktu
            if (target_t - datetime.now()).total_seconds() > 7200:
                if now < relogin_t:
                    STATE.log(f"Relogin semua akun jam "
                              f"{relogin_t.strftime('%H:%M')}...", "cyan")
                    while datetime.now() < relogin_t:
                        await asyncio.sleep(0.5)
                await relogin_all_if_needed()
            else:
                STATE.log("Terlalu mepet target, skip relogin "
                          "(session terakhir dipakai)", "yellow")
            await wait_until_target()
            await run_claim_all(mode="lighthouse")

    STATE.log("Selesai. Dashboard tetap terbuka (Ctrl+C untuk keluar).",
              "bold magenta")
    STATE.finished = True
    try:
        await asyncio.sleep(3600 * 24)   # tetap hidup, tidak auto-close
    except asyncio.CancelledError:
        pass

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    try:
        asyncio.run(app(mode))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
