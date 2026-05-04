from __future__ import annotations

import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional
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


@dataclass
class ExportStats:
    label: str
    folder: Path
    messages: int = 0
    attachments: int = 0
    cdn_files: int = 0
    other_links: int = 0
    errors: List[str] = field(default_factory=list)


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


def can_read_history(channel: discord.abc.Messageable) -> bool:
    """True if the current user can fetch the channel's message history."""
    guild = getattr(channel, "guild", None)
    if guild is None:
        return True  # DMs / group DMs are always readable
    me = guild.me
    perms = channel.permissions_for(me)
    return bool(perms.read_messages and perms.read_message_history)


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
    session: aiohttp.ClientSession,
    url: str,
    folder: Path,
    *,
    fetch_url: Optional[str] = None,
) -> Path:
    """Save `url` to disk; if `fetch_url` is given, GET that instead but keep
    the filename derived from `url`. Lets us swap an expired CDN URL for a
    refreshed one without changing the saved filename."""
    path = unique_path(folder, filename_from_url(url))
    async with session.get(fetch_url or url) as resp:
        resp.raise_for_status()
        data = await resp.read()
    path.write_bytes(data)
    return path


async def refresh_cdn_urls(
    client: discord.Client,
    urls: List[str],
    log: Optional[LogFn] = None,
) -> dict[str, str]:
    """Hit POST /attachments/refresh-urls so expired Discord CDN signatures
    (ex=, is=, hm= query params) are reissued with a fresh ~24h validity.

    Returns {original_url: refreshed_url}. URLs that the API doesn't return
    are simply absent from the dict — callers should fall back to the
    original.
    """
    if not urls:
        return {}
    token = getattr(getattr(client, "http", None), "token", None)
    if not token:
        return {}
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) discord/1.0.9036 Chrome/120 Safari/537.36"
        ),
    }
    out: dict[str, str] = {}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        # Endpoint accepts up to 50 URLs per request.
        for i in range(0, len(urls), 50):
            batch = urls[i:i + 50]
            try:
                async with s.post(
                    "https://discord.com/api/v9/attachments/refresh-urls",
                    headers=headers,
                    json={"attachment_urls": batch},
                ) as r:
                    if r.status >= 400:
                        if log:
                            log(f"refresh-urls HTTP {r.status}")
                        continue
                    data = await r.json()
            except Exception as e:  # noqa: BLE001
                if log:
                    log(f"refresh-urls failed: {e}")
                continue
            for item in data.get("refreshed_urls", []):
                orig = item.get("original")
                ref = item.get("refreshed")
                if orig and ref:
                    out[orig] = ref
    return out


def _format_header(msg: discord.Message) -> str:
    ts = msg.created_at.isoformat(timespec="seconds")
    return f"[{ts}] {msg.author} ({msg.author.id})"


async def _collect_history(
    channel: discord.abc.Messageable, limit: Optional[int]
) -> List[discord.Message]:
    """Fetch the most recent N messages, then return them oldest-first.

    Done in two steps because some self-bot tokens have flaky behaviour
    with `oldest_first=True`. Newest-first is the API default and is
    reliable; we just reverse for chronological writing.
    """
    msgs: List[discord.Message] = []
    async for m in channel.history(limit=limit):
        msgs.append(m)
    msgs.reverse()
    return msgs


