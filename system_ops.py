"""Info sistem & screenshot."""
from __future__ import annotations

import io
import time

import mss
import mss.tools
import psutil
from PIL import Image

_BOOT_TIME = psutil.boot_time()


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}h")
    if h:
        parts.append(f"{h}j")
    parts.append(f"{m}m")
    return " ".join(parts)


def summary() -> str:
    cpu = psutil.cpu_percent(interval=0.5)
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime = time.time() - _BOOT_TIME

    lines = [
        "🖥️ *Status Sistem*",
        f"CPU: {cpu:.0f}% ({psutil.cpu_count(logical=True)} core)",
        f"RAM: {vm.percent:.0f}% — {_fmt_bytes(vm.used)} / {_fmt_bytes(vm.total)}",
        f"Disk: {disk.percent:.0f}% — {_fmt_bytes(disk.used)} / {_fmt_bytes(disk.total)}",
        f"Uptime: {_fmt_duration(uptime)}",
    ]

    batt = psutil.sensors_battery()
    if batt is not None:
        plug = "🔌 charging" if batt.power_plugged else "🔋 baterai"
        lines.append(f"Daya: {batt.percent:.0f}% ({plug})")

    return "\n".join(lines)


def top_processes(limit: int = 10) -> str:
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
            procs.append((mem, p.info["pid"], p.info["name"] or "?"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(reverse=True)

    lines = [f"📊 *Top {limit} proses (RAM)*"]
    for mem, pid, name in procs[:limit]:
        lines.append(f"`{pid:>6}`  {_fmt_bytes(mem):>9}  {name[:30]}")
    return "\n".join(lines)


def screenshot_png() -> bytes:
    """Screenshot semua monitor digabung jadi satu PNG."""
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])  # monitor[0] = gabungan semua layar
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
