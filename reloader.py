"""Hot-reload modul kode bot tanpa restart, dengan validasi & rollback.

Gaya kerja (aman seperti Hermes):
  - Saat bot start, snapshot() menyimpan sumber "versi baik terakhir" tiap modul.
  - reload():
      1. Validasi sumber baru di namespace TERISOLASI (compile + exec_module).
      2. Bila valid -> importlib.reload modul live.
      3. Healthcheck: atribut penting masih ada & benar.
      Bila langkah mana pun GAGAL -> kembalikan file ke versi baik terakhir dan
      muat ulang, sehingga disk + memori selalu berisi kode yang pasti jalan.
  - Setiap sukses memperbarui snapshot "versi baik".

Hanya modul "logika" yang aman di-reload (dipanggil via atribut saat runtime).
bot.py sendiri (handler, loop, kunci instance) TIDAK bisa hot-reload -> perlu restart.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path

log = logging.getLogger("reloader")

RELOAD_ORDER = ["system_ops", "file_ops", "shell_ops", "browser_ops", "desktop_ops", "memory_ops", "tools", "agent"]
RELOADABLE = set(RELOAD_ORDER)

# Sumber (bytes) versi baik terakhir per modul. Diisi snapshot() saat bot start,
# diperbarui setiap reload sukses.
_GOOD: dict[str, bytes] = {}

_HEALTH = {
    "system_ops": lambda m: callable(getattr(m, "summary", None))
    and callable(getattr(m, "screenshot_png", None)),
    "file_ops": lambda m: callable(getattr(m, "read_text", None))
    and callable(getattr(m, "edit_text", None)),
    "shell_ops": lambda m: callable(getattr(m, "run", None)),
    "browser_ops": lambda m: callable(getattr(m, "open_url", None))
    and callable(getattr(m, "scrape", None)),
    "desktop_ops": lambda m: callable(getattr(m, "list_windows", None))
    and callable(getattr(m, "screenshot_window", None)),
    "memory_ops": lambda m: callable(getattr(m, "remember", None))
    and callable(getattr(m, "as_prompt_block", None)),
    "tools": lambda m: isinstance(getattr(m, "TOOLS", None), list)
    and len(m.TOOLS) > 0
    and callable(getattr(m, "execute", None)),
    "agent": lambda m: callable(getattr(m, "run", None)),
}


def snapshot(names: list[str] | None = None) -> None:
    """Simpan sumber modul yang sedang berjalan sebagai 'versi baik'. Panggil saat start."""
    for name in (names or RELOAD_ORDER):
        mod = sys.modules.get(name)
        path = getattr(mod, "__file__", None) if mod else None
        if path and Path(path).exists():
            _GOOD[name] = Path(path).read_bytes()
    log.info("Snapshot kode-baik tersimpan untuk: %s", ", ".join(sorted(_GOOD)))


def _probe(name: str, path: str) -> None:
    """Muat sumber di namespace terisolasi untuk menangkap error sebelum reload live."""
    src = Path(path).read_text(encoding="utf-8")
    compile(src, path, "exec")  # SyntaxError lebih dini & jelas
    spec = importlib.util.spec_from_file_location(f"_probe_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # error import / top-level


def _restore(name: str, path: str, mod) -> bool:
    """Tulis balik versi baik ke disk lalu reload. True bila ada yang dipulihkan."""
    good = _GOOD.get(name)
    if good is None:
        return False
    if Path(path).read_bytes() != good:
        Path(path).write_bytes(good)
    importlib.reload(mod)
    return True


def _reload_one(name: str) -> str:
    if name not in RELOADABLE:
        return f"• {name}: ✗ bukan modul yang bisa di-reload"
    mod = sys.modules.get(name)
    if mod is None:
        return f"• {name}: ✗ belum dimuat"
    path = getattr(mod, "__file__", None)
    if not path:
        return f"• {name}: ✗ path tidak diketahui"

    no_backup = _GOOD.get(name) is None

    # 1) Validasi terisolasi.
    try:
        _probe(name, path)
    except Exception as exc:  # noqa: BLE001
        restored = _restore(name, path, mod)
        tail = "dikembalikan ke versi baik" if restored else "kode lama di memori tetap dipakai (tanpa snapshot)"
        return f"• {name}: ✗ GAGAL validasi ({type(exc).__name__}: {str(exc)[:160]}). {tail}."

    # 2) Reload live.
    try:
        importlib.reload(mod)
    except Exception as exc:  # noqa: BLE001
        restored = _restore(name, path, mod)
        tail = "sudah di-ROLLBACK" if restored else "TANPA snapshot, disarankan restart"
        return f"• {name}: ✗ reload gagal ({type(exc).__name__}: {str(exc)[:160]}). {tail}."

    # 3) Healthcheck.
    check = _HEALTH.get(name)
    if check is not None and not check(mod):
        restored = _restore(name, path, mod)
        tail = "sudah di-ROLLBACK ke kode lama" if restored else "TANPA snapshot, disarankan restart"
        return f"• {name}: ✗ healthcheck gagal. {tail}."

    # Sukses -> perbarui snapshot versi baik.
    _GOOD[name] = Path(path).read_bytes()
    warn = " (catatan: snapshot awal belum ada, baru dibuat sekarang)" if no_backup else ""
    return f"• {name}: ✓ berhasil di-reload{warn}"


def reload(modules: list[str] | None = None) -> str:
    """Reload daftar modul (atau semua yang bisa). Kembalikan ringkasan teks."""
    if modules:
        unknown = [m for m in modules if m not in RELOADABLE]
        if unknown:
            return (
                "Tidak bisa reload: " + ", ".join(unknown) + ".\n"
                "Yang bisa di-reload: " + ", ".join(RELOAD_ORDER) + ".\n"
                "(bot.py butuh restart penuh, tidak bisa hot-reload.)"
            )
        order = [m for m in RELOAD_ORDER if m in modules]
    else:
        order = list(RELOAD_ORDER)

    lines = [_reload_one(name) for name in order]
    ok = sum(1 for ln in lines if "✓" in ln)
    return f"♻️ Hot-reload: {ok}/{len(lines)} modul berhasil.\n" + "\n".join(lines)
