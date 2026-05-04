from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import List, Optional

import aiohttp
import discord
from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPalette,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from discord_service import DiscordService
from downloader import downloads_root, export_channel, export_channels, safe_name


# ----- Design tokens (adapted from the React landing-page rules) ----------

CREAM = "#F3F4ED"
INK = "#1a1a1a"
INK_60 = "rgba(26,26,26,0.60)"
INK_40 = "rgba(26,26,26,0.40)"
INK_10 = "rgba(26,26,26,0.10)"
BLUE = "#0871E7"
NOKIA_FG = "#2A3616"

FONT_SERIF_STACK = "'Instrument Serif', 'Cormorant Garamond', 'Georgia', serif"
FONT_SANS_STACK = "'Inter', 'Helvetica Neue', 'Segoe UI', system-ui, sans-serif"
FONT_NOKIA_STACK = "'Nokia Cellphone FC Small', 'Px437 IBM VGA8', 'Courier New', monospace"


GLOBAL_QSS = f"""
QWidget {{
    background: {CREAM};
    color: {INK};
    font-family: {FONT_SANS_STACK};
    font-size: 13px;
}}
QLabel#hero {{
    font-family: {FONT_SERIF_STACK};
    color: {INK};
    letter-spacing: -1px;
}}
QLabel#sub {{
    font-family: {FONT_SANS_STACK};
    color: {INK_60};
}}
QLabel#nokia {{
    font-family: {FONT_NOKIA_STACK};
    color: {NOKIA_FG};
    font-size: 11px;
}}
QFrame#navbar {{
    background: rgba(255,255,255,0.55);
    border: 1px solid {INK_10};
    border-radius: 28px;
}}
QLabel#brand {{
    font-family: {FONT_SERIF_STACK};
    font-size: 26px;
    color: {INK};
}}
QPushButton[role="link"] {{
    background: transparent;
    border: none;
    color: {INK};
    font-size: 13px;
    padding: 4px 6px;
}}
QPushButton[role="link"]:hover {{ color: {INK_60}; }}
QPushButton[role="cta"] {{
    background: {BLUE};
    color: white;
    border: 1px solid {BLUE};
    border-radius: 18px;
    padding: 8px 18px;
    font-size: 13px;
}}
QPushButton[role="cta"]:hover {{ background: #1380F0; }}
QPushButton[role="cta"]:disabled {{ background: rgba(8,113,231,0.4); }}
QPushButton[role="ghost"] {{
    background: white;
    color: {INK};
    border: 1px solid {INK_10};
    border-radius: 18px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton[role="ghost"]:hover {{ background: #FAFAF6; }}
QFrame#card {{
    background: white;
    border: 1px solid {INK_10};
    border-radius: 18px;
}}
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    background: white;
    border: 1px solid {INK_10};
    border-radius: 14px;
    padding: 10px 14px;
    margin: 4px 2px;
    color: {INK};
}}
QListWidget::item:hover {{ background: #FAFAF6; }}
QListWidget::item:selected {{
    background: {INK};
    color: white;
    border-color: {INK};
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: {INK_10};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {INK_40}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QSpinBox {{
    background: white;
    border: 1px solid {INK_10};
    border-radius: 12px;
    padding: 4px 8px;
}}
"""


# ----- Animations ---------------------------------------------------------


def fade_in(widget: QWidget, *, duration: int = 1200, delay: int = 0) -> None:
    """Match motion/react entrance: opacity 0 -> 1 with a serif-friendly ease."""
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    if delay:
        QTimer.singleShot(delay, anim.start)
    else:
        anim.start()
    widget._fade_anim = anim  # type: ignore[attr-defined]


# ----- Reusable widgets ---------------------------------------------------


class CTAButton(QPushButton):
    """Blue rounded pill with the inner-glint and outline from the spec."""

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "cta")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(8, 113, 231, 90))
        self.setGraphicsEffect(shadow)


class GhostButton(QPushButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)


class Navbar(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("navbar")
        self.setFixedHeight(56)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 8, 8, 8)
        layout.setSpacing(28)

        brand = QLabel("discord.")
        brand.setObjectName("brand")
        layout.addWidget(brand)

        layout.addStretch(1)
        for name in ("Servers", "Channels", "Messages"):
            btn = QPushButton(name)
            btn.setProperty("role", "link")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setEnabled(False)  # decorative — keeps the navbar layout intact
            layout.addWidget(btn)

        layout.addStretch(1)
        self.cta = CTAButton("Link up")
        layout.addWidget(self.cta)


