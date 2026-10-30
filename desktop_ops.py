"""Kontrol aplikasi desktop (GUI automation) — lihat & kendalikan jendela aplikasi
seperti Telegram Desktop, Teams, dll.

Melihat (aman): list_windows, focus_window, screenshot_window.
Mengendalikan (berisiko -> dikonfirmasi di sisi bot): type_text, press_keys, click.

Pencocokan jendela memakai JUDUL maupun NAMA PROSES aplikasi. Ini penting karena
banyak aplikasi (Telegram, Teams) memakai nama chat sebagai judul jendela, bukan
nama aplikasinya. Jadi 'Telegram' cocok dengan proses Telegram.exe, 'teams' dengan
ms-teams.exe, dsb.
"""
from __future__ import annotations

import ctypes
import io
import time

import mss
import psutil
import pyautogui
import pygetwindow as gw
import pyperclip
from PIL import Image

pyautogui.FAILSAFE = False

_BIDI = str.maketrans({"‎": "", "‏": "", "‪": "", "‬": ""})


def _clean(s: str) -> str:
    return (s or "").translate(_BIDI).strip()


def _pid_of(hwnd: int) -> int:
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
    return pid.value


def _proc_name(hwnd: int) -> str:
    try:
        return psutil.Process(_pid_of(hwnd)).name()
    except Exception:  # noqa: BLE001
        return ""


def list_windows() -> str:
    rows = []
    seen = set()
    for w in gw.getAllWindows():
        title = _clean(w.title)
        if not title:
            continue
        pname = _proc_name(w._hWnd)
        key = (title, pname)
        if key in seen:
            continue
        seen.add(key)
        app = f"  —  [{pname}]" if pname else ""
        rows.append(f"• {title[:80]}{app}")
    if not rows:
        return "Tidak ada jendela terlihat."
    return f"🪟 {len(rows)} jendela terbuka:\n" + "\n".join(rows)


def _find(query: str):
    q = query.strip().lower()
    cands = []
    for w in gw.getAllWindows():
        title = _clean(w.title)
        if not title:
            continue
        pname = _proc_name(w._hWnd)
        if q in title.lower() or q in pname.lower():
            cands.append(w)
    if not cands:
        return None
    # Prioritaskan jendela yang tidak terminimize & berukuran valid.
    for w in cands:
        try:
            if not w.isMinimized and w.width > 0 and w.height > 0:
                return w
        except Exception:  # noqa: BLE001
            pass
    return cands[0]


def _bring_to_front(w) -> None:
    try:
        if w.isMinimized:
            w.restore()
    except Exception:  # noqa: BLE001
        pass
    try:
        w.activate()
    except Exception:  # noqa: BLE001
        try:
            w.minimize()
            time.sleep(0.2)
            w.restore()
        except Exception:  # noqa: BLE001
            pass


def focus_window(title: str) -> str:
    w = _find(title)
    if w is None:
        return f"Jendela yang cocok dengan '{title}' tidak ditemukan. Cek /windows."
    _bring_to_front(w)
    time.sleep(0.3)
    return f"✅ Jendela difokuskan: {_clean(w.title)[:80]}"


def screenshot_window(title: str) -> bytes:
    w = _find(title)
    if w is None:
        raise ValueError(f"Jendela '{title}' tidak ditemukan. Cek /windows.")
    _bring_to_front(w)
    time.sleep(0.5)
    left, top = max(w.left, 0), max(w.top, 0)
    width, height = w.width, w.height
    if width <= 0 or height <= 0:
        raise ValueError("Ukuran jendela tidak valid (mungkin terminimize).")
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def type_text(text: str) -> str:
    pyautogui.typewrite(text, interval=0.02)
    return f"⌨️ Mengetik {len(text)} karakter ke jendela aktif."


def press_keys(keys: str) -> str:
    parts = [k.strip().lower() for k in keys.replace(" ", "").split("+") if k.strip()]
    if not parts:
        return "Tidak ada tombol."
    if len(parts) > 1:
        pyautogui.hotkey(*parts)
    else:
        pyautogui.press(parts[0])
    return f"⌨️ Menekan: {keys}"


def click(x: int, y: int, button: str = "left") -> str:
    if button not in ("left", "right", "middle"):
        return f"Tombol tidak valid: {button}"
    pyautogui.click(int(x), int(y), button=button)
    return f"🖱️ Klik {button} di ({x}, {y})."


# ---- Clipboard & copy/paste antar aplikasi ----------------------------------

def read_clipboard() -> str:
    try:
        t = pyperclip.paste()
    except Exception as exc:  # noqa: BLE001
        return f"(gagal baca clipboard: {exc})"
    return t if (t and t.strip()) else "(clipboard kosong)"


def write_clipboard(text: str) -> str:
    pyperclip.copy(text)
    return f"📋 Clipboard diisi {len(text)} karakter."


def copy_from_window(title: str) -> str:
    """Fokuskan jendela, pilih semua (Ctrl+A) & salin (Ctrl+C), kembalikan teksnya.

    Catatan: sebagian aplikasi (Teams/Telegram) hanya menyeleksi kotak ketik, bukan
    isi percakapan. Kalau hasilnya kosong/salah, pilih teks manual lalu Ctrl+C."""
    w = _find(title)
    if w is None:
        return f"Jendela '{title}' tidak ditemukan. Cek /windows."
    _bring_to_front(w)
    time.sleep(0.4)
    try:
        pyperclip.copy("")  # kosongkan dulu untuk deteksi hasil
    except Exception:  # noqa: BLE001
        pass
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.35)
    try:
        text = pyperclip.paste()
    except Exception:  # noqa: BLE001
        text = ""
    if not text or not text.strip():
        return (
            "(tidak ada teks tersalin otomatis — aplikasi mungkin tak mendukung "
            "Ctrl+A/Ctrl+C di area itu. Pilih teksnya manual lalu Ctrl+C, baru minta "
            "'paste isi clipboard ke <aplikasi>'.)"
        )
    return text if len(text) <= 4000 else text[:4000] + " … (dipotong)"


def paste_to_window(title: str, text: str = "", send: bool = False) -> str:
    """Fokuskan jendela lalu tempel (Ctrl+V). Bila `text` diisi, clipboard diset dulu.
    Bila send=True, tekan Enter setelah menempel (mengirim pesan)."""
    w = _find(title)
    if w is None:
        return f"Jendela '{title}' tidak ditemukan. Cek /windows."
    _bring_to_front(w)
    time.sleep(0.4)
    if text:
        try:
            pyperclip.copy(text)
        except Exception as exc:  # noqa: BLE001
            return f"Gagal set clipboard: {exc}"
        time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)
    if send:
        pyautogui.press("enter")
    return f"✅ Ditempel ke {_clean(w.title)[:60]}" + (" dan dikirim." if send else ".")
