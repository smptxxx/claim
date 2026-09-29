# ============================================================
#  TENCENT AUTO CLAIM - BOT TELEGRAM (remote control)
#  Jalan di RDP ini: python tg_bot.py
#  Token: file token.txt (di-gitignore) ATAU env TG_BOT_TOKEN
#  Akses: hanya ALLOWED_USER_ID (di-getid.txt) yang dilayani.
# ============================================================
#
#  Perintah bot:
#    /start        — info & daftar perintah
#    /getid        — lihat Telegram ID kamu (untuk daftar akses)
#    /akun         — daftar akun + status session
#    /add email:password — tambah/update akun
#    /del email    — hapus akun + session-nya
#    /login        — login semua akun sekarang (1 akun 1 browser)
#    /test         — LATIHAN: claim COS semua akun
#    /gas          — gas 2C2G langsung (tanpa nunggu jadwal)
#    /war          — mode WAR terjadwal: 22:40 login -> 23:00 gas
#    /status       — status job yang sedang jalan
#    /log          — 30 baris log terakhir
#    /stop         — batalkan job yang jalan (browser dibiarkan terbuka)
#    /shot         — screenshot bukti claim terakhir (kirim file)
# ============================================================

import asyncio
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (Application, CommandHandler, ContextTypes)

import claim_core
from claim_core import (JM, BASE_DIR, accounts_status, add_account,
                        del_account, load_accounts, log, tail_log)

TOKEN_FILE = BASE_DIR / "token.txt"
GETID_FILE = BASE_DIR / "getid.txt"
ALLOWED_FILE = BASE_DIR / "allowed_id.txt"


def get_token():
    if TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    return os.environ.get("TG_BOT_TOKEN", "").strip()


def load_allowed():
    if ALLOWED_FILE.exists():
        txt = ALLOWED_FILE.read_text(encoding="utf-8").strip()
        ids = set()
        for part in txt.replace(",", "\n").split():
            if part.strip().isdigit():
                ids.add(int(part))
        return ids
    return set()


def save_allowed(ids):
    ALLOWED_FILE.write_text("\n".join(str(i) for i in sorted(ids)),
                            encoding="utf-8")


ALLOWED = load_allowed()


def is_allowed(uid):
    if not ALLOWED:
        # Belum ada daftar: user pertama yang /getid otomatis jadi owner
        return False
    return uid in ALLOWED


async def cmd_start(update: Update, ctx):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text(
            f"⛔ Kamu tidak terdaftar.\nTelegram ID kamu: {uid}\n"
            f"Minta owner daftarkan ID ini ke allowed_id.txt")
        return
    await update.message.reply_text(
        "🤖 TENCENT AUTO CLAIM BOT\n\n"
        "/akun — daftar akun + status session\n"
        "/add email:password — tambah/update akun\n"
        "/del email — hapus akun\n"
        "/login — login semua akun sekarang\n"
        "/test — LATIHAN claim COS\n"
        "/gas — gas 2C2G langsung\n"
        "/war — WAR terjadwal (22:40 login, 23:00 gas)\n"
        "/status — status job\n"
        "/log — log terakhir\n"
        "/stop — batalkan job\n"
        "/shot — screenshot hasil")


async def cmd_getid(update: Update, ctx):
    uid = update.effective_user.id
    GETID_FILE.write_text(f"{uid}\n", encoding="utf-8")
    jawab = (f"Telegram ID kamu: {uid}\n(sudah disimpan ke getid.txt)\n\n")
    if not ALLOWED:
        # user pertama = owner otomatis
        ALLOWED.add(uid)
        save_allowed(ALLOWED)
        jawab += "✅ Kamu terdaftar sebagai OWNER (user pertama). Bot siap!"
    elif is_allowed(uid):
        jawab += "✅ Kamu sudah terdaftar."
    else:
        jawab += "⛔ Belum terdaftar. Minta owner masukkan ID ini ke allowed_id.txt"
    await update.message.reply_text(jawab)


def guard(func):
    async def wrapper(update: Update, ctx):
        uid = update.effective_user.id
        if not is_allowed(uid):
            await update.message.reply_text(
                f"⛔ Akses ditolak. ID kamu: {uid}")
            log(f"[TG] akses ditolak dari {uid}")
            return
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            await func(update, ctx)
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ ERROR: {type(e).__name__}: {e}")
            log(f"[TG] error di {func.__name__}: {e}")
    return wrapper


