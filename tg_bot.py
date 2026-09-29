# ============================================================
#  TENCENT AUTO CLAIM - BOT TELEGRAM v4 (button edition)
#  Jalan di RDP ini: python tg_bot.py
#  Token : token.txt | Akses: allowed_id.txt (1 ID per baris)
#  Fitur:
#    - Semua menu pakai BUTTON (inline keyboard)
#    - Kelola akun via button: add (kirim teks), hapus per akun
#    - Limit 30 akun
#    - LIVE LOG realtime saat job jalan (pesan di-edit terus)
#    - /jam = jam RDP
#    - /stop HANYA menghentikan job — BOT TIDAK mati
#    - AUTO-WAR: tiap hari 22:40 login all -> standby -> 23:00 gas
#    - Auto-restart polling + single instance guard
# ============================================================

import asyncio
import os
import socket
import sys
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          CallbackQueryHandler, MessageHandler, filters)

import claim_core
from claim_core import (JM, BASE_DIR, MAX_ACCOUNTS, accounts_status,
                        add_account, del_account, load_accounts, log,
                        tail_log, auto_war_loop)

TOKEN_FILE = BASE_DIR / "token.txt"
ALLOWED_FILE = BASE_DIR / "allowed_id.txt"
# State sesi "tunggu input" per user (misal: mau nambah akun)
PENDING_ADD = set()
_LOCK_SOCK = None


def acquire_single_instance(port=47321):
    """Cegah 2 bot jalan bersamaan (yang lama tetap aman)."""
    global _LOCK_SOCK
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        _LOCK_SOCK = s
        return True
    except OSError:
        return False


# ================== AUTH & HELPERS ==================

def get_token():
    if TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    return os.environ.get("TG_BOT_TOKEN", "").strip()


def load_allowed():
    ids = set()
    if ALLOWED_FILE.exists():
        for part in ALLOWED_FILE.read_text(encoding="utf-8").strip().split():
            if part.isdigit():
                ids.add(int(part))
    return ids


ALLOWED = load_allowed()


def is_allowed(uid):
    return uid in ALLOWED


def main_menu_kb():
    akun_n = len(load_accounts())
    status = "🟢 job jalan" if JM.busy else "⚪ idle"
    rows = [
        [InlineKeyboardButton(f"👥 Akun ({akun_n}/{MAX_ACCOUNTS})",
                              callback_data="menu:akun"),
         InlineKeyboardButton("⏰ Jam RDP", callback_data="jam")],
        [InlineKeyboardButton("🔑 Login Semua", callback_data="login")],
        [InlineKeyboardButton("🎓 Test COS", callback_data="test"),
         InlineKeyboardButton("⚡ GAS 2C2G", callback_data="gas")],
        [InlineKeyboardButton("🚀 WAR 23:00", callback_data="war")],
        [InlineKeyboardButton("📊 Status", callback_data="status"),
         InlineKeyboardButton("📜 Log", callback_data="log30")],
        [InlineKeyboardButton("⏹ STOP JOB", callback_data="stop"),
         InlineKeyboardButton("📸 Bukti", callback_data="shot")],
    ]
    return InlineKeyboardMarkup(rows)


async def send_or_edit(query, text, kb=None):
    """Balas callback: edit pesan kalau dari tombol, kirim baru kalau tidak."""
    if kb is None:
        kb = main_menu_kb()
    txt = text if len(text) <= 4096 else text[:4090] + "…"
    try:
        await query.edit_message_text(txt, reply_markup=kb)
    except Exception:
        try:
            await query.message.reply_text(txt, reply_markup=kb)
        except Exception:
            pass


# ================== LIVE LOG STREAMER ==================

class LiveLog:
    """Pesan Telegram yang di-update tiap ada log baru (max ~2x/dtk)."""

    def __init__(self, bot, chat_id):
        self.bot = bot
        self.chat_id = chat_id
        self.msg = None
        self.buf = []
        self.dirty = asyncio.Event()
        self.task = None
        self.active = True

    def on_line(self, line):
        """Dipanggil sinkron dari claim_core.log()."""
        self.buf.append(line)
        self.dirty.set()

    async def _create(self, first_text):
        self.msg = await self.bot.send_message(
            self.chat_id, f"```\n{first_text}\n```", parse_mode="Markdown")

    async def run(self):
        """Loop flush: gabungkan baris baru ke pesan yang sama."""
        while self.active:
            try:
                await asyncio.wait_for(self.dirty.wait(), timeout=1.5)
            except asyncio.TimeoutError:
                pass
            self.dirty.clear()
            if not self.buf:
                continue
            tambah = "\n".join(self.buf)
            self.buf = []
            if self.msg is None:
                try:
                    await self._create(tambah)
                except Exception:
                    pass
                continue
            teks = (self.msg.text or "").strip("`").strip()
            teks = (teks + "\n" + tambah)[-4000:]
            try:
                await self.bot.edit_message_text(
                    f"```\n{teks}\n```", chat_id=self.chat_id,
                    message_id=self.msg.message_id, parse_mode="Markdown")
            except Exception:
                pass

    def stop(self):
        self.active = False


