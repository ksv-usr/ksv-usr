from __future__ import annotations

import re
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional

import aiohttp
import discord


_INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_URL_RE = re.compile(r'https?://[^\s<>"\']+')

LogFn = Callable[[str], None]


def safe_name(name: str, max_len: int = 80) -> str:
    cleaned = _INVALID_FS.sub("_", name).strip().strip(".")
    return (cleaned or "unnamed")[:max_len]


def downloads_root() -> Path:
    home = Path.home()
    for candidate in ("Downloads", "Téléchargements", "Telechargements"):
        d = home / candidate
        if d.exists():
            return d
    fallback = home / "Downloads"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def unique_path(folder: Path, filename: str) -> Path:
    path = folder / safe_name(filename)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while (folder / f"{stem}_{i}{suffix}").exists():
        i += 1
    return folder / f"{stem}_{i}{suffix}"


async def _save_attachment(session: aiohttp.ClientSession, att: discord.Attachment, folder: Path) -> Path:
    path = unique_path(folder, att.filename)
    async with session.get(att.url) as resp:
        resp.raise_for_status()
        data = await resp.read()
    # Always written as bytes, never executed.
    path.write_bytes(data)
    return path


def _format_message(msg: discord.Message) -> str:
    ts = msg.created_at.isoformat(timespec="seconds")
    author = f"{msg.author} ({msg.author.id})"
    parts = [f"[{ts}] {author}"]
    if msg.content:
        parts.append(msg.content)
    for att in msg.attachments:
        parts.append(f"[piece-jointe] {att.filename} -> {att.url}")
    for emb in msg.embeds:
        if emb.url:
            parts.append(f"[embed] {emb.url}")
        if emb.description:
            parts.append(f"[embed-desc] {emb.description}")
    return "\n".join(parts) + "\n"


async def export_channel(
    channel: discord.abc.Messageable,
    dest_root: Path,
    *,
    limit: Optional[int] = None,
    log: Optional[LogFn] = None,
) -> Path:
    """Export one channel's history into dest_root/<channel>/.

    Writes messages.txt, links.txt, and saves every attachment.
    Attachments are written to disk only — never executed.
    """
    label = getattr(channel, "name", None) or f"dm-{getattr(channel, 'id', 'x')}"
    folder = dest_root / safe_name(f"{label}-{channel.id}")
    folder.mkdir(parents=True, exist_ok=True)

    transcript = folder / "messages.txt"
    links = folder / "links.txt"

    timeout = aiohttp.ClientTimeout(total=180)
    count = 0
    async with aiohttp.ClientSession(timeout=timeout) as session:
        with transcript.open("w", encoding="utf-8") as f, links.open("w", encoding="utf-8") as lf:
            try:
                async for msg in channel.history(limit=limit, oldest_first=True):
                    count += 1
                    f.write(_format_message(msg))
                    f.write("\n")
                    for url in _URL_RE.findall(msg.content or ""):
                        lf.write(url + "\n")
                    for att in msg.attachments:
                        try:
                            saved = await _save_attachment(session, att, folder)
                            if log:
                                log(f"  ↓ {saved.name}")
                        except Exception as e:  # noqa: BLE001
                            if log:
                                log(f"  ! {att.filename}: {e}")
            except discord.Forbidden:
                if log:
                    log(f"  accès refusé sur {label}")
            except Exception as e:  # noqa: BLE001
                if log:
                    log(f"  erreur dans {label}: {e}")
    if log:
        log(f"{label}: {count} messages")
    return folder


async def export_channels(
    channels: Iterable[discord.abc.Messageable],
    dest_root: Path,
    *,
    limit: Optional[int] = None,
    log: Optional[LogFn] = None,
) -> Path:
    dest_root.mkdir(parents=True, exist_ok=True)
    for ch in channels:
        await export_channel(ch, dest_root, limit=limit, log=log)
    return dest_root
