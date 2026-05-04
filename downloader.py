from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import unquote, urlparse

import aiohttp
import discord


_INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_URL_RE = re.compile(r'https?://[^\s<>"\']+')
_DISCORD_CDN_HOSTS = (
    "cdn.discordapp.com",
    "media.discordapp.net",
    "images.discordapp.net",
)

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


def is_discord_cdn(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return False
    return any(host == h or host.endswith("." + h) for h in _DISCORD_CDN_HOSTS)


def filename_from_url(url: str, fallback: str = "cdn-file") -> str:
    try:
        path = urlparse(url).path
    except Exception:  # noqa: BLE001
        return fallback
    last = path.rsplit("/", 1)[-1]
    last = unquote(last).strip()
    return last or fallback


async def _save_attachment(
    session: aiohttp.ClientSession, att: discord.Attachment, folder: Path
) -> Path:
    path = unique_path(folder, att.filename)
    async with session.get(att.url) as resp:
        resp.raise_for_status()
        data = await resp.read()
    # Always written as bytes, never executed.
    path.write_bytes(data)
    return path


async def _save_url(
    session: aiohttp.ClientSession, url: str, folder: Path
) -> Path:
    path = unique_path(folder, filename_from_url(url))
    async with session.get(url) as resp:
        resp.raise_for_status()
        data = await resp.read()
    path.write_bytes(data)
    return path


def _format_header(msg: discord.Message) -> str:
    ts = msg.created_at.isoformat(timespec="seconds")
    return f"[{ts}] {msg.author} ({msg.author.id})"


async def export_channel(
    channel: discord.abc.Messageable,
    dest_root: Path,
    *,
    limit: Optional[int] = None,
    log: Optional[LogFn] = None,
) -> Path:
    """Export one channel: messages.txt, links.txt, every attachment, every Discord-CDN URL.

    Discord CDN URLs found in message text are downloaded as files
    (cdn.discordapp.com / media.discordapp.net / images.discordapp.net).
    Other URLs are written to links.txt. Attachments are written as
    bytes only — never executed.
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
                    f.write(_format_header(msg) + "\n")
                    if msg.content:
                        f.write(msg.content + "\n")

                    # Attachments: always download.
                    for att in msg.attachments:
                        try:
                            saved = await _save_attachment(session, att, folder)
                            f.write(f"[attachment] {att.filename} -> {saved.name}\n")
                            if log:
                                log(f"  ↓ {saved.name}")
                        except Exception as e:  # noqa: BLE001
                            f.write(f"[attachment-failed] {att.filename}: {e}\n")
                            if log:
                                log(f"  ! {att.filename}: {e}")

                    # URLs in content: Discord CDN -> download, else -> links.txt.
                    for url in _URL_RE.findall(msg.content or ""):
                        if is_discord_cdn(url):
                            try:
                                saved = await _save_url(session, url, folder)
                                f.write(f"[cdn] {url} -> {saved.name}\n")
                                if log:
                                    log(f"  ↓ {saved.name}")
                            except Exception as e:  # noqa: BLE001
                                f.write(f"[cdn-failed] {url}: {e}\n")
                                if log:
                                    log(f"  ! {url}: {e}")
                        else:
                            lf.write(url + "\n")

                    # Embed URLs go to links.txt — they're previews, not files.
                    for emb in msg.embeds:
                        if emb.url and not is_discord_cdn(emb.url):
                            lf.write(emb.url + "\n")

                    f.write("\n")
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
