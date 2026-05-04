from __future__ import annotations

from typing import List, Optional

import discord
from PyQt6.QtCore import QObject, pyqtSignal


class DiscordService(QObject):
    """Thin wrapper around discord.py-self to surface state via Qt signals."""

    ready = pyqtSignal()
    error = pyqtSignal(str)
    disconnected = pyqtSignal()

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token
        self.client = discord.Client(chunk_guilds_at_startup=False)

        @self.client.event
        async def on_ready() -> None:  # noqa: N802 - discord.py callback name
            self.ready.emit()

        @self.client.event
        async def on_disconnect() -> None:  # noqa: N802
            self.disconnected.emit()

    async def start(self) -> None:
        try:
            await self.client.start(self._token)
        except discord.LoginFailure as e:
            self.error.emit(f"Token invalide: {e}")
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"Connexion échouée: {e}")

    async def stop(self) -> None:
        if not self.client.is_closed():
            await self.client.close()

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

    async def fetch_messages(self, channel_id: int, limit: int = 100) -> List[discord.Message]:
        channel = self.get_channel(channel_id)
        if not channel:
            return []
        msgs: List[discord.Message] = []
        async for m in channel.history(limit=limit):
            msgs.append(m)
        msgs.reverse()
        return msgs
