# Bot Kendali Laptop (Telegram) + Agent

Bot Telegram self-hosted untuk mengontrol **laptop Anda sendiri** (Windows 11) dari
Telegram, dengan **mode agent** (bahasa natural → LLM via 9Router memutuskan tindakan)
dan **ingatan permanen**. Berjalan sebagai program di laptop Anda, bukan di server
orang lain.

## ⚠️ Keamanan — baca dulu

- **Token bot = kunci laptop Anda.** Siapa pun yang punya token + merupakan
  `owner_id` bisa menjalankan perintah. Jangan commit `config.json`, jangan bagikan
  token. Kalau bocor, segera revoke lewat BotFather.
- Bot **hanya merespons `owner_id`** (Telegram user id Anda). User lain diabaikan.
- Aksi berisiko (shell, tulis/edit file, ketik/klik desktop, paste+kirim) selalu
  **minta konfirmasi tombol** dulu.
- `/run` memberi akses shell penuh. Kalau tak perlu, set `"shell_enabled": false`.
- Log (`bot.log`) **menyensor** pola rahasia (password/token/bearer) otomatis.
- Jalankan hanya di laptop Anda sendiri.

## Prasyarat

- Python 3.10+ (`python --version`)
- Akun Telegram
- Endpoint LLM OpenAI-compatible (proyek ini memakai **9Router** lokal di
  `localhost:20128`, model `claude-combo`)

## Setup

Dari folder proyek:

```bash
pip install -r requirements.txt
python -m playwright install chromium
copy config.example.json config.json
```

Edit `config.json`:

```json
{
  "bot_token": "token dari BotFather",
  "owner_id": 123456789,
  "shell_enabled": true,
  "shell_timeout_sec": 30,
  "chrome_debug_url": "http://localhost:9222",
  "battery_alert_percent": 20,
  "router_base_url": "http://localhost:20128/v1",
  "router_api_key": "api key 9Router Anda",
  "router_model": "claude-combo",
  "agent_max_steps": 25,
  "agent_mode": "auto",
  "browser_profile_dir": "browser_profile",
  "browser_headless": true
}
```

