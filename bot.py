"""Bot Telegram untuk mengontrol laptop Anda sendiri (Windows 11).

Jalankan:  python bot.py
Semua perintah hanya merespons OWNER_ID (lihat auth.py).
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
import time
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PersistenceInput,
    PicklePersistence,
    filters,
)

import agent
import browser_ops
import config
import file_ops
import memory_ops
import shell_ops
import system_ops
from auth import owner_only

# Pola rahasia yang disensor sebelum ditulis ke log (nilai -> ***).
# Urutan penting: pola khusus (Bearer/token) dijalankan sebelum pola key:value umum.
_REDACT_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),      # Bearer <token>
    (re.compile(r"bot\d{6,}:[A-Za-z0-9_\-]{20,}"), "bot***"),         # token bot Telegram di URL
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b"), "***"),         # token bot Telegram umum
    # key: value / key=value / "key":"value" (termasuk kutip ter-escape \" dari perintah shell)
    (re.compile(
        r'(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?token|'
        r'refresh[_-]?token|authorization)([:=\s"\'\\]+)([^\s"\',}\\&]+)'
    ), r"\1\2***"),
]


class RedactingFormatter(logging.Formatter):
    """Formatter yang menyensor pola rahasia dari seluruh baris log (termasuk traceback)."""

    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        for pat, repl in _REDACT_PATTERNS:
            s = pat.sub(repl, s)
        return s


_LOG_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),  # tampil di console saat dijalankan manual
        logging.FileHandler(config.BASE_DIR / "bot.log", encoding="utf-8"),  # untuk mode pythonw
    ],
)
# Pasang formatter penyensor ke semua handler.
for _h in logging.getLogger().handlers:
    _h.setFormatter(RedactingFormatter(_LOG_FMT))

log = logging.getLogger("laptopbot")

# Kurangi kebisingan + jangan catat URL polling (yang memuat token) tiap 10 detik.
for _noisy in ("httpx", "httpcore", "telegram", "apscheduler"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

HELP = """🤖 *Bot Kendali Laptop*

*Sistem*
/sys — status CPU/RAM/disk/baterai
/ps — 10 proses pemakai RAM terbesar
/screenshot — tangkap layar
/windows — daftar jendela aplikasi terbuka
/appshot `<judul>` — screenshot jendela aplikasi (mis. Telegram/Teams)

*File*
/ls `<path>` — daftar isi folder
/get `<path>` — kirim file ke chat ini
(kirim file apa pun ke bot → disimpan ke folder downloads)
(baca/tulis/edit kode: lewat mode agent, ketik bahasa biasa)

*Shell*
/run `<perintah>` — jalankan perintah cmd.exe

*Browser*
/open `<url>` — buka URL di browser default laptop
/browser_login `[url]` — login situs di profil bot (Drive, sosmed, dll)
/tabs — daftar tab Chrome (butuh mode debug)
/scrape `<url>` — ambil judul + teks halaman (pakai profil login bot)
/shot `<url>` — screenshot halaman web (pakai profil login bot)

*Agent (9Router)*
Ketik saja dalam bahasa biasa, mis.
"berapa pemakaian RAM sekarang?" atau "screenshot layar lalu buka youtube".
/reset — hapus riwayat percakapan agent
/reload `[modul...]` — hot-reload kode tanpa restart (kosong = semua)

