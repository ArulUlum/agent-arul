"""Menjalankan perintah shell (cmd.exe di Windows) dengan timeout.

PERINGATAN: ini memberi kendali shell penuh atas laptop Anda kepada siapa pun
yang memegang token + merupakan OWNER_ID. Jangan pernah bagikan token bot.
Bisa dimatikan lewat config: "shell_enabled": false.
"""
from __future__ import annotations

import asyncio

import config


async def run(command: str) -> str:
    if not config.SHELL_ENABLED:
        return "🚫 Perintah shell dinonaktifkan di config (shell_enabled=false)."

    command = command.strip()
    if not command:
        return "Pakai: /run <perintah>"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return f"❌ Gagal menjalankan: {exc}"

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=config.SHELL_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        # /T = bunuh juga proses anak; proc.kill() sendiri hanya membunuh cmd.exe.
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/F", "/T", "/PID", str(proc.pid),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
        return f"⏱️ Timeout setelah {config.SHELL_TIMEOUT_SEC}s. Proses dan anak-anaknya dihentikan."

    out = stdout.decode("utf-8", errors="replace") if stdout else ""
    # ``` di output menutup blok kode Markdown lebih awal -> Telegram gagal parse.
    out = out.replace("```", "'''").strip() or "(tidak ada output)"

    # Batas pesan Telegram ~4096 char; sisakan ruang untuk format.
    if len(out) > 3500:
        out = out[:3500] + "\n… (dipotong)"

    return f"exit={proc.returncode}\n```\n{out}\n```"
