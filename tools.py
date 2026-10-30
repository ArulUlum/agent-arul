"""Definisi tools untuk agent (format OpenAI function-calling) + dispatcher.

Setiap tool memetakan ke fungsi di modul *_ops yang sudah ada. Tool yang
menghasilkan gambar (screenshot) mengirim foto langsung ke chat lewat `actions`,
lalu mengembalikan teks singkat ke LLM sebagai konfirmasi.

`actions` adalah objek dengan method async:
    - send_photo(png_bytes, caption)
    - confirm(prompt) -> bool   (tombol Ya/Tidak di Telegram)
"""
from __future__ import annotations

import asyncio
from typing import Any

import browser_ops
import config
import desktop_ops
import file_ops
import memory_ops
import shell_ops
import system_ops

# Skema tools yang dikirim ke model. Deskripsi ditulis jelas agar model tahu
# kapan memakai masing-masing.
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": "Status laptop: CPU, RAM, disk, uptime, baterai.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "Daftar proses yang paling banyak memakai RAM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Jumlah proses (default 10)."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Tangkap layar laptop saat ini dan kirim ke pengguna.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Daftar isi sebuah folder di laptop.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path folder."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_file",
            "description": "Kirim sebuah file dari laptop ke pengguna lewat Telegram (maks 50 MB).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path file."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Simpan sebuah fakta PERMANEN tentang pengguna/konteks ke ingatan "
                "(bertahan selamanya, termasuk setelah restart). Contoh: nama, profesi, "
                "preferensi, poin penting dari CV, lokasi file penting. Simpan hal yang "
                "berguna diingat jangka panjang, bukan obrolan sesaat."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Fakta yang diingat, ringkas & jelas."}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Cari/lihat ingatan tersimpan (kosongkan query untuk melihat semua).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Kata kunci (opsional)."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Hapus ingatan berdasarkan id atau kata yang ada di teksnya.",
            "parameters": {
                "type": "object",
                "properties": {"target": {"type": "string", "description": "id ingatan atau kata kunci."}},
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "Daftar dokumen yang pernah diupload pengguna (folder downloads).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "Baca isi dokumen jadi teks — mendukung PDF (mis. CV) dan file teks. "
                "Pakai ini untuk membaca CV/laporan yang diupload (di folder downloads)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path file, mis. 'downloads/CV.pdf'."},
                    "max_chars": {"type": "integer", "description": "Batas karakter (default 8000)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Baca isi file teks/kode di laptop (untuk dilihat atau sebelum diedit).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path file."},
                    "max_chars": {"type": "integer", "description": "Batas karakter (default 6000)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Tulis atau timpa file di laptop dengan konten baru. Pengguna "
                "akan diminta konfirmasi. Untuk perubahan kecil, pilih edit_file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path file."},
                    "content": {"type": "string", "description": "Isi penuh file yang baru."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Edit presisi: ganti satu potongan teks lama dengan teks baru di "
                "sebuah file. Baca file dulu (read_file) agar potongan 'old' cocok "
                "persis. Pengguna akan diminta konfirmasi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path file."},
                    "old": {"type": "string", "description": "Teks lama yang akan diganti (harus cocok persis)."},
                    "new": {"type": "string", "description": "Teks pengganti."},
                    "replace_all": {"type": "boolean", "description": "Ganti semua kemunculan (default false)."},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_windows",
            "description": "Daftar jendela aplikasi desktop yang sedang terbuka (Telegram, Teams, dll).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "Fokuskan/munculkan jendela aplikasi ke depan (cocokkan sebagian judul).",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Sebagian judul jendela, mis. 'Teams'."}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_window",
            "description": "Fokuskan lalu screenshot jendela aplikasi tertentu dan kirim ke pengguna (mis. lihat isi Telegram/Teams).",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Sebagian judul jendela."}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": (
                "Ketik teks ke jendela yang sedang aktif (mis. menulis pesan). BERISIKO: "
                "pengguna dikonfirmasi dulu. Fokuskan dulu jendela yang benar (focus_window)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_keys",
            "description": (
                "Tekan tombol/pintasan di jendela aktif, mis. 'enter' (mengirim pesan), "
                "'ctrl+a', 'win+r'. BERISIKO: pengguna dikonfirmasi dulu."
            ),
            "parameters": {
                "type": "object",
                "properties": {"keys": {"type": "string", "description": "mis. 'enter' atau 'ctrl+a'."}},
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_screen",
            "description": "Klik di koordinat layar (x,y); button left (default) atau right (menu konteks). BERISIKO: pengguna dikonfirmasi dulu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Default left."},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_clipboard",
            "description": "Baca teks yang ada di clipboard (papan tempel) sekarang.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_from_window",
            "description": (
                "Fokuskan jendela aplikasi lalu salin isinya (Ctrl+A, Ctrl+C) dan "
                "kembalikan teksnya. Berguna untuk ambil teks dari Teams/Telegram. "
                "Catatan: sebagian aplikasi hanya menyeleksi kotak ketik; bila kosong, "
                "pengguna perlu memilih teks manual lalu Ctrl+C."
            ),
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Sebagian judul/nama aplikasi."}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "paste_to_window",
            "description": (
                "Tempel teks ke jendela aplikasi (mis. kirim isi laporan ke Telegram). "
                "Bila 'text' diisi, itu yang ditempel; bila kosong, menempel isi clipboard "
                "saat ini. send=true akan menekan Enter (mengirim). BERISIKO: dikonfirmasi dulu."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Aplikasi tujuan, mis. 'Telegram'."},
                    "text": {"type": "string", "description": "Teks yang ditempel (kosong = pakai isi clipboard)."},
                    "send": {"type": "boolean", "description": "true = tekan Enter setelah menempel (mengirim)."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reload_code",
            "description": (
                "Hot-reload modul kode bot yang baru diedit, TANPA restart. "
                "Divalidasi dulu; kalau kode baru rusak, perubahan TIDAK diterapkan "
                "(bot tetap jalan dengan kode lama) dan hasilnya melaporkan errornya. "
                "Modul yang bisa: system_ops, file_ops, shell_ops, browser_ops, tools, "
                "agent. Kosongkan 'modules' untuk reload semua. bot.py tidak bisa "
                "hot-reload (perlu restart)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "modules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Nama modul yang diedit; kosong = reload semua.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Jalankan perintah shell (cmd.exe) di laptop. BERISIKO: pengguna "
                "akan dimintai konfirmasi dulu. Pakai hanya bila perintah eksplisit dibutuhkan."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Perintah yang dijalankan."}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Buka sebuah URL di browser default laptop pengguna.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_browser_tabs",
            "description": "Daftar tab Chrome yang terbuka (butuh Chrome mode remote-debugging).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_login",
            "description": (
                "Buka jendela browser bot (TERLIHAT) di laptop supaya pengguna login "
                "ke situs yang butuh akun (Google Drive, Twitter/X, Instagram, Facebook, "
                "dll). Setelah pengguna login lalu menutup jendela, cookie tersimpan di "
                "profil bot, dan scrape_url/screenshot_url jadi dalam keadaan SUDAH LOGIN. "
                "Panggil ini bila situs yang diminta butuh login dan belum pernah login. "
                "Opsional 'url' = halaman awal yang dibuka."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Halaman awal (default google.com)."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_url",
            "description": (
                "Buka URL memakai profil browser bot (SUDAH LOGIN bila pengguna pernah "
                "browser_login), kembalikan judul + teks halaman. Untuk situs berakun, "
                "pastikan sudah browser_login dulu."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_url",
            "description": (
                "Buka URL memakai profil browser bot (SUDAH LOGIN bila pengguna pernah "
                "browser_login) dan kirim screenshot halaman ke pengguna."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]


async def execute(name: str, args: dict[str, Any], actions) -> str:
    """Jalankan satu tool call. Selalu mengembalikan string untuk dikirim balik ke LLM."""
    try:
        if name == "get_system_status":
            return await asyncio.to_thread(system_ops.summary)

        if name == "list_processes":
            limit = int(args.get("limit", 10))
            return await asyncio.to_thread(system_ops.top_processes, limit)

        if name == "take_screenshot":
            png = await asyncio.to_thread(system_ops.screenshot_png)
            await actions.send_photo(png, caption="🖥️ Layar sekarang")
            return "Screenshot sudah dikirim ke pengguna."

        if name == "list_directory":
            return await asyncio.to_thread(file_ops.list_dir, args["path"])

        if name == "send_file":
            try:
                path = await asyncio.to_thread(file_ops.resolve_for_send, args["path"])
            except ValueError as exc:
                return f"Gagal: {exc}"
            await actions.send_document(path)
            return f"File {path.name} sudah dikirim ke pengguna."

        if name == "remember":
            return await asyncio.to_thread(memory_ops.remember, args.get("text", ""))

        if name == "recall":
            return await asyncio.to_thread(memory_ops.recall, args.get("query", ""))

        if name == "forget":
            return await asyncio.to_thread(memory_ops.forget, args.get("target", ""))

        if name == "list_documents":
            return await asyncio.to_thread(file_ops.list_documents)

        if name == "read_document":
            max_chars = int(args.get("max_chars", 8000))
            return await asyncio.to_thread(file_ops.read_document, args["path"], max_chars)

        if name == "read_file":
            max_chars = int(args.get("max_chars", 6000))
            return await asyncio.to_thread(file_ops.read_text, args["path"], max_chars)

        if name == "write_file":
            path = args["path"]
            content = args.get("content", "")
            # ponytail: batas pesan Telegram 4096; sisa ditandai eksplisit. Lebih panjang -> kirim sebagai file.
            preview = content[:3000]
            cut = f"\n\n⚠️ {len(content) - 3000} karakter TIDAK ditampilkan." if len(content) > 3000 else ""
            ok = await actions.confirm(
                f"Tulis/timpa file:\n{path}\n({len(content)} karakter)\n\nIsi:\n{preview}{cut}"
            )
            if not ok:
                return "Pengguna MENOLAK menulis file. Jangan ditulis."
            return await asyncio.to_thread(file_ops.write_text, path, content)

        if name == "edit_file":
            path = args["path"]
            old = args.get("old", "")
            new = args.get("new", "")
            replace_all = bool(args.get("replace_all", False))
            # ponytail: batas pesan Telegram 4096; sisa ditandai eksplisit.
            old_prev, new_prev = old[:1400], new[:1400]
            cut = ""
            if len(old) > 1400 or len(new) > 1400:
                cut = f"\n\n⚠️ Sebagian TIDAK ditampilkan (old {len(old)}, new {len(new)} karakter)."
            ok = await actions.confirm(
                f"Edit file:\n{path}\n\nGANTI:\n{old_prev}\n\nMENJADI:\n{new_prev}{cut}"
            )
            if not ok:
                return "Pengguna MENOLAK edit file. Jangan diubah."
            return await asyncio.to_thread(file_ops.edit_text, path, old, new, replace_all)

        if name == "list_windows":
            return await asyncio.to_thread(desktop_ops.list_windows)

        if name == "focus_window":
            return await asyncio.to_thread(desktop_ops.focus_window, args["title"])

        if name == "screenshot_window":
            try:
                png = await asyncio.to_thread(desktop_ops.screenshot_window, args["title"])
            except Exception as exc:  # noqa: BLE001
                return f"Gagal screenshot jendela: {exc}"
            await actions.send_photo(png, caption=f"🪟 {args['title']}")
            return "Screenshot jendela sudah dikirim ke pengguna."

        if name == "type_text":
            text = args.get("text", "")
            ok = await actions.confirm(f"Ketik teks ini ke jendela aktif?\n\n{text}")
            if not ok:
                return "Pengguna MENOLAK mengetik. Jangan diketik."
            return await asyncio.to_thread(desktop_ops.type_text, text)

        if name == "press_keys":
            keys = args.get("keys", "")
            ok = await actions.confirm(f"Tekan tombol '{keys}' di jendela aktif?")
            if not ok:
                return "Pengguna MENOLAK. Jangan ditekan."
            return await asyncio.to_thread(desktop_ops.press_keys, keys)

        if name == "click_screen":
            x, y = args.get("x"), args.get("y")
            button = args.get("button", "left")
            ok = await actions.confirm(f"Klik {button} di layar koordinat ({x}, {y})?")
            if not ok:
                return "Pengguna MENOLAK klik."
            return await asyncio.to_thread(desktop_ops.click, x, y, button)

        if name == "read_clipboard":
            return await asyncio.to_thread(desktop_ops.read_clipboard)

        if name == "copy_from_window":
            return await asyncio.to_thread(desktop_ops.copy_from_window, args["title"])

        if name == "paste_to_window":
            title = args["title"]
            text = args.get("text", "")
            send = bool(args.get("send", False))
            preview = (text[:200] + "…") if len(text) > 200 else (text or "(isi clipboard saat ini)")
            tail = " dan DIKIRIM (Enter)" if send else ""
            ok = await actions.confirm(f"Tempel ke '{title}'{tail}?\n\n{preview}")
            if not ok:
                return "Pengguna MENOLAK paste."
            return await asyncio.to_thread(desktop_ops.paste_to_window, title, text, send)

        if name == "reload_code":
            import reloader

            mods = args.get("modules") or None
            return await asyncio.to_thread(reloader.reload, mods)

        if name == "run_shell":
            command = args.get("command", "")
            if not config.SHELL_ENABLED:
                return "Shell dinonaktifkan di config."
            ok = await actions.confirm(f"Jalankan perintah ini?\n\n{command}")
            if not ok:
                return "Pengguna MENOLAK menjalankan perintah. Jangan dijalankan."
            return await shell_ops.run(command)

        if name == "open_url":
            return await asyncio.to_thread(browser_ops.open_url, args["url"])

        if name == "list_browser_tabs":
            return await asyncio.to_thread(browser_ops.list_chrome_tabs)

        if name == "browser_login":
            await actions.send_text(
                "🌐 Membuka jendela browser bot di laptop. Silakan login ke situs yang "
                "Anda mau (Google, sosmed, dll), lalu TUTUP jendelanya kalau selesai."
            )
            start = args.get("url") or "https://www.google.com"
            return await asyncio.to_thread(browser_ops.open_login_window, start)

        if name == "scrape_url":
            return await asyncio.to_thread(browser_ops.scrape, args["url"])

        if name == "screenshot_url":
            png = await asyncio.to_thread(browser_ops.screenshot_url, args["url"])
            await actions.send_photo(png, caption=args["url"])
            return "Screenshot halaman sudah dikirim ke pengguna."

        return f"Tool tidak dikenal: {name}"
    except Exception as exc:  # noqa: BLE001
        return f"Error saat menjalankan {name}: {exc}"
