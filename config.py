"""Konfigurasi bot: dibaca dari config.json, dengan override dari environment variable.

Prioritas: environment variable > config.json > default.
Token & owner_id WAJIB terisi, kalau tidak bot menolak jalan.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = BASE_DIR / "config.json"

_DEFAULTS = {
    "bot_token": "",
    "owner_id": 0,
    "download_dir": "downloads",
    "shell_enabled": True,
    "shell_timeout_sec": 30,
    "chrome_debug_url": "http://localhost:9222",
    "battery_alert_percent": 20,
    "router_base_url": "http://localhost:20128/v1",
    "router_api_key": "",
    "router_model": "claude-combo",
    "agent_max_steps": 25,
    "agent_mode": "auto",
    "browser_profile_dir": "browser_profile",
    "browser_headless": True,
}


def _load() -> dict:
    data = dict(_DEFAULTS)
    if _CONFIG_PATH.exists():
        with _CONFIG_PATH.open(encoding="utf-8") as fh:
            data.update(json.load(fh))

    # Override dari environment variable (berguna agar token tidak tersimpan di file).
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        data["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_OWNER_ID"):
        data["owner_id"] = int(os.environ["TELEGRAM_OWNER_ID"])
    if os.environ.get("ROUTER_API_KEY"):
        data["router_api_key"] = os.environ["ROUTER_API_KEY"]
    if os.environ.get("ROUTER_BASE_URL"):
        data["router_base_url"] = os.environ["ROUTER_BASE_URL"]
    if os.environ.get("ROUTER_MODEL"):
        data["router_model"] = os.environ["ROUTER_MODEL"]
    if os.environ.get("AGENT_MODE"):
        data["agent_mode"] = os.environ["AGENT_MODE"]

    return data


_cfg = _load()

BOT_TOKEN: str = _cfg["bot_token"]
OWNER_ID: int = int(_cfg["owner_id"])
SHELL_ENABLED: bool = bool(_cfg["shell_enabled"])
SHELL_TIMEOUT_SEC: int = int(_cfg["shell_timeout_sec"])
CHROME_DEBUG_URL: str = str(_cfg["chrome_debug_url"]).rstrip("/")
BATTERY_ALERT_PERCENT: int = int(_cfg["battery_alert_percent"])

ROUTER_BASE_URL: str = str(_cfg["router_base_url"]).rstrip("/")
ROUTER_API_KEY: str = str(_cfg["router_api_key"])
ROUTER_MODEL: str = str(_cfg["router_model"])
AGENT_MAX_STEPS: int = int(_cfg["agent_max_steps"])
# "auto" = coba tools native dulu, fallback ke prompt bila ditolak server.
# "native" = paksa function-calling native. "prompt" = paksa mode prompt JSON.
AGENT_MODE: str = str(_cfg["agent_mode"]).lower()
# 9Router lokal Anda WAJIB API key (tes menunjukkan 401 "Missing API key"
# tanpa key). Agent aktif hanya bila base_url, model, dan key terisi.
AGENT_ENABLED: bool = (
    bool(ROUTER_BASE_URL)
    and bool(ROUTER_MODEL)
    and bool(ROUTER_API_KEY)
    and not ROUTER_API_KEY.startswith("GANTI_")
)

DOWNLOAD_DIR: Path = (BASE_DIR / _cfg["download_dir"]).resolve()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Profil persisten browser bot (menyimpan cookie login semua situs — SENSITIF).
BROWSER_PROFILE_DIR: Path = (BASE_DIR / _cfg["browser_profile_dir"]).resolve()
BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_HEADLESS: bool = bool(_cfg["browser_headless"])


def validate() -> None:
    if not BOT_TOKEN or BOT_TOKEN.startswith("GANTI_"):
        raise SystemExit(
            "bot_token belum diisi. Salin config.example.json -> config.json "
            "lalu isi token dari BotFather (atau set env TELEGRAM_BOT_TOKEN)."
        )
    if OWNER_ID <= 0:
        raise SystemExit(
            "owner_id belum diisi. Isi dengan Telegram user id Anda "
            "(atau set env TELEGRAM_OWNER_ID). Cara dapat id: chat ke @userinfobot."
        )
