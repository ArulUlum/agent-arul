"""Operasi file: daftar isi folder & siapkan path untuk kirim/terima."""
from __future__ import annotations

from pathlib import Path

import config


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


def list_dir(path_str: str) -> str:
    path = Path(path_str).expanduser()
    if not path.exists():
        return f"❌ Tidak ada: {path}"
    if not path.is_dir():
        return f"❌ Bukan folder: {path}"

    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines = [f"📁 `{path}`"]
    for e in entries[:200]:
        try:
            if e.is_dir():
                lines.append(f"📂 {e.name}/")
            else:
                lines.append(f"📄 {e.name}  ({_fmt_size(e.stat().st_size)})")
        except OSError:
            lines.append(f"⚠️ {e.name}  (tidak terbaca)")
    if len(entries) > 200:
        lines.append(f"… dan {len(entries) - 200} item lain (dipotong).")
    return "\n".join(lines)


def resolve_for_send(path_str: str) -> Path:
    """Validasi path file yang akan dikirim. Melempar ValueError kalau tidak valid."""
    path = Path(path_str).expanduser()
    if not path.exists():
        raise ValueError(f"File tidak ditemukan: {path}")
    if not path.is_file():
        raise ValueError(f"Bukan file: {path}")
    # Batas aman Bot API untuk mengirim dokumen = 50 MB.
    size = path.stat().st_size
    if size > 50 * 1024 * 1024:
        raise ValueError(f"File terlalu besar ({_fmt_size(size)}). Maks 50 MB via bot.")
    return path


def read_text(path_str: str, max_chars: int = 6000) -> str:
    """Baca isi file teks. Dipotong bila melebihi max_chars."""
    path = Path(path_str).expanduser()
    if not path.exists():
        raise ValueError(f"File tidak ditemukan: {path}")
    if not path.is_file():
        raise ValueError(f"Bukan file: {path}")
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError(f"File terlalu besar untuk dibaca (>2 MB): {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"File bukan teks / encoding tidak didukung: {path}") from exc
    if len(text) > max_chars:
        return text[:max_chars] + f"\n… (dipotong; total {len(text)} karakter)"
    return text


def write_text(path_str: str, content: str) -> str:
    """Tulis/timpa file teks. Folder induk dibuat otomatis bila belum ada."""
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(content, encoding="utf-8", newline="")
    verb = "Menimpa" if existed else "Membuat"
    return f"{verb} {path} ({len(content)} karakter)."


def edit_text(path_str: str, old: str, new: str, replace_all: bool = False) -> str:
    """Ganti potongan teks di file (mirip find & replace presisi).

    Kalau `old` tidak ditemukan -> error (tidak menulis apa-apa).
    Kalau `old` muncul >1 kali dan replace_all=False -> error (minta konteks unik).
    """
    path = Path(path_str).expanduser()
    if not path.is_file():
        raise ValueError(f"File tidak ditemukan: {path}")
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ValueError("Teks lama tidak ditemukan di file; tidak ada yang diubah.")
    if count > 1 and not replace_all:
        raise ValueError(
            f"Teks lama muncul {count} kali. Beri potongan yang lebih unik, "
            "atau set replace_all=true untuk ganti semua."
        )
    new_text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    path.write_text(new_text, encoding="utf-8", newline="")
    n = count if replace_all else 1
    return f"OK: {n} penggantian di {path}."


def read_document(path_str: str, max_chars: int = 8000) -> str:
    """Baca isi dokumen jadi teks. Mendukung PDF (pypdf) dan file teks biasa."""
    path = Path(path_str).expanduser()
    if not path.exists():
        raise ValueError(f"File tidak ditemukan: {path}")
    if not path.is_file():
        raise ValueError(f"Bukan file: {path}")

    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        text = "\n".join(parts).strip()
        if not text:
            return "(PDF tidak mengandung teks terbaca — mungkin hasil scan/gambar; perlu OCR.)"
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Format tidak didukung untuk dibaca sebagai teks: {ext}") from exc

    text = " ".join(text.split())
    if len(text) > max_chars:
        return text[:max_chars] + f"\n… (dipotong; total ~{len(text)} karakter)"
    return text


def list_documents() -> str:
    """Daftar file di folder downloads (tempat file yang diupload ke bot disimpan)."""
    d = config.DOWNLOAD_DIR
    files = sorted([p for p in d.iterdir() if p.is_file()], key=lambda p: p.name.lower())
    if not files:
        return "Belum ada dokumen di folder downloads."
    lines = [f"📂 Dokumen di {d}:"]
    for p in files:
        lines.append(f"• {p.name}  ({_fmt_size(p.stat().st_size)})")
    return "\n".join(lines)


def download_path_for(filename: str) -> Path:
    """Path tujuan simpan untuk file yang di-upload ke bot (nama di-sanitasi)."""
    safe = Path(filename).name  # buang komponen direktori, cegah path traversal
    if not safe:
        safe = "upload.bin"
    return config.DOWNLOAD_DIR / safe