async def export_channel(
    channel: discord.abc.Messageable,
    dest_root: Path,
    *,
    client: Optional[discord.Client] = None,
    limit: Optional[int] = None,
    log: Optional[LogFn] = None,
) -> ExportStats:
    """Export one channel: messages.txt, links.txt, every attachment, every Discord-CDN URL.

    Returns ExportStats so callers can show meaningful results. Writes a
    `_export.log` to the channel folder with everything that happened
    (including the reason for any skipped channel) — that's the file to
    open when something looks empty.
    """
    label = getattr(channel, "name", None) or f"dm-{getattr(channel, 'id', 'x')}"
    folder = dest_root / safe_name(f"{label}-{channel.id}")
    folder.mkdir(parents=True, exist_ok=True)
    stats = ExportStats(label=label, folder=folder)

    debug = (folder / "_export.log").open("w", encoding="utf-8")

    def _logline(line: str) -> None:
        debug.write(line + "\n")
        debug.flush()
        sys.stderr.write(f"[{label}] {line}\n")
        sys.stderr.flush()
        if log:
            log(line)

    try:
        if not can_read_history(channel):
            msg = "skipped: missing read_message_history permission"
            stats.errors.append(msg)
            _logline(msg)
            return stats

        _logline(f"starting export, limit={limit}")
        try:
            messages = await _collect_history(channel, limit)
        except discord.Forbidden as e:
            stats.errors.append(f"forbidden while reading history: {e}")
            _logline(f"forbidden: {e}")
            return stats
        except Exception as e:  # noqa: BLE001
            stats.errors.append(f"history fetch failed: {e}")
            _logline(f"history fetch failed: {e}\n{traceback.format_exc()}")
            return stats

        _logline(f"fetched {len(messages)} messages")

        if not messages:
            _logline("nothing to write")
            return stats

        # Pre-collect every Discord-CDN URL we plan to fetch, then batch-
        # refresh them via /attachments/refresh-urls. Without this, any URL
        # whose ex=/is=/hm= signature has expired returns 404 and the file
        # silently fails to download.
        cdn_seen: set[str] = set()
        for msg in messages:
            for url in _URL_RE.findall(msg.content or ""):
                if is_discord_cdn(url):
                    cdn_seen.add(url)
            for emb in msg.embeds:
                for src in (emb.image, emb.thumbnail, emb.video):
                    u = getattr(src, "url", None)
                    if u and is_discord_cdn(u):
                        cdn_seen.add(u)

        refresh_map: dict[str, str] = {}
        if cdn_seen and client is not None:
            refresh_map = await refresh_cdn_urls(client, list(cdn_seen), log=_logline)
            _logline(f"refreshed {len(refresh_map)}/{len(cdn_seen)} CDN URLs")

        # `async with` only works with async context managers; file objects
        # are sync, so the aiohttp session and the files have to live in
        # separate `with` statements. Putting them on the same line raises
        # "TextIOWrapper does not support the asynchronous context manager
        # protocol", and worse, .open("w") truncates messages.txt before the
        # error is raised — leaving you with 0-byte files.
        timeout = aiohttp.ClientTimeout(total=180)
        transcript_path = folder / "messages.txt"
        links_path = folder / "links.txt"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with transcript_path.open("w", encoding="utf-8") as f, \
                    links_path.open("w", encoding="utf-8") as lf:
                for msg in messages:
                    stats.messages += 1
                    f.write(_format_header(msg) + "\n")
                    if msg.content:
                        f.write(msg.content + "\n")

                    # Attachments: always download.
                    for att in msg.attachments:
                        try:
                            saved = await _save_attachment(session, att, folder)
                            f.write(f"[attachment] {att.filename} -> {saved.name}\n")
                            stats.attachments += 1
                            _logline(f"↓ attachment {saved.name}")
                        except Exception as e:  # noqa: BLE001
                            f.write(f"[attachment-failed] {att.filename}: {e}\n")
                            stats.errors.append(f"attachment {att.filename}: {e}")
                            _logline(f"! attachment {att.filename}: {e}")

                    # URLs in content: Discord CDN -> download, else -> links.txt.
                    for url in _URL_RE.findall(msg.content or ""):
                        if is_discord_cdn(url):
                            try:
                                saved = await _save_url(
                                    session, url, folder,
                                    fetch_url=refresh_map.get(url),
                                )
                                f.write(f"[cdn] {url} -> {saved.name}\n")
                                stats.cdn_files += 1
                                _logline(f"↓ cdn {saved.name}")
                            except Exception as e:  # noqa: BLE001
                                f.write(f"[cdn-failed] {url}: {e}\n")
                                stats.errors.append(f"cdn {url}: {e}")
                                _logline(f"! cdn {url}: {e}")
                        else:
                            lf.write(url + "\n")
                            stats.other_links += 1

                    # Embeds: their .url is generally a preview link, not a file.
                    # Embeds may also expose image/video proxies on the CDN —
                    # download those, log the rest.
                    for emb in msg.embeds:
                        candidate = None
                        for src in (emb.image, emb.thumbnail, emb.video):
                            u = getattr(src, "url", None)
                            if u and is_discord_cdn(u):
                                candidate = u
                                break
                        if candidate:
                            try:
                                saved = await _save_url(
                                    session, candidate, folder,
                                    fetch_url=refresh_map.get(candidate),
                                )
                                f.write(f"[embed-cdn] {candidate} -> {saved.name}\n")
                                stats.cdn_files += 1
                            except Exception as e:  # noqa: BLE001
                                f.write(f"[embed-cdn-failed] {candidate}: {e}\n")
                                stats.errors.append(f"embed-cdn {candidate}: {e}")
                        elif emb.url:
                            lf.write(emb.url + "\n")
                            stats.other_links += 1

                    f.write("\n")

        _logline(
            f"done: {stats.messages} messages, {stats.attachments} attachments, "
            f"{stats.cdn_files} cdn files, {stats.other_links} other links"
        )
        return stats
    finally:
        debug.close()


async def export_channels(
    channels: Iterable[discord.abc.Messageable],
    dest_root: Path,
    *,
    client: Optional[discord.Client] = None,
    limit: Optional[int] = None,
    log: Optional[LogFn] = None,
) -> List[ExportStats]:
    dest_root.mkdir(parents=True, exist_ok=True)
    results: List[ExportStats] = []
    for ch in channels:
        results.append(
            await export_channel(ch, dest_root, client=client, limit=limit, log=log)
        )
    return results


def summarize(stats_list: List[ExportStats]) -> str:
    total_msgs = sum(s.messages for s in stats_list)
    total_att = sum(s.attachments for s in stats_list)
    total_cdn = sum(s.cdn_files for s in stats_list)
    total_links = sum(s.other_links for s in stats_list)
    skipped = [s.label for s in stats_list if s.messages == 0]
    lines = [
        f"{len(stats_list)} channels processed",
        f"  {total_msgs} messages, {total_att} attachments, "
        f"{total_cdn} CDN files, {total_links} other links",
    ]
    if skipped:
        lines.append(f"  skipped/empty: {', '.join(skipped[:8])}"
                     + ("…" if len(skipped) > 8 else ""))
    return "\n".join(lines)
