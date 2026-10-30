"""Ingatan permanen bot: fakta tentang pengguna/konteks yang bertahan lintas restart.

Disimpan di memory/memory.json. Fakta yang tersimpan otomatis diselipkan ke konteks
agent setiap giliran (lewat agent._messages_with_memory), jadi bot selalu 'ingat'.
Agent juga punya tool remember/recall/forget untuk mengelola sendiri.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import config

MEM_DIR = config.BASE_DIR / "memory"
MEM_FILE = MEM_DIR / "memory.json"


def _load() -> list[dict]:
    if MEM_FILE.exists():
        try:
            return json.loads(MEM_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []
    return []


def _save(items: list[dict]) -> None:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    MEM_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def remember(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "Tidak ada yang diingat (teks kosong)."
    items = _load()
    # Hindari duplikat persis.
    if any(m["text"] == text for m in items):
        return "ℹ️ Sudah ada di ingatan."
    mid = (max((m.get("id", 0) for m in items), default=0) + 1)
    items.append({"id": mid, "text": text, "ts": time.strftime("%Y-%m-%d")})
    _save(items)
    return f"🧠 Diingat [{mid}]: {text[:120]}"


def recall(query: str = "") -> str:
    items = _load()
    if query:
        q = query.lower()
        items = [m for m in items if q in m["text"].lower()]
    if not items:
        return "(tidak ada ingatan yang cocok)"
    return "\n".join(f"- [{m['id']}] ({m.get('ts','')}) {m['text']}" for m in items[-80:])


def forget(target: str) -> str:
    items = _load()
    n = len(items)
    t = str(target).strip().lower()
    kept = [m for m in items if str(m["id"]) != t and t not in m["text"].lower()]
    _save(kept)
    removed = n - len(kept)
    return f"🗑️ Menghapus {removed} ingatan." if removed else "Tidak ada ingatan yang cocok."


def as_prompt_block(limit: int = 50) -> str:
    """Blok teks ingatan untuk diselipkan ke system prompt agent."""
    items = _load()
    if not items:
        return ""
    lines = [f"- {m['text']}" for m in items[-limit:]]
    return "INGATAN TERSIMPAN (fakta tentang pengguna/konteks, pakai bila relevan):\n" + "\n".join(lines)
