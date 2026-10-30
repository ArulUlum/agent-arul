"""Operasi browser.

Tiga jenis:
1. Browser default Anda (open_url, list_chrome_tabs) — mengontrol Chrome yang
   sedang Anda pakai. list_chrome_tabs butuh Chrome --remote-debugging-port=9222.
2. PROFIL BROWSER BOT (persisten) — Chromium/Chrome terpisah milik bot dengan
   folder profil sendiri (config.BROWSER_PROFILE_DIR). Anda login sekali lewat
   open_login_window(); cookie semua situs (Google Drive, sosmed, dll) tersimpan
   di situ, lalu scrape()/screenshot_url() memakai profil itu -> sudah login.
3. (profil bot juga dipakai untuk scrape/screenshot agar konten yang butuh login
   bisa diakses.)

Fungsi Playwright memakai sync API dan dimaksudkan dipanggil via asyncio.to_thread
dari sisi bot, agar tidak bentrok dengan event loop utama. Profil persisten hanya
boleh dibuka SATU proses pada satu waktu (login window vs scrape tidak boleh
bersamaan) — bila terkunci, fungsi memberi pesan yang jelas.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import webbrowser

import requests

import config

# Serialisasi semua operasi Playwright di profil bot: cegah dua chrome sekaligus
# di satu profil (yang menyebabkan proses chrome yatim menumpuk).
_BROWSER_LOCK = threading.Lock()

PROFILE_BUSY_MSG = (
    "🔒 Profil browser bot sedang dipakai (mungkin jendela login masih terbuka). "
    "Tutup dulu jendela itu, lalu coba lagi."
)


# ---- Browser default (milik Anda) --------------------------------------------

def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    ok = webbrowser.open(url)
    return f"🌐 Membuka di browser default: {url}" if ok else "❌ Gagal membuka browser."


def list_chrome_tabs() -> str:
    try:
        resp = requests.get(f"{config.CHROME_DEBUG_URL}/json/list", timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return (
            "❌ Tidak bisa membaca tab Chrome.\n"
            "Pastikan Chrome dijalankan dengan:\n"
            "`chrome.exe --remote-debugging-port=9222`"
        )
    tabs = [t for t in data if t.get("type") == "page"]
    if not tabs:
        return "Tidak ada tab terbuka."
    lines = [f"🗂️ *{len(tabs)} tab terbuka*"]
    for i, t in enumerate(tabs[:40], 1):
        title = (t.get("title") or "(tanpa judul)")[:60]
        url = (t.get("url") or "")[:80]
        lines.append(f"{i}. {title}\n   {url}")
    return "\n".join(lines)


# ---- Profil browser bot (persisten, logged-in) -------------------------------

def _normalize(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _is_profile_locked(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("singletonlock", "processsingleton", "in use", "already running", "cannot create", "profile"))


def _launch_persistent(p, headless: bool):
    """Buka persistent context memakai Chromium BAWAAN Playwright di profil bot.

    Sengaja TIDAK memakai channel='chrome': Chrome asli melakukan 'singleton
    handoff' saat profil sudah dipakai, sehingga ctx.close() tak membunuh prosesnya
    -> chrome yatim menumpuk. Chromium bawaan justru gagal bersih bila profil
    terkunci (ditangkap sebagai PROFILE_BUSY). Sidik jari otomasi dibuang agar
    situs ber-login tetap ramah."""
    return p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )


_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def _chrome_path():
    for p in _CHROME_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return shutil.which("chrome") or shutil.which("chrome.exe")


def open_login_window(start_url: str = "https://www.google.com") -> str:
    """Buka jendela Chrome ASLI (bukan otomasi) pada profil bot, lalu LANGSUNG kembali
    (tidak memblokir). Pengguna login & menutup jendela sendiri; cookie tersimpan di
    profil, dipakai scrape/screenshot berikutnya. Memakai Chrome manual = paling ramah
    login Google (tanpa sidik jari otomasi)."""
    start_url = _normalize(start_url)
    chrome = _chrome_path()
    if not chrome:
        return "❌ Chrome tidak ditemukan untuk jendela login."
    try:
        subprocess.Popen(
            [
                chrome,
                f"--user-data-dir={config.BROWSER_PROFILE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
                start_url,
            ],
            creationflags=0x00000008,  # DETACHED_PROCESS: mandiri dari proses bot
        )
    except Exception as exc:  # noqa: BLE001
        return f"❌ Gagal membuka jendela login: {exc}"
    return (
        "🌐 Jendela browser bot dibuka di laptop. Silakan login ke situs yang Anda mau, "
        "lalu TUTUP jendelanya kalau selesai. Cookie tersimpan; setelah ditutup, "
        "scrape/screenshot sudah dalam keadaan login. (Jangan scrape saat jendela ini "
        "masih terbuka — profil sedang dipakai.)"
    )


def scrape(url: str) -> str:
    """Buka URL memakai profil bot (sudah login), kembalikan judul + teks halaman."""
    from playwright.sync_api import sync_playwright

    url = _normalize(url)
    with _BROWSER_LOCK:
        with sync_playwright() as p:
            try:
                ctx = _launch_persistent(p, headless=config.BROWSER_HEADLESS)
            except Exception as exc:  # noqa: BLE001
                if _is_profile_locked(exc):
                    return PROFILE_BUSY_MSG
                raise
            try:
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                title = page.title()
                text = page.inner_text("body")
            finally:
                ctx.close()

    text = " ".join(text.split())
    if len(text) > 3000:
        text = text[:3000] + " … (dipotong)"
    return f"🔎 {title}\n{url}\n\n{text}"


def screenshot_url(url: str) -> bytes:
    """Buka URL memakai profil bot (sudah login), kembalikan screenshot PNG."""
    from playwright.sync_api import sync_playwright

    url = _normalize(url)
    with _BROWSER_LOCK:
        with sync_playwright() as p:
            try:
                ctx = _launch_persistent(p, headless=config.BROWSER_HEADLESS)
            except Exception as exc:  # noqa: BLE001
                if _is_profile_locked(exc):
                    raise RuntimeError(PROFILE_BUSY_MSG) from exc
                raise
            try:
                page = ctx.new_page()
                page.set_viewport_size({"width": 1280, "height": 900})
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1500)
                return page.screenshot(full_page=True)
            finally:
                ctx.close()