def attach_live_log(bot, chat_id):
    """Buat LiveLog untuk chat ini + pasang ke claim_core, return handler."""
    live = LiveLog(bot, chat_id)
    JM.add_listener(live.on_line)

    async def runner():
        await live.run()

    live.task = asyncio.create_task(runner())
    return live


# ================== COMMAND DASAR ==================

async def cmd_start(update: Update, ctx):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text(
            f"⛔ Kamu tidak terdaftar.\nTelegram ID kamu: {uid}")
        return
    await update.message.reply_text(
        "🤖 TENCENT AUTO CLAIM — BUTTON EDITION\n"
        "Pilih aksi lewat tombol di bawah 👇",
        reply_markup=main_menu_kb())


async def cmd_getid(update: Update, ctx):
    await update.message.reply_text(
        f"Telegram ID kamu: {update.effective_user.id}\n"
        f"Terdaftar: {'✅' if is_allowed(update.effective_user.id) else '❌'}")


async def cmd_jam(update: Update, ctx):
    from datetime import datetime
    now = datetime.now()
    await update.message.reply_text(
        f"🕐 Jam RDP: {now.strftime('%H:%M:%S')}\n"
        f"📅 {now.strftime('%A, %d %B %Y')}\n"
        f"⏰ Auto-WAR: login 22:40 → gas 23:00")


def guard(func):
    async def wrapper(update: Update, ctx):
        uid = update.effective_user.id
        if not is_allowed(uid):
            await update.message.reply_text(f"⛔ Akses ditolak. ID: {uid}")
            return
        try:
            await func(update, ctx)
        except Exception as e:
            try:
                await update.message.reply_text(
                    f"⚠️ ERROR: {type(e).__name__}: {e}")
            except Exception:
                pass
            log(f"[TG] error di {func.__name__}: {e}")
    return wrapper


async def cmd_status(update: Update, ctx):
    n = len(load_accounts())
    teks = (f"Job: {JM.job_desc()}\n"
            f"Akun: {n}/{MAX_ACCOUNTS}\n"
            f"Browser standby: {len(JM.standby_pages)}")
    if claim_core.WAR_STATE["target"] is not None:
        teks += (f"\nTarget WAR: "
                 f"{claim_core.WAR_STATE['target'].strftime('%d %b %H:%M:%S')}")
    if JM.results:
        teks += "\n\nHasil terakhir:"
        for e, v in list(JM.results.items())[:25]:
            teks += f"\n  {v} {e}"
    await update.message.reply_text(teks, reply_markup=main_menu_kb())


@guard
async def cmd_log(update: Update, ctx):
    n = 50
    if ctx.args and ctx.args[0].isdigit():
        n = min(int(ctx.args[0]), 300)
    teks = tail_log(n) or "(log kosong)"
    if len(teks) > 3900:
        teks = teks[-3900:]
    await update.message.reply_text(f"```\n{teks}\n```",
                                    parse_mode="Markdown",
                                    reply_markup=main_menu_kb())


@guard
async def cmd_add(update: Update, ctx):
    arg = " ".join(ctx.args) if ctx.args else ""
    await handle_add_text(update.message, arg)


@guard
async def cmd_del(update: Update, ctx):
    if not ctx.args:
        await update.message.reply_text("Format: /del email")
        return
    email = ctx.args[0].strip()
    if del_account(email):
        await update.message.reply_text(f"✅ {email} dihapus (beserta session)")
    else:
        await update.message.reply_text(f"⚠️ {email} tidak ditemukan")


