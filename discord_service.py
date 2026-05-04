from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import List, Optional

import discord
from PyQt6.QtCore import QObject, pyqtSignal


class DiscordService(QObject):
    """Runs discord.py-self on its own asyncio loop in a daemon thread.

    The Qt thread interacts with it via:
      - `submit(coro)` -> concurrent.futures.Future
      - read-only accessors (`guilds`, `text_channels`, `get_channel`)
      - signals (`ready`, `error`) that fire back on the Qt thread.

    Avoiding qasync sidesteps the QSocketNotifier / startTimer thread
    warnings seen on PyQt6 + Python 3.12.
    """

    ready = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token
        self.client = discord.Client(chunk_guilds_at_startup=False)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()

        @self.client.event
        async def on_ready() -> None:  # noqa: N802
            self.ready.emit()

    # -- Lifecycle ------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="discord-loop"
        )
        self._thread.start()
        # Wait until the loop is created, so submit() is safe immediately.
        self._loop_ready.wait(timeout=5.0)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_until_complete(self.client.start(self._token))
        except discord.LoginFailure as e:
            self.error.emit(f"Token invalide: {e}")
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"Connexion échouée: {e}")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                pass
            loop.close()

    def stop(self) -> None:
        if self._loop is None:
            return
        if self.client.is_closed():
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.client.close(), self._loop)
            fut.result(timeout=5)
        except Exception:  # noqa: BLE001
            pass

    # -- Submit ---------------------------------------------------------

    def submit(self, coro) -> Future:
        if self._loop is None:
            raise RuntimeError("DiscordService not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # -- Read-only accessors (safe to call from the Qt thread) ----------

    @property
    def me(self) -> Optional[discord.ClientUser]:
        return self.client.user

    def guilds(self) -> List[discord.Guild]:
        return sorted(self.client.guilds, key=lambda g: g.name.lower())

    def text_channels(self, guild_id: int) -> List[discord.TextChannel]:
        guild = self.client.get_guild(guild_id)
        if not guild:
            return []
        me = guild.me
        result: List[discord.TextChannel] = []
        for ch in guild.channels:
            if not isinstance(ch, discord.TextChannel):
                continue
            try:
                if ch.permissions_for(me).read_messages:
                    result.append(ch)
            except Exception:  # noqa: BLE001
                continue
        result.sort(key=lambda c: (c.category.position if c.category else -1, c.position))
        return result

    def get_channel(self, channel_id: int) -> Optional[discord.abc.Messageable]:
        ch = self.client.get_channel(channel_id)
        if isinstance(ch, discord.abc.Messageable):
            return ch
        return None

    # -- Coroutines (must be run via submit) ----------------------------

    async def fetch_messages_coro(
        self, channel_id: int, limit: int = 100
    ) -> List[discord.Message]:
        channel = self.get_channel(channel_id)
        if not channel:
            return []
        msgs: List[discord.Message] = []
        async for m in channel.history(limit=limit):
            msgs.append(m)
        msgs.reverse()
        return msgs