- **`bot_token`** dari @BotFather; **`owner_id`** dari @userinfobot.
- **`router_api_key`** wajib diisi bila 9Router Anda menolak request tanpa key.
- Rahasia juga bisa lewat env var: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_ID`,
  `ROUTER_API_KEY`, `ROUTER_BASE_URL`, `ROUTER_MODEL`, `AGENT_MODE`.

## Jalankan

```bash
python bot.py
```

Lalu chat ke bot Anda, kirim `/start`.

### Jalan otomatis saat login Windows (tanpa admin)

```bash
powershell -ExecutionPolicy Bypass -File install_startup.ps1
```

Menaruh launcher tersembunyi di folder Startup; bot start otomatis tiap login, di
latar belakang (`pythonw`, tanpa console), log ke `bot.log`.

Skrip bantu:
- `status_bot.ps1` — cek bot nyala/mati
- `restart_bot.ps1` — stop lalu start ulang (pakai setelah mengubah `bot.py`)
- `uninstall_startup.ps1` — hapus auto-start

**Satu instance saja.** Bot mengunci port localhost `49231`; instance kedua langsung
keluar (mencegah error Telegram `Conflict`).

## Perintah

| Perintah | Fungsi |
|---|---|
| `/start`, `/help` | Bantuan |
| `/ping` | Cek bot nyala & responsif |
| `/sys` | Status CPU/RAM/disk/baterai |
| `/ps` | 10 proses pemakai RAM terbesar |
| `/screenshot` | Tangkap layar |
| `/windows` | Daftar jendela aplikasi terbuka (+ nama aplikasi) |
| `/appshot <judul>` | Screenshot jendela aplikasi (mis. Telegram/Teams) |
| `/ls <path>` | Daftar isi folder |
| `/get <path>` | Kirim file ke chat (maks 50 MB) |
| kirim file ke bot | Disimpan ke `downloads/` + otomatis diingat |
| `/run <perintah>` | Jalankan perintah cmd.exe (konfirmasi) |
| `/open <url>` | Buka URL di browser default laptop |
| `/browser_login [url]` | Login situs di profil browser bot (Drive, sosmed) |
| `/tabs` | Daftar tab Chrome (butuh mode debug) |
| `/scrape <url>` | Ambil judul + teks halaman (profil login bot) |
| `/shot <url>` | Screenshot halaman web (profil login bot) |
| `/memory [kata]` | Lihat/cari ingatan permanen |
| `/reset` | Hapus riwayat percakapan agent (ingatan tetap) |
| `/reload [modul...]` | Hot-reload kode tanpa restart (kosong = semua) |

Monitoring: bot mengirim peringatan saat baterai ≤ `battery_alert_percent` dan tidak
di-charge.

## Mode Agent (9Router)

Ketik **bahasa biasa**; LLM memutuskan tool yang dipanggil. Contoh:

- "berapa pemakaian RAM sekarang?"
- "screenshot telegram" / "lihat isi teams"
- "baca CV saya dan ceritakan tentang saya"
- "di app.py, ganti `DEBUG = True` jadi `DEBUG = False`"
- "copy laporan dari teams lalu paste ke telegram"

Pemrosesan **paralel** (pesan lain tak terblokir oleh operasi lama), dengan **kunci
per-chat** agar riwayat tidak kacau saat pesan beruntun.

**Fallback function-calling** (`agent_mode`):
- `auto` (default) — coba `tools` native; bila ditolak server, otomatis beralih ke
  **mode prompt** (model memanggil tool via blok JSON yang di-parse bot).
- `native` / `prompt` — paksa salah satu.

## Fitur

### Ingatan permanen (memory)

Bot punya ingatan yang **bertahan lintas restart** (`memory/memory.json`), otomatis
diselipkan ke konteks tiap giliran. Riwayat percakapan juga disimpan ke disk
(`state/`), jadi restart tak menghapus konteks.

- Tool agent: `remember`, `recall`, `forget`.
- File yang Anda upload otomatis diingat (nama + lokasi).
- Baca dokumen: `read_document` mendukung **PDF** (mis. CV) & file teks.
- `/memory` melihat isinya.

### Edit kode

`read_file` (baca), `edit_file` (ganti potongan presisi), `write_file` (buat/timpa).
Setiap tulis/edit **minta konfirmasi** dengan cuplikan perubahan.

### Hot-reload (upgrade tanpa restart)

Muat ulang kode yang baru diedit **tanpa mematikan proses**, dengan validasi &
rollback otomatis:
1. Validasi di namespace terisolasi (compile + import). Gagal → kode lama tetap
   dipakai, file dikembalikan ke versi baik.
2. Reload modul live.
3. Healthcheck → bila gagal, rollback otomatis.

Lewat `/reload [modul]` atau tool agent `reload_code`. Yang bisa di-reload:
`system_ops`, `file_ops`, `shell_ops`, `browser_ops`, `desktop_ops`, `memory_ops`,
`tools`, `agent`. **`bot.py` perlu restart** (handler, loop, persistensi, kunci
instance).

### Browser — situs ber-akun (Google Drive, sosmed)

Bot punya profil browser terpisah (`browser_profile/`):
1. `/browser_login` → jendela Chrome bot muncul (langsung kembali, tidak memblokir).
2. Login ke situs yang Anda mau, lalu **tutup jendelanya**.
3. `/scrape <url>` dan `/shot <url>` otomatis dalam keadaan sudah login.

Catatan:
- Scrape/screenshot pakai Chromium bawaan + **serialisasi** (satu per satu) agar
  proses chrome tidak menumpuk; jangan scrape saat jendela login masih terbuka.
- Profil menyimpan cookie sesi = **sensitif** (sudah di-`.gitignore`).
- `/tabs` butuh Chrome dijalankan dengan `--remote-debugging-port=9222`.

### Kontrol aplikasi desktop

- `list_windows` / `/windows`, `focus_window`, `screenshot_window` / `/appshot`.
- Input (konfirmasi): `type_text`, `press_keys`, `click_screen`.
- Clipboard & antar-aplikasi: `read_clipboard`, `copy_from_window`,
  `paste_to_window` (mis. salin laporan dari Teams → tempel ke Telegram).

Pencocokan jendela pakai judul **atau** nama proses (mis. `Telegram`, `teams`).

## Arsitektur file

```
bot.py        → entry point, handler Telegram, adapter media/konfirmasi, persistensi
agent.py      → loop LLM function-calling (native + fallback prompt), injeksi ingatan
tools.py      → skema tools + dispatcher ke modul *_ops
system_ops.py → status sistem & screenshot
file_ops.py   → file, baca/tulis/edit, baca dokumen (PDF)
shell_ops.py  → jalankan perintah shell
browser_ops.py→ browser default, profil login, scrape/screenshot
desktop_ops.py→ jendela aplikasi, input, clipboard
memory_ops.py → ingatan permanen
reloader.py   → hot-reload + validasi + rollback
auth.py       → owner lock
config.py     → konfigurasi
*.ps1 / *.vbs → auto-start, status, restart
```

## Lisensi / catatan

Alat pribadi. Gunakan hanya di perangkat milik sendiri.