async def handle_add_text(msg, arg):
    arg = arg.strip()
    if not arg or ":" not in arg:
        PENDING_ADD.add(msg.chat_id)
        await msg.reply_text(
            f"📧 Kirim akun sekarang, format:\n"
            f"email:password\n\n"
            f"Bisa sekaligus banyak — 1 akun per baris "
            f"(limit {MAX_ACCOUNTS} akun).\n"
            f"Kirim /batal untuk membatalkan.")
        return
    baris_ok, baris_gagal = [], []
    for line in arg.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        email, _, password = line.partition(":")
        email, password = email.strip(), password.strip()
        if "@" not in email or not password:
            baris_gagal.append(f"⚠️ tidak valid: {line[:30]}")
            continue
        hasil = add_account(email, password)
        if hasil.startswith("⛔"):
            baris_gagal.append(hasil)
        else:
            tanda = "✅ ditambah" if hasil.startswith("added") else "♻️ update"
            baris_ok.append(f"{tanda}: {email}")
    teks = ""
    if baris_ok:
        teks += "\n".join(baris_ok) + "\n"
    teks += "\n".join(baris_gagal)
    teks += f"\n\nTotal akun: {len(load_accounts())}/{MAX_ACCOUNTS}"
    PENDING_ADD.discard(msg.chat_id)
    await msg.reply_text(teks or "Tidak ada baris valid.",
                         reply_markup=main_menu_kb())


@guard
async def cmd_batal(update: Update, ctx):
    PENDING_ADD.discard(update.effective_chat.id)
    await update.message.reply_text("OK, batal.", reply_markup=main_menu_kb())


@guard
async def cmd_text_router(update: Update, ctx):
    """Semua teks biasa: kalau lagi nunggu input add -> proses add."""
    chat_id = update.effective_chat.id
    if chat_id in PENDING_ADD:
        await handle_add_text(update.message, update.message.text or "")


# ================== CALLBACK BUTTONS ==================