/ping — cek bot nyala & responsif
/help — tampilkan bantuan ini
"""


class TelegramActions:
    """Adapter yang dipakai tools untuk mengirim media & minta konfirmasi."""

    def __init__(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.update = update
        self.context = context
        self.chat = update.effective_chat

    async def send_text(self, text: str) -> None:
        await self.chat.send_message(text)

    async def send_photo(self, png: bytes, caption: str | None = None) -> None:
        await self.chat.send_photo(png, caption=caption)

    async def send_document(self, path) -> None:
        with open(path, "rb") as fh:
            await self.chat.send_document(fh, filename=path.name)

    async def confirm(self, prompt: str) -> bool:
        token = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self.context.application.bot_data.setdefault("pending", {})[token] = fut
        kb = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Ya", callback_data=f"cf:{token}:1"),
                InlineKeyboardButton("❌ Tidak", callback_data=f"cf:{token}:0"),
            ]]
        )
        # Teks polos (tanpa Markdown) agar konten kode tidak memicu error parse.
        await self.chat.send_message(f"⚠️ {prompt}", reply_markup=kb)
        try:
            return await asyncio.wait_for(fut, timeout=120)
        except asyncio.TimeoutError:
            return False
        finally:
            self.context.application.bot_data.get("pending", {}).pop(token, None)


# --- Umum ---------------------------------------------------------------------

@owner_only
async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)


_START = time.monotonic()
_CHAT_LOCKS: dict[int, asyncio.Lock] = {}


@owner_only
async def cmd_ping(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    up = int(time.monotonic() - _START)
    await update.message.reply_text(
        f"🟢 Bot nyala & merespons. Uptime {up // 3600}j {(up % 3600) // 60}m {up % 60}d."
    )


# --- Sistem -------------------------------------------------------------------

@owner_only
async def cmd_sys(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = await asyncio.to_thread(system_ops.summary)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_ps(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = await asyncio.to_thread(system_ops.top_processes)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_screenshot(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_action(ChatAction.UPLOAD_PHOTO)
    png = await asyncio.to_thread(system_ops.screenshot_png)
    await update.message.reply_photo(png, caption="🖥️ Layar sekarang")


@owner_only
async def cmd_windows(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import desktop_ops

    text = await asyncio.to_thread(desktop_ops.list_windows)
    await update.message.reply_text(text)


@owner_only
async def cmd_appshot(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import desktop_ops

    if not ctx.args:
        await update.message.reply_text("Pakai: /appshot <sebagian judul jendela>  (lihat /windows)")
        return
    title = " ".join(ctx.args)
    await update.effective_chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        png = await asyncio.to_thread(desktop_ops.screenshot_window, title)
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ {exc}")
        return
    await update.message.reply_photo(png, caption=f"🪟 {title}")


# --- File ---------------------------------------------------------------------

@owner_only
async def cmd_ls(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    path = " ".join(ctx.args) if ctx.args else str(config.BASE_DIR)
    text = await asyncio.to_thread(file_ops.list_dir, path)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_get(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Pakai: /get <path file>")
        return
    path_str = " ".join(ctx.args)
    try:
        path = await asyncio.to_thread(file_ops.resolve_for_send, path_str)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    await update.effective_chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    with path.open("rb") as fh:
        await update.message.reply_document(fh, filename=path.name)


@owner_only
async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    obj = msg.document or (msg.photo[-1] if msg.photo else None)
    if obj is None:
        return
    filename = getattr(obj, "file_name", None) or f"{obj.file_unique_id}.jpg"
    dest = file_ops.download_path_for(filename)
    tg_file = await obj.get_file()
    await tg_file.download_to_drive(custom_path=str(dest))
    # Auto-ingat: supaya agent tahu file ini ada & lokasinya (lintas restart).
    await asyncio.to_thread(
        memory_ops.remember, f"Pengguna mengunggah dokumen '{filename}' tersimpan di {dest}"
    )
    await msg.reply_text(f"💾 Tersimpan: `{dest}`\n🧠 Diingat.", parse_mode=ParseMode.MARKDOWN)


# --- Shell --------------------------------------------------------------------

@owner_only
async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    command = " ".join(ctx.args)
    if not command:
        await update.message.reply_text("Pakai: /run <perintah>")
        return
    await update.effective_chat.send_action(ChatAction.TYPING)
    result = await shell_ops.run(command)
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN)


# --- Browser ------------------------------------------------------------------

@owner_only
async def cmd_open(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Pakai: /open <url>")
        return
    text = await asyncio.to_thread(browser_ops.open_url, ctx.args[0])
    await update.message.reply_text(text)


@owner_only
async def cmd_tabs(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = await asyncio.to_thread(browser_ops.list_chrome_tabs)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_browser_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    start = ctx.args[0] if ctx.args else "https://www.google.com"
    await update.message.reply_text(
        "🌐 Membuka jendela browser bot di laptop. Login ke situs yang Anda mau "
        "(Google Drive, sosmed, dll), lalu tutup jendelanya kalau selesai. "
        "Cookie akan tersimpan untuk dipakai scrape/screenshot."
    )
    result = await asyncio.to_thread(browser_ops.open_login_window, start)
    await update.message.reply_text(result)


@owner_only
async def cmd_scrape(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Pakai: /scrape <url>")
        return
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        text = await asyncio.to_thread(browser_ops.scrape, ctx.args[0])
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ Gagal scrape: {exc}")
        return
    # Teks halaman web bebas isi -> kirim polos, bukan Markdown.
    await update.message.reply_text(text)


@owner_only
async def cmd_shot(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Pakai: /shot <url>")
        return
    await update.effective_chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        png = await asyncio.to_thread(browser_ops.screenshot_url, ctx.args[0])
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ Gagal screenshot: {exc}")
        return
    await update.message.reply_photo(png, caption=ctx.args[0])


# --- Agent (bahasa natural via 9Router) ---------------------------------------

def _trim_history(history: list[dict], max_len: int = 40, keep: int = 24) -> None:
    """Jaga riwayat tidak membengkak; potong di batas pesan 'user' agar tetap valid."""
    if len(history) <= max_len:
        return
    system = history[0]
    tail = history[-keep:]
    while tail and tail[0].get("role") != "user":
        tail.pop(0)
    history[:] = [system] + tail


@owner_only
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.AGENT_ENABLED:
        await update.message.reply_text(
            "🤖 Agent nonaktif. Isi `router_api_key` di config.json "
            "(atau env ROUTER_API_KEY) lalu restart bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    history = ctx.chat_data.setdefault("history", agent.new_history())
    actions = TelegramActions(update, ctx)

    # Kunci per-chat (disimpan di luar chat_data agar chat_data tetap bisa
    # di-pickle untuk persistensi): cegah dua giliran agent mengaduk `history`.
    cid = update.effective_chat.id
    lock = _CHAT_LOCKS.get(cid)
    if lock is None:
        lock = asyncio.Lock()
        _CHAT_LOCKS[cid] = lock

    await update.effective_chat.send_action(ChatAction.TYPING)
    async with lock:
        reply = await agent.run(update.message.text, history, actions)
        _trim_history(history)
    # Kirim polos agar markdown model yang tidak valid tidak memicu error Telegram.
    await update.message.reply_text(reply)


@owner_only
async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.chat_data["history"] = agent.new_history()
    await update.message.reply_text("🧹 Riwayat percakapan agent direset. (Ingatan permanen tetap.)")


@owner_only
async def cmd_memory(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = " ".join(ctx.args) if ctx.args else ""
    text = await asyncio.to_thread(memory_ops.recall, q)
    await update.message.reply_text("🧠 Ingatan:\n" + text)


@owner_only
async def cmd_reload(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import reloader

    mods = ctx.args or None  # /reload tools agent  -> ['tools','agent']; /reload -> semua
    await update.effective_chat.send_action(ChatAction.TYPING)
    result = await asyncio.to_thread(reloader.reload, mods)
    await update.message.reply_text(result)


@owner_only
async def on_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    try:
        _, token, val = (q.data or "").split(":")
    except ValueError:
        return
    fut = ctx.application.bot_data.get("pending", {}).get(token)
    decision = val == "1"
    if fut is not None and not fut.done():
        fut.set_result(decision)
    await q.edit_message_text("✅ Dikonfirmasi." if decision else "❌ Dibatalkan.")


# --- Monitoring: contoh peringatan baterai lemah ------------------------------

async def battery_watch(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import psutil

    batt = psutil.sensors_battery()
    if batt is None:
        return
    flagged = ctx.bot_data.get("battery_flagged", False)
    low = (not batt.power_plugged) and batt.percent <= config.BATTERY_ALERT_PERCENT
    if low and not flagged:
        await ctx.bot.send_message(
            config.OWNER_ID,
            f"🪫 Baterai tinggal {batt.percent:.0f}% dan tidak sedang di-charge.",
        )
        ctx.bot_data["battery_flagged"] = True
    elif not low:
        ctx.bot_data["battery_flagged"] = False


# --- Error handler ------------------------------------------------------------

async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Error saat memproses update", exc_info=ctx.error)


# Pengaman satu-instance: bind port localhost sebagai "kunci". Instance kedua
# gagal bind -> keluar rapi, supaya tidak dua bot berebut token (Conflict).
_LOCK_SOCKET: socket.socket | None = None


def _acquire_single_instance_lock(port: int = 49231) -> bool:
    global _LOCK_SOCKET
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        s.close()
        return False
    s.listen(1)
    _LOCK_SOCKET = s  # simpan referensi agar tidak tertutup selama proses hidup
    return True


def main() -> None:
    config.validate()

    if not _acquire_single_instance_lock():
        log.warning("Instance bot lain sudah berjalan — keluar agar tidak bentrok (Conflict).")
        return

    import reloader
    reloader.snapshot()  # simpan 'versi baik' tiap modul untuk rollback hot-reload

    # concurrent_updates: proses banyak pesan paralel, agar operasi lama
    # (browser_login, scrape, panggilan agent) tidak memblokir pesan lain.
    async def _notify(app: Application, text: str) -> None:
        try:
            await app.bot.send_message(config.OWNER_ID, text)
        except Exception:  # noqa: BLE001
            log.exception("Gagal kirim notif")

    # ponytail: post_stop hanya jalan bila bot berhenti rapi (Ctrl+C/SIGTERM). Shutdown Windows
    # sering mematikan pythonw paksa -> notif mati tak terkirim; upgrade: scheduled task Event ID 1074.
    # Persistensi: simpan chat_data (riwayat percakapan agent) ke disk agar
    # bertahan lintas restart. bot_data tidak disimpan (berisi objek transien).
    state_dir = config.BASE_DIR / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    persistence = PicklePersistence(
        filepath=str(state_dir / "ptb_state.pkl"),
        store_data=PersistenceInput(bot_data=False, chat_data=True, user_data=False, callback_data=False),
    )
    app = (
        Application.builder().token(config.BOT_TOKEN).concurrent_updates(True)
        .persistence(persistence)
        .post_init(lambda a: _notify(a, "🟢 Laptop nyala, bot sudah berjalan."))
        .post_stop(lambda a: _notify(a, "🔴 Bot berhenti (laptop dimatikan/restart)."))
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("sys", cmd_sys))
    app.add_handler(CommandHandler("ps", cmd_ps))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("windows", cmd_windows))
    app.add_handler(CommandHandler("appshot", cmd_appshot))
    app.add_handler(CommandHandler("ls", cmd_ls))
    app.add_handler(CommandHandler("get", cmd_get))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("open", cmd_open))
    app.add_handler(CommandHandler("tabs", cmd_tabs))
    app.add_handler(CommandHandler("browser_login", cmd_browser_login))
    app.add_handler(CommandHandler("scrape", cmd_scrape))
    app.add_handler(CommandHandler("shot", cmd_shot))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("reload", cmd_reload))
    app.add_handler(CallbackQueryHandler(on_confirm, pattern=r"^cf:"))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, on_document))
    # Pesan teks biasa (bukan command) -> agent 9Router.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    if app.job_queue is not None:
        app.job_queue.run_repeating(battery_watch, interval=120, first=30)

    log.info("Bot mulai. Owner id = %s", config.OWNER_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