class TypingStatus(QLabel):
    """Cycles through nokia-font status messages, like the landing page demo."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("nokia")
        self._messages: List[str] = ["Are you here?", "Yes, I am.", "Speak soon."]
        self._idx = 0
        self._sub = 0
        self._deleting = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._cursor = True
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._blink)
        self._cursor_timer.start(800)
        self._timer.start(100)
        self._render()

    def set_messages(self, messages: List[str]) -> None:
        if not messages:
            return
        self._messages = messages
        self._idx = 0
        self._sub = 0
        self._deleting = False
        self._render()

    def _tick(self) -> None:
        msg = self._messages[self._idx]
        if not self._deleting:
            self._sub += 1
            if self._sub >= len(msg):
                self._sub = len(msg)
                self._deleting = True
                self._timer.start(2000)
                self._render()
                return
            self._timer.start(100)
        else:
            self._sub -= 1
            if self._sub <= 0:
                self._sub = 0
                self._deleting = False
                self._idx = (self._idx + 1) % len(self._messages)
            self._timer.start(50)
        self._render()

    def _blink(self) -> None:
        self._cursor = not self._cursor
        self._render()

    def _render(self) -> None:
        msg = self._messages[self._idx][: self._sub]
        cursor = "▌" if self._cursor else " "
        self.setText(f"{msg}{cursor}")


# ----- Domain widgets -----------------------------------------------------


class MessageCard(QFrame):
    """Displays one message: header, content, attachments, links."""

    def __init__(self, msg: discord.Message, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._msg = msg
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
        header = QLabel(
            f"<span style='font-weight:600'>{msg.author.display_name}</span>"
            f"  <span style='color:{INK_40}'>{ts}</span>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        if msg.content:
            body = QLabel(msg.content)
            body.setWordWrap(True)
            body.setOpenExternalLinks(False)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(body)

        for att in msg.attachments:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = QLabel(
                f"📎 {att.filename}  <span style='color:{INK_40}'>"
                f"{att.size // 1024} KB</span>"
            )
            name.setTextFormat(Qt.TextFormat.RichText)
            row.addWidget(name, 1)
            layout.addLayout(row)

        for emb in msg.embeds:
            if emb.url:
                link = QLabel(f"<a href='{emb.url}' style='color:{BLUE}'>{emb.url}</a>")
                link.setTextFormat(Qt.TextFormat.RichText)
                link.setOpenExternalLinks(True)
                layout.addWidget(link)

        # The thumbnail row is populated lazily by the panel.
        self.thumb_row = QHBoxLayout()
        self.thumb_row.setSpacing(8)
        layout.addLayout(self.thumb_row)

        # Per-message download button (only if there's something to save).
        if msg.attachments or msg.content:
            row = QHBoxLayout()
            row.addStretch(1)
            self.save_btn = GhostButton("Download")
            self.save_btn.setMinimumHeight(28)
            row.addWidget(self.save_btn)
            layout.addLayout(row)
        else:
            self.save_btn = None

    def add_thumbnail(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        thumb = QLabel()
        thumb.setPixmap(pixmap.scaled(
            220, 220,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        thumb.setStyleSheet(f"border:1px solid {INK_10}; border-radius:12px; padding:4px;")
        self.thumb_row.addWidget(thumb)
        self.thumb_row.addStretch(1)


# ----- Coroutines for cross-thread work ----------------------------------


async def _fetch_bytes(url: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url) as r:
            r.raise_for_status()
            return await r.read()


async def _save_message_coro(msg: discord.Message, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "message.txt").write_text(
        f"[{msg.created_at.isoformat(timespec='seconds')}] {msg.author}\n"
        f"{msg.content or ''}\n",
        encoding="utf-8",
    )
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        for att in msg.attachments:
            try:
                async with s.get(att.url) as r:
                    r.raise_for_status()
                    data = await r.read()
                (root / safe_name(att.filename)).write_bytes(data)
            except Exception:  # noqa: BLE001
                continue
    return root


# ----- Main window --------------------------------------------------------


class MainWindow(QWidget):
    """Three-panel browser: servers / channels / messages."""

    # Cross-thread delivery: emitted from the discord loop, received in Qt.
    _messages_ready = pyqtSignal(int, object)            # channel_id, list[Message] | None
    _thumb_ready = pyqtSignal(int, bytes)                # message_id, raw bytes
    _save_done = pyqtSignal(str)                         # human path
    _save_failed = pyqtSignal(str)                       # error
    _log = pyqtSignal(str)

    def __init__(self, service: DiscordService) -> None:
        super().__init__()
        self.service = service
        self._current_guild: Optional[discord.Guild] = None
        self._current_channel_id: Optional[int] = None

        self.setWindowTitle("discord. — quiet browser")
        self.resize(1280, 820)
        self.setStyleSheet(GLOBAL_QSS)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(CREAM))
        self.setPalette(pal)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        self.navbar = Navbar()
        self.navbar.cta.setText("Connecting…")
        self.navbar.cta.setEnabled(False)
        outer.addWidget(self.navbar)

        # Hero
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 8, 0, 8)
        hero_layout.setSpacing(6)
        self.headline = QLabel("Short notes.\nDaily calm.")
        self.headline.setObjectName("hero")
        self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(36)
        self.headline.setFont(font)
        self.headline.setStyleSheet(
            f"font-family:{FONT_SERIF_STACK}; font-size:42px; color:{INK};"
        )
        hero_layout.addWidget(self.headline)

        self.sub = QLabel(
            "Browse your servers, read the channels, save what matters. "
            "A quiet rhythm in the digital noise."
        )
        self.sub.setObjectName("sub")
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub.setStyleSheet(f"font-size:14px; color:{INK_60};")
        hero_layout.addWidget(self.sub)

        self.typing = TypingStatus()
        self.typing.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.typing.set_messages(["connecting…", "loading guilds…", "ready."])
        hero_layout.addWidget(self.typing)

        outer.addWidget(hero)
        fade_in(self.headline, duration=1500)
        fade_in(self.sub, duration=1200, delay=300)

        # Three columns
        grid = QHBoxLayout()
        grid.setSpacing(16)
        outer.addLayout(grid, 1)

        grid.addWidget(self._build_server_panel(), 1)
        grid.addWidget(self._build_channel_panel(), 1)
        grid.addWidget(self._build_message_panel(), 2)

        # Wire service signals
        self.service.ready.connect(self._on_ready)
        self.service.error.connect(self._on_error)

        # Wire internal cross-thread signals (queued connections by default)
        self._messages_ready.connect(self._render_messages)
        self._thumb_ready.connect(self._attach_thumb)
        self._save_done.connect(self._notify_save_done)
        self._save_failed.connect(self._notify_save_failed)
        self._log.connect(self._on_log)

    # -- Panels ---------------------------------------------------------

    def _panel_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QLabel(title)
        header.setStyleSheet(
            f"font-family:{FONT_SERIF_STACK}; font-size:22px; color:{INK};"
        )
        layout.addWidget(header)
        return card, layout

    def _build_server_panel(self) -> QFrame:
        card, layout = self._panel_card("Servers")
        self.server_status = QLabel("…")
        self.server_status.setStyleSheet(f"color:{INK_60}; font-size:12px;")
        layout.addWidget(self.server_status)
        self.server_list = QListWidget()
        self.server_list.setSpacing(2)
        self.server_list.itemSelectionChanged.connect(self._on_server_selected)
        layout.addWidget(self.server_list, 1)
        return card

    def _build_channel_panel(self) -> QFrame:
        card, layout = self._panel_card("Channels")
        self.channel_status = QLabel("Pick a server.")
        self.channel_status.setStyleSheet(f"color:{INK_60}; font-size:12px;")
        layout.addWidget(self.channel_status)

        self.channel_list = QListWidget()
        self.channel_list.setSpacing(2)
        self.channel_list.itemSelectionChanged.connect(self._on_channel_selected)
        layout.addWidget(self.channel_list, 1)

        # Download all + limit
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel("Limit:"))
        self.limit_box = QSpinBox()
        self.limit_box.setRange(50, 100000)
        self.limit_box.setSingleStep(50)
        self.limit_box.setValue(500)
        bar.addWidget(self.limit_box)
        bar.addStretch(1)
        self.download_all_btn = CTAButton("Download all")
        self.download_all_btn.setEnabled(False)
        self.download_all_btn.clicked.connect(self._download_all_channels)
        bar.addWidget(self.download_all_btn)
        layout.addLayout(bar)
        return card

    def _build_message_panel(self) -> QFrame:
        card, layout = self._panel_card("Messages")
        self.message_status = QLabel("Pick a channel.")
        self.message_status.setStyleSheet(f"color:{INK_60}; font-size:12px;")
        layout.addWidget(self.message_status)

        bar = QHBoxLayout()
        bar.addStretch(1)
        self.refresh_btn = GhostButton("Refresh")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self._reload_current_channel)
        bar.addWidget(self.refresh_btn)
        self.download_one_btn = CTAButton("Download channel")
        self.download_one_btn.setEnabled(False)
        self.download_one_btn.clicked.connect(self._download_current_channel)
        bar.addWidget(self.download_one_btn)
        layout.addLayout(bar)

        self.message_scroll = QScrollArea()
        self.message_scroll.setWidgetResizable(True)
        self.message_container = QWidget()
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(4, 4, 4, 4)
        self.message_layout.setSpacing(10)
        self.message_layout.addStretch(1)
        self.message_scroll.setWidget(self.message_container)
        layout.addWidget(self.message_scroll, 1)
        return card

    # -- Service callbacks ---------------------------------------------

    def _on_ready(self) -> None:
        me = self.service.me
        who = str(me) if me else "you"
        self.navbar.cta.setText("Connected")
        self.navbar.cta.setEnabled(False)
        self.typing.set_messages([f"hi, {who}", "ready.", "browse quietly."])
        self._refresh_servers()

    def _on_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Discord", msg)
        self.typing.set_messages(["disconnected.", msg[:40]])

    def _on_log(self, msg: str) -> None:
        self.typing.set_messages([msg[:40]])

    # -- Server / channel ----------------------------------------------

    def _refresh_servers(self) -> None:
        self.server_list.clear()
        guilds = self.service.guilds()
        self.server_status.setText(f"{len(guilds)} servers")
        for g in guilds:
            item = QListWidgetItem(g.name)
            item.setData(Qt.ItemDataRole.UserRole, g.id)
            self.server_list.addItem(item)

    def _on_server_selected(self) -> None:
        items = self.server_list.selectedItems()
        if not items:
            return
        guild_id = items[0].data(Qt.ItemDataRole.UserRole)
        self._current_guild = self.service.client.get_guild(guild_id)
        self._populate_channels()

    def _populate_channels(self) -> None:
        self.channel_list.clear()
        if not self._current_guild:
            return
        channels = self.service.text_channels(self._current_guild.id)
        self.channel_status.setText(
            f"{len(channels)} channels in {self._current_guild.name}"
        )
        self.download_all_btn.setEnabled(bool(channels))
        for ch in channels:
            item = QListWidgetItem(f"# {ch.name}")
            item.setData(Qt.ItemDataRole.UserRole, ch.id)
            self.channel_list.addItem(item)

    def _on_channel_selected(self) -> None:
        items = self.channel_list.selectedItems()
        if not items:
            return
        channel_id = items[0].data(Qt.ItemDataRole.UserRole)
        self._current_channel_id = channel_id
        self.refresh_btn.setEnabled(True)
        self.download_one_btn.setEnabled(True)
        self._reload_current_channel()

    # -- Messages: load & render ---------------------------------------

    def _reload_current_channel(self) -> None:
        if self._current_channel_id is None:
            return
        self._clear_messages()
        self.message_status.setText("Loading…")
        cid = self._current_channel_id

        fut = self.service.submit(self.service.fetch_messages_coro(cid, limit=80))

        def done(f: Future) -> None:
            if f.exception():
                self._messages_ready.emit(cid, None)
            else:
                self._messages_ready.emit(cid, f.result())

        fut.add_done_callback(done)

    def _clear_messages(self) -> None:
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_messages(self, cid: int, msgs: object) -> None:
        if cid != self._current_channel_id:
            return
        if msgs is None:
            self.message_status.setText("Failed to load messages.")
            return
        msgs_list: List[discord.Message] = list(msgs)  # type: ignore[arg-type]
        self.message_status.setText(f"{len(msgs_list)} messages")
        for m in msgs_list:
            card = MessageCard(m)
            if card.save_btn is not None:
                card.save_btn.clicked.connect(
                    lambda _checked, mm=m: self._save_single_message(mm)
                )
            self.message_layout.insertWidget(self.message_layout.count() - 1, card)

        # Schedule thumbnails
        for m in msgs_list:
            for att in m.attachments:
                ctype = att.content_type or ""
                if not ctype.startswith("image/"):
                    continue
                self._schedule_thumb(m.id, att.url)

    def _schedule_thumb(self, msg_id: int, url: str) -> None:
        fut = self.service.submit(_fetch_bytes(url))

        def done(f: Future) -> None:
            if f.exception():
                return
            try:
                data = f.result()
            except Exception:  # noqa: BLE001
                return
            self._thumb_ready.emit(msg_id, data)

        fut.add_done_callback(done)

    def _attach_thumb(self, msg_id: int, data: bytes) -> None:
        pix = QPixmap()
        if not pix.loadFromData(data):
            return
        for i in range(self.message_layout.count()):
            w = self.message_layout.itemAt(i).widget()
            if isinstance(w, MessageCard) and w._msg.id == msg_id:
                w.add_thumbnail(pix)
                return

    # -- Downloads ------------------------------------------------------

    def _save_single_message(self, msg: discord.Message) -> None:
        ch = self.service.get_channel(msg.channel.id)
        if ch is None:
            return
        guild_name = self._current_guild.name if self._current_guild else "dm"
        root = (
            downloads_root()
            / "discord-browser"
            / safe_name(guild_name)
            / safe_name(f"{getattr(ch, 'name', 'dm')}-{ch.id}")
            / f"msg-{msg.id}"
        )
        fut = self.service.submit(_save_message_coro(msg, root))

        def done(f: Future) -> None:
            if f.exception():
                self._save_failed.emit(str(f.exception()))
            else:
                self._save_done.emit(str(f.result()))

        fut.add_done_callback(done)

    def _download_current_channel(self) -> None:
        if self._current_channel_id is None:
            return
        ch = self.service.get_channel(self._current_channel_id)
        if ch is None:
            return
        guild_name = self._current_guild.name if self._current_guild else "dm"
        dest = downloads_root() / "discord-browser" / safe_name(guild_name)
        limit = self.limit_box.value()
        self.download_one_btn.setEnabled(False)

        def emit_log(line: str) -> None:
            self._log.emit(line)

        fut = self.service.submit(export_channel(ch, dest, limit=limit, log=emit_log))

        def done(f: Future) -> None:
            self.download_one_btn.setEnabled(True)
            if f.exception():
                self._save_failed.emit(str(f.exception()))
            else:
                self._save_done.emit(str(f.result()))

        fut.add_done_callback(done)

    def _download_all_channels(self) -> None:
        if not self._current_guild:
            return
        channels = self.service.text_channels(self._current_guild.id)
        if not channels:
            return
        confirm = QMessageBox.question(
            self,
            "Download all",
            f"Download up to {self.limit_box.value()} messages from "
            f"{len(channels)} channels in “{self._current_guild.name}”?\n\n"
            "Files will be saved (never executed).",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        dest = downloads_root() / "discord-browser" / safe_name(self._current_guild.name)
        limit = self.limit_box.value()
        self.download_all_btn.setEnabled(False)

        def emit_log(line: str) -> None:
            self._log.emit(line)

        fut = self.service.submit(
            export_channels(channels, dest, limit=limit, log=emit_log)
        )

        def done(f: Future) -> None:
            self.download_all_btn.setEnabled(True)
            if f.exception():
                self._save_failed.emit(str(f.exception()))
            else:
                self._save_done.emit(str(f.result()))

        fut.add_done_callback(done)

    # -- Save notification handlers -------------------------------------

    def _notify_save_done(self, path: str) -> None:
        self.typing.set_messages(["saved.", path[-40:]])
        QMessageBox.information(self, "Download finished", f"Saved to:\n{path}")

    def _notify_save_failed(self, err: str) -> None:
        self.typing.set_messages(["save failed."])
        QMessageBox.warning(self, "Download failed", err)


# ----- Font setup helper --------------------------------------------------


def install_optional_fonts() -> None:
    """Best-effort: load any TTFs found in ./fonts so the QSS family resolves."""
    folder = Path(__file__).resolve().parent / "fonts"
    if not folder.exists():
        return
    for f in folder.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))
    for f in folder.glob("*.otf"):
        QFontDatabase.addApplicationFont(str(f))