@guard
async def on_button(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    data = query.data
    bot = ctx.bot
    chat_id = query.message.chat_id

    if data == "menu:akun":
        accounts = load_accounts()
        if not accounts:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Tambah Akun", callback_data="add")],
                [InlineKeyboardButton("« Menu", callback_data="home")]])
            await send_or_edit(query, "Belum ada akun.", kb)
            return
        teks = f"👥 AKUN ({len(accounts)}/{MAX_ACCOUNTS})\n\nKetuk akun = hapus:"
        rows = []
        for email in accounts:
            sp = claim_core.session_path(email)
            tanda = "🟢" if sp.exists() else "⚪"
            rows.append([InlineKeyboardButton(
                f"{tanda} {email[:28]}", callback_data=f"delask:{email}")])
        rows.append([InlineKeyboardButton("➕ Tambah Akun",
                                          callback_data="add")])
        rows.append([InlineKeyboardButton("« Menu", callback_data="home")])
        await send_or_edit(query, teks, InlineKeyboardMarkup(rows))

    elif data.startswith("delask:"):
        email = data.split(":", 1)[1]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 YA, HAPUS",
                                  callback_data=f"delyes:{email}")],
            [InlineKeyboardButton("« Batal", callback_data="menu:akun")]])
        await send_or_edit(query, f"Hapus akun\n{email}\nbeserta session-nya?",
                           kb)

    elif data.startswith("delyes:"):
        email = data.split(":", 1)[1]
        ok = del_account(email)
        teks = (f"🗑 {email} dihapus." if ok
                else f"⚠️ {email} tidak ditemukan.")
        accounts = load_accounts()
        rows = [[InlineKeyboardButton("➕ Tambah Akun", callback_data="add")],
                [InlineKeyboardButton("« Menu", callback_data="home")]]
        await send_or_edit(query, teks + f"\n\nSisa: {len(accounts)} akun",
                           InlineKeyboardMarkup(rows))

    elif data == "add":
        PENDING_ADD.add(chat_id)
        await send_or_edit(
            query,
            f"📧 Kirim akun (format email:password).\n"
            f"Banyak akun? 1 per baris. Limit {MAX_ACCOUNTS}.\n"
            f"/batal untuk membatalkan.")

    elif data == "home":
        akun_n = len(load_accounts())
        await send_or_edit(
            query,
            f"🏠 MENU — akun {akun_n}/{MAX_ACCOUNTS}, "
            f"job: {JM.job_desc()}", main_menu_kb())

    elif data == "jam":
        from datetime import datetime
        now = datetime.now()
        await send_or_edit(
            query,
            f"🕐 Jam RDP: {now.strftime('%H:%M:%S')}\n"
            f"📅 {now.strftime('%A, %d %B %Y')}\n"
            f"⏰ Auto-WAR: login 22:40 → gas 23:00 (otomatis tiap hari)")

    elif data == "login":
        if JM.busy:
            await send_or_edit(query, f"⛔ Job jalan: {JM.job_desc()}")
            return
        await send_or_edit(query, "🔑 Login semua akun dimulai... (live log menyusul)")
        live = attach_live_log(bot, chat_id)
        try:
            hasil = await JM.login_all()
        finally:
            live.stop()
        await bot.send_message(chat_id, hasil, reply_markup=main_menu_kb())

    elif data == "test":
        await start_job_button(query, bot, chat_id, "cos")

    elif data == "gas":
        await start_job_button(query, bot, chat_id, "lighthouse")

    elif data == "war":
        if JM.busy:
            await send_or_edit(query, f"⛔ Job jalan: {JM.job_desc()}")
            return
        pesan = await JM.start_war()
        live = attach_live_log(bot, chat_id)
        await send_or_edit(query, pesan)
        asyncio.create_task(finish_job_watcher(bot, chat_id, live))

    elif data == "status":
        teks = (f"Job: {JM.job_desc()}\n"
                f"Akun: {len(load_accounts())}/{MAX_ACCOUNTS}\n"
                f"Browser standby: {len(JM.standby_pages)}")
        if claim_core.WAR_STATE["target"] is not None:
            teks += (f"\nTarget WAR: "
                     f"{claim_core.WAR_STATE['target'].strftime('%d %b %H:%M:%S')}")
        if JM.results:
            teks += "\n\nHasil terakhir:"
            for e, v in list(JM.results.items())[:20]:
                teks += f"\n  {v} {e}"
        await send_or_edit(query, teks)

    elif data == "log30":
        teks = tail_log(30) or "(log kosong)"
        if len(teks) > 3900:
            teks = teks[-3900:]
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await bot.send_message(chat_id, f"```\n{teks}\n```",
                               parse_mode="Markdown",
                               reply_markup=main_menu_kb())

    elif data == "stop":
        pesan = await JM.stop()
        await send_or_edit(query, pesan + "\n\n🤖 Bot tetap ONLINE — "
                                       "ini cuma stop job-nya.")

    elif data == "shot":
        shots = sorted(BASE_DIR.glob("claim_*.png"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if not shots:
            await send_or_edit(query, "Belum ada screenshot claim.")
            return
        with open(shots[0], "rb") as f:
            await bot.send_photo(chat_id, f, caption=f"📸 {shots[0].name}")


async def start_job_button(query, bot, chat_id, mode):
    pesan = await JM.start_instant(mode)
    if pesan.startswith("⛔"):
        await send_or_edit(query, pesan)
        return
    live = attach_live_log(bot, chat_id)
    await send_or_edit(query, pesan + "\n\n📜 Live log menyusul di bawah...")
    asyncio.create_task(finish_job_watcher(bot, chat_id, live))


async def finish_job_watcher(bot, chat_id, live):
    """Tunggu job selesai, stop live log, kirim ringkasan."""
    try:
        if JM.job_task:
            await asyncio.shield(JM.job_task)
    except Exception:
        pass
    await asyncio.sleep(1.5)  # biar log terakhir sempat masuk buffer
    live.stop()
    ok_n = sum(1 for v in JM.results.values() if v.startswith("✓"))
    tot = len(JM.results)
    teks = f"🏁 JOB SELESAI — {ok_n}/{tot} sukses\n\nJob sekarang: idle"
    try:
        await bot.send_message(chat_id, teks, reply_markup=main_menu_kb())
    except Exception:
        pass


# ================== LIFECYCLE ==================

async def on_startup(app):
    # auto-WAR harian 22:40
    async def notify(text):
        for uid in ALLOWED:
            try:
                await app.bot.send_message(uid, text)
            except Exception:
                pass
    app.create_task(auto_war_loop(notify))
    log("[TG] AUTO-WAR scheduler aktif (22:40 login -> 23:00 gas)")


async def on_error(update, context):
    log(f"[TG] ERROR: {context.error}")


def main():
    if not acquire_single_instance():
        print("[!] Bot sudah jalan di proses lain! Tutup dulu (atau tunggu).")
        sys.exit(2)
    token = get_token()
    if not token:
        print("[!] Token belum ada! Simpan ke token.txt")
        sys.exit(1)

    app = Application.builder().token(token).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("getid", cmd_getid))
    app.add_handler(CommandHandler("jam", cmd_jam))
    app.add_handler(CommandHandler("akun", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("del", cmd_del))
    app.add_handler(CommandHandler("batal", cmd_batal))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("log", cmd_log))
    # teks biasa (input add akun) — harus paling akhir
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   cmd_text_router))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
    app.post_init = on_startup

    log("[TG] Bot v4 mulai... (button edition, auto-war aktif)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Bot dihentikan manual.")
