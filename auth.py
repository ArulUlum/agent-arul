"""Kunci pemilik: hanya OWNER_ID yang boleh memakai bot.

Semua handler dibungkus @owner_only. Pesan dari user lain diabaikan dan dicatat.
"""
from __future__ import annotations

import logging
from functools import wraps

import config

log = logging.getLogger(__name__)


def owner_only(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user = update.effective_user
        if user is None or user.id != config.OWNER_ID:
            uid = getattr(user, "id", "?")
            uname = getattr(user, "username", "?")
            log.warning("Akses ditolak untuk user id=%s username=%s", uid, uname)
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Akses ditolak. Bot ini privat.")
            return None
        return await func(update, context, *args, **kwargs)

    return wrapper
