"""Layer agent: bahasa natural -> LLM (9Router, OpenAI-compatible) -> tool calls.

Dua mode:
  - native : pakai function-calling bawaan OpenAI (parameter `tools`).
  - prompt : fallback bila server tidak mendukung `tools`. Model memanggil tool
             dengan membalas satu blok JSON; bot mem-parsing lalu mengeksekusi.

config.AGENT_MODE: "auto" (coba native, fallback ke prompt), "native", "prompt".
Pada mode "auto", bila panggilan native ditolak server karena tools tak didukung,
sesi otomatis beralih ke "prompt" untuk seterusnya.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from openai import OpenAI

import config
import memory_ops
import tools as tools_mod

log = logging.getLogger("agent")

SYSTEM_PROMPT = (
    "Kamu adalah agent yang mengendalikan laptop Windows 11 milik pengguna "
    "lewat Telegram. Jawab ringkas dalam Bahasa Indonesia. Gunakan tool yang "
    "tersedia untuk menjalankan tindakan di laptop; jangan mengarang hasil — "
    "selalu panggil tool untuk data nyata (status sistem, isi folder, dsb). "
    "Untuk perintah shell, panggil run_shell; konfirmasi ke pengguna ditangani "
    "oleh sistem. Kalau tool mengembalikan error, sampaikan apa adanya. "
    "Untuk mengubah kode: panggil read_file dulu agar paham isi & agar potongan "
    "'old' pada edit_file cocok persis; pakai edit_file untuk perubahan kecil dan "
    "write_file hanya untuk file baru atau penulisan ulang penuh. "
    "Untuk UPGRADE kemampuan bot sendiri tanpa restart: edit modul terkait "
    "(mis. tools.py + salah satu *_ops.py), lalu panggil reload_code dengan modul "
    "yang diubah. Periksa hasilnya: bila '✓ berhasil' berarti kode baru sudah aktif; "
    "bila '✗' berarti divalidasi gagal dan otomatis dikembalikan — perbaiki lalu ulangi. "
    "bot.py tidak bisa di-reload (perlu restart). "
    "PROSEDUR 'salin laporan dari Telegram' (bila pengguna minta ambil/salin teks pesan "
    "Telegram): 1) focus_window 'Telegram'. 2) press_keys 'esc'. 3) click_screen "
    "x=960 y=390 button=right (klik kanan pada pesan). 4) press_keys 'down' 3 kali "
    "(item ke-3 = Copy Text). 5) press_keys 'enter'. 6) read_clipboard lalu tampilkan "
    "isinya. Bila clipboard kosong atau menu salah, screenshot_window 'Telegram' lalu "
    "geser x ke kanan sedikit (jangan mentok) dan ulangi. "
    "INGATAN: kamu punya ingatan permanen. Simpan fakta penting tentang pengguna "
    "dengan remember (nama, profesi, preferensi, dsb). Bila pengguna bertanya tentang "
    "dirinya dan belum ada di ingatan, cek dokumen yang diupload: list_documents lalu "
    "read_document pada CV/berkas relevan (PDF didukung), lalu simpan poin pentingnya "
    "dengan remember agar diingat ke depannya."
)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        # Router lokal sering tak butuh key; SDK tetap minta string non-kosong.
        _client = OpenAI(
            base_url=config.ROUTER_BASE_URL,
            api_key=config.ROUTER_API_KEY or "local",
        )
    return _client


def new_history() -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _messages_with_memory(history: list[dict]) -> list[dict]:
    """Bangun daftar pesan dengan system prompt + ingatan permanen terbaru di depan."""
    mem = memory_ops.as_prompt_block()
    sys_content = SYSTEM_PROMPT + ("\n\n" + mem if mem else "")
    body = history[1:] if (history and history[0].get("role") == "system") else list(history)
    return [{"role": "system", "content": sys_content}] + body


# --- Deteksi "tools tidak didukung" -------------------------------------------

class _ToolsUnsupported(Exception):
    pass


def _is_tools_unsupported(exc: Exception) -> bool:
    """Tebak apakah error berasal dari server yang tak mendukung function-calling."""
    status = getattr(exc, "status_code", None)
    msg = str(getattr(exc, "message", "") or exc).lower()
    hints = ("tool", "function", "not support", "unsupported", "unknown parameter", "unexpected")
    if status in (400, 404, 422) and any(h in msg for h in hints):
        return True
    # Beberapa server hanya menyebut tools tanpa status jelas.
    return ("tools" in msg and ("not" in msg or "support" in msg or "invalid" in msg))


# --- Mode native --------------------------------------------------------------

def _assistant_entry(msg) -> dict:
    entry: dict = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        entry["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return entry


def _sanitize(messages: list[dict]) -> list[dict]:
    """Pastikan tiap assistant.tool_calls diikuti tool_result yang cocok & kontigu.
    Buang tool_call tanpa hasil dan tool message yatim, agar API (Anthropic lewat
    9Router) tidak menolak karena pasangan tool_use/tool_result tidak lengkap."""
    out: list[dict] = []
    i, n = 0, len(messages)
    while i < n:
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            j = i + 1
            results: dict[str, dict] = {}
            while j < n and messages[j].get("role") == "tool":
                results[messages[j].get("tool_call_id")] = messages[j]
                j += 1
            kept = [tc for tc in m["tool_calls"] if tc["id"] in results]
            if kept:
                nm = dict(m)
                nm["tool_calls"] = kept
                out.append(nm)
                out.extend(results[tc["id"]] for tc in kept)
            elif m.get("content"):
                nm = dict(m)
                nm.pop("tool_calls", None)
                out.append(nm)
            i = j
        elif m.get("role") == "tool":
            i += 1  # tool message yatim -> buang
        else:
            out.append(m)
            i += 1
    return out


async def _run_native(client: OpenAI, history: list[dict], actions) -> str:
    for step in range(config.AGENT_MAX_STEPS):
        try:
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=config.ROUTER_MODEL,
                messages=_sanitize(_messages_with_memory(history)),
                tools=tools_mod.TOOLS,
                tool_choice="auto",
            )
        except Exception as exc:  # noqa: BLE001
            # Hanya langkah pertama yang relevan untuk deteksi fallback.
            if step == 0 and _is_tools_unsupported(exc):
                raise _ToolsUnsupported() from exc
            log.exception("Panggilan native ke 9Router gagal")
            return f"❌ Gagal menghubungi 9Router: {exc}"

        msg = resp.choices[0].message
        history.append(_assistant_entry(msg))

        if not msg.tool_calls:
            return msg.content or "(tidak ada jawaban)"

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            log.info("Tool (native): %s(%s)", tc.function.name, args)
            result = await tools_mod.execute(tc.function.name, args, actions)
            history.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

    return "⚠️ Mencapai batas langkah agent. Coba perjelas permintaan."


# --- Mode prompt (fallback) ---------------------------------------------------

_FENCE = re.compile(r"```(?:tool_call|json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _tools_doc() -> str:
    lines = []
    for t in tools_mod.TOOLS:
        f = t["function"]
        params = f.get("parameters", {}).get("properties", {})
        req = set(f.get("parameters", {}).get("required", []))
        sig = ", ".join(f"{k}{'' if k in req else '?'}" for k in params) or "tanpa argumen"
        lines.append(f"- {f['name']}({sig}): {f['description']}")
    return "\n".join(lines)


def _protocol_text() -> str:
    return (
        "MODE TANPA FUNCTION-CALLING NATIVE. Untuk memanggil tool, balas HANYA "
        "dengan satu blok kode persis seperti ini, tanpa teks lain:\n"
        "```tool_call\n"
        '{"tool": "<nama_tool>", "arguments": { ... }}\n'
        "```\n"
        "Sistem akan menjalankan tool lalu mengirim balasan diawali 'HASIL TOOL'. "
        "Panggil SATU tool per langkah. Jika sudah tidak butuh tool lagi, balas "
        "dengan jawaban akhir untuk pengguna sebagai teks biasa (TANPA blok tool_call).\n\n"
        "Daftar tool:\n" + _tools_doc()
    )


def _parse_tool_call(text: str):
    """Kembalikan (nama, args) bila teks berisi panggilan tool, selainnya None."""
    if not text:
        return None
    candidates = []
    m = _FENCE.search(text)
    if m:
        candidates.append(m.group(1))
    candidates.append(text.strip())
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and "tool" in obj:
            args = obj.get("arguments")
            return obj["tool"], (args if isinstance(args, dict) else {})
    return None


def _prompt_messages(history: list[dict]) -> list[dict]:
    # system dasar (+ ingatan), lalu sisipkan protokol sebagai system kedua.
    base = _messages_with_memory(history)
    protocol = {"role": "system", "content": _protocol_text()}
    return [base[0], protocol] + base[1:]


async def _run_prompt(client: OpenAI, history: list[dict], actions) -> str:
    for _ in range(config.AGENT_MAX_STEPS):
        try:
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=config.ROUTER_MODEL,
                messages=_prompt_messages(history),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Panggilan prompt-mode ke 9Router gagal")
            return f"❌ Gagal menghubungi 9Router: {exc}"

        content = resp.choices[0].message.content or ""
        history.append({"role": "assistant", "content": content})

        parsed = _parse_tool_call(content)
        if parsed is None:
            return content or "(tidak ada jawaban)"

        name, args = parsed
        log.info("Tool (prompt): %s(%s)", name, args)
        result = await tools_mod.execute(name, args, actions)
        history.append({"role": "user", "content": f"HASIL TOOL {name}:\n{result}"})

    return "⚠️ Mencapai batas langkah agent. Coba perjelas permintaan."


# --- Entry point --------------------------------------------------------------

async def run(user_text: str, history: list[dict], actions) -> str:
    """Jalankan satu giliran agent. `history` dimutasi (riwayat percakapan chat)."""
    client = _get_client()
    history.append({"role": "user", "content": user_text})

    if config.AGENT_MODE == "prompt":
        return await _run_prompt(client, history, actions)

    if config.AGENT_MODE == "native":
        return await _run_native(client, history, actions)

    # mode "auto": coba native, fallback ke prompt bila tools ditolak.
    try:
        return await _run_native(client, history, actions)
    except _ToolsUnsupported:
        log.warning("Server menolak tools native -> beralih ke mode prompt untuk sesi ini.")
        config.AGENT_MODE = "prompt"  # kunci untuk panggilan berikutnya
        return await _run_prompt(client, history, actions)