@guard
async def cmd_akun(update: Update, ctx):
    await update.message.reply_text(accounts_status())


@guard
async def cmd_add(update: Update, ctx):
    if not ctx.args:
        await update.message.reply_text(
            "Format: /add email:password\nContoh: /add evi548@gitech.app:Buka@122")
        return
    arg = " ".join(ctx.args)
    if ":" not in arg:
        await update.message.reply_text("⚠️ Harus ada ':' pemisah email:password")
        return
    email, _, password = arg.partition(":")
    email = email.strip()
    password = password.strip()
    if "@" not in email or not password:
        await update.message.reply_text("⚠️ Email/password tidak valid")
        return
    msg = add_account(email, password)
    await update.message.reply_text(f"✅ {msg}\nTotal akun: {len(load_accounts())}")


@guard
async def cmd_del(update: Update, ctx):
    if not ctx.args:
        await update.message.reply_text("Format: /del email")
        return
    email = ctx.args[0].strip()
    if del_account(email):
        await update.message.reply_text(
            f"✅ {email} dihapus (beserta session-nya)")
    else:
        await update.message.reply_text(f"⚠️ {email} tidak ditemukan")


@guard
async def cmd_login(update: Update, ctx):
    if JM.busy:
        await update.message.reply_text(
            f"⛔ Masih ada job jalan: {JM.job_desc()}\n/stop dulu kalau mau batal.")
        return
    await update.message.reply_text("🔑 Login semua akun dimulai...")
    hasil = await JM.login_all()
    await update.message.reply_text(hasil)


@guard
async def cmd_test(update: Update, ctx):
    await update.message.reply_text(await JM.start_instant("cos"))


@guard
async def cmd_gas(update: Update, ctx):
    await update.message.reply_text(await JM.start_instant("lighthouse"))


@guard
async def cmd_war(update: Update, ctx):
    await update.message.reply_text(await JM.start_war())


@guard
async def cmd_status(update: Update, ctx):
    n = len(load_accounts())
    teks = (f"Job: {JM.job_desc()}\n"
            f"Akun terdaftar: {n}\n"
            f"Browser standby terbuka: {len(JM.standby_pages)}")
    if claim_core.WAR_STATE["target"] is not None:
        teks += f"\nTarget WAR: {claim_core.WAR_STATE['target'].strftime('%d %b %H:%M:%S')}"
    if JM.results:
        teks += "\n\nHasil terakhir:"
        for e, v in list(JM.results.items())[:25]:
            teks += f"\n  {v} {e}"
    await update.message.reply_text(teks)


@guard
async def cmd_log(update: Update, ctx):
    n = 30
    if ctx.args and ctx.args[0].isdigit():
        n = min(int(ctx.args[0]), 200)
    teks = tail_log(n) or "(log kosong)"
    if len(teks) > 3900:
        teks = teks[-3900:]
    await update.message.reply_text(f"```\n{teks}\n```",
                                    parse_mode="Markdown")


@guard
async def cmd_stop(update: Update, ctx):
    await update.message.reply_text(await JM.stop())


@guard
async def cmd_shot(update: Update, ctx):
    shots = sorted(BASE_DIR.glob("claim_*.png"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not shots:
        await update.message.reply_text("Belum ada screenshot claim.")
        return
    with open(shots[0], "rb") as f:
        await update.message.reply_photo(f, caption=f"📸 {shots[0].name}")


async def on_error(update, context):
    log(f"[TG] ERROR: {context.error}")


def main():
    token = get_token()
    if not token:
        print("[!] Token belum ada!")
        print("    Simpan token bot ke file token.txt di folder ini,")
        print("    atau set env TG_BOT_TOKEN.")
        sys.exit(1)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("getid", cmd_getid))
    app.add_handler(CommandHandler("akun", cmd_akun))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("del", cmd_del))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("gas", cmd_gas))
    app.add_handler(CommandHandler("war", cmd_war))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("shot", cmd_shot))
    app.add_error_handler(on_error)

    log("[TG] Bot mulai... (Ctrl+C untuk stop)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Bot dihentikan.")
