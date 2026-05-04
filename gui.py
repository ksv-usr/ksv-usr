from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import List, Optional

import discord
from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFontDatabase,
    QPalette,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from discord_service import DiscordService
from downloader import (
    ExportStats,
    downloads_root,
    export_channel,
    export_channels,
    safe_name,
    summarize,
)


# ----- Design tokens (the React landing-page rules, translated) ----------

CREAM = "#F3F4ED"
INK = "#1a1a1a"
INK_60 = "rgba(26,26,26,0.60)"
INK_40 = "rgba(26,26,26,0.40)"
INK_10 = "rgba(26,26,26,0.10)"
BLUE = "#0871E7"
BLUE_GLINT = "#DEF0FC"
NOKIA_FG = "#2A3616"

FONT_SERIF = "'Instrument Serif', 'Cormorant Garamond', 'Georgia', serif"
FONT_SANS = "'Inter', 'Helvetica Neue', 'Segoe UI', system-ui, sans-serif"
FONT_NOKIA = "'Nokia Cellphone FC Small', 'Px437 IBM VGA8', 'Courier New', monospace"


GLOBAL_QSS = f"""
QWidget {{
    background: {CREAM};
    color: {INK};
    font-family: {FONT_SANS};
    font-size: 14px;
}}
QLabel#brand {{
    background: transparent;
    font-family: {FONT_SERIF};
    font-size: 28px;
    color: {INK};
    letter-spacing: -0.5px;
}}
QLabel#hero {{
    background: transparent;
    font-family: {FONT_SERIF};
    color: {INK};
    letter-spacing: -1px;
}}
QLabel#sub {{
    background: transparent;
    font-family: {FONT_SANS};
    color: {INK_60};
}}
QLabel#nokia {{
    background: transparent;
    font-family: {FONT_NOKIA};
    color: {NOKIA_FG};
    font-size: 14px;
    line-height: 1.0;
}}
QFrame#navbar {{
    background: rgba(255,255,255,0.55);
    border: 1px solid {INK_10};
    border-radius: 28px;
}}
QPushButton[role="link"] {{
    background: transparent;
    border: none;
    color: {INK};
    font-size: 14px;
    padding: 4px 6px;
}}
QPushButton[role="link"]:hover {{ color: {INK_60}; }}
QPushButton[role="cta"] {{
    background: {BLUE};
    color: white;
    border: 1px solid {BLUE};
    border-radius: 18px;
    padding: 8px 18px;
    font-size: 14px;
}}
QPushButton[role="cta"]:hover {{ background: #1380F0; }}
QPushButton[role="cta"]:disabled {{ background: rgba(8,113,231,0.4); }}
QPushButton[role="ghost"] {{
    background: white;
    color: {INK};
    border: 1px solid {INK_10};
    border-radius: 14px;
    padding: 6px 14px;
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


# ----- Animation: cubic-bezier(0.16, 1, 0.3, 1) ---------------------------


def landing_ease() -> QEasingCurve:
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(0.16, 1.0), QPointF(0.3, 1.0), QPointF(1.0, 1.0))
    return c


def fade_in(widget: QWidget, *, duration: int, delay: int = 0) -> None:
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(landing_ease())
    if delay:
        QTimer.singleShot(delay, anim.start)
    else:
        anim.start()
    widget._fade_anim = anim  # keep ref


# ----- Reusable widgets ---------------------------------------------------


class CTAButton(QPushButton):
    """Blue rounded pill with the inner-glint and outline from the spec."""

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "cta")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        # Inset white glint at the top, per spec.
        self._glint = QFrame(self)
        self._glint.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f"stop:0 {BLUE_GLINT}, stop:1 transparent);"
            f"border: none; border-radius: 12px;"
        )
        self._glint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Outer drop shadow gives the button some lift.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(8, 113, 231, 90))
        self.setGraphicsEffect(shadow)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        w = int(self.width() * 0.8)
        x = int(self.width() * 0.10)
        self._glint.setGeometry(x, 1, w, 16)


class GhostButton(QPushButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Navbar(QFrame):
    """Pill navbar matching the spec: brand, links, CTA."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("navbar")
        self.setFixedHeight(56)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 8, 8)
        layout.setSpacing(28)

        brand = QLabel("dot.")
        brand.setObjectName("brand")
        layout.addWidget(brand)

        layout.addStretch(1)
        for name in ("Philosophy", "Trust", "Access", "Tribe"):
            btn = QPushButton(name)
            btn.setProperty("role", "link")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setEnabled(False)  # decorative, per spec
            layout.addWidget(btn)

        layout.addStretch(1)
        self.cta = CTAButton("Link up")
        layout.addWidget(self.cta)


class TypingMessages(QLabel):
    """Cycles through ["Are you here?", "Yes, I am.", "Speak soon."] per spec.

    Typing speed 100ms, deleting 50ms, pause 2000ms before deleting.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("nokia")
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._messages: List[str] = ["Are you here?", "Yes, I am.", "Speak soon."]
        self._idx = 0
        self._sub = 0
        self._deleting = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._cursor_on = True
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._blink)
        self._cursor_timer.start(800)
        self._timer.start(100)
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
        self._cursor_on = not self._cursor_on
        self._render()

    def _render(self) -> None:
        msg = self._messages[self._idx][: self._sub]
        cursor = "▌" if self._cursor_on else " "
        self.setText(f"{msg}{cursor}")


class Hero(QWidget):
    """Hero section: video bg, white/5 tint, centered headline, sub, typing overlay."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(640)
        self.setStyleSheet(f"background: {CREAM};")

        # --- Video background ---------------------------------------------
        # Disabled: the cloudfront h264 file uses Late SEI which the local
        # ffmpeg decoder cannot handle, spamming stderr with thousands of
        # "Late SEI is not implemented" lines and slowing the app. The cream
        # background alone matches the page palette and stays calm.
        self._video_widget = None
        self._player = None
        self._audio = None

        # --- white/5 tint overlay -----------------------------------------
        self._tint = QWidget(self)
        self._tint.setStyleSheet("background: rgba(255,255,255,0.05);")
        self._tint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # --- headlines & typing -------------------------------------------
        self.headline = QLabel("Short notes.\nDaily calm.", self)
        self.headline.setObjectName("hero")
        self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.headline.setStyleSheet(
            f"background: transparent; font-family: {FONT_SERIF};"
            f"font-size: 56px; color: {INK}; letter-spacing: -1px; line-height: 0.85;"
        )

        self.subline = QLabel(
            "Linked with a single anonymous peer. One message every day. "
            "A quiet rhythm in the digital noise.",
            self,
        )
        self.subline.setObjectName("sub")
        self.subline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subline.setWordWrap(True)
        self.subline.setStyleSheet(
            f"background: transparent; font-family: {FONT_SANS};"
            f"font-size: 16px; color: {INK_60};"
        )

        self.typing = TypingMessages(self)
        self.typing.setStyleSheet(
            f"background: transparent; font-family: {FONT_NOKIA};"
            f"color: {NOKIA_FG}; font-size: 14px;"
        )
        self.typing.setFixedSize(130, 22)

        # Animations: opacity 0->1 + scale-ish via delay; ease [0.16,1,0.3,1].
        fade_in(self.headline, duration=1500)
        fade_in(self.subline, duration=1200, delay=300)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if self._video_widget is not None:
            self._video_widget.setGeometry(0, 0, w, h)
        self._tint.setGeometry(0, 0, w, h)

        # pt-24 / pt-32 -> reserve top space for the floating navbar.
        top_pad = 128
        avail_w = max(0, w - 80)

        self.headline.setFixedWidth(min(900, avail_w))
        self.headline.adjustSize()
        hl_w, hl_h = self.headline.width(), self.headline.height()
        hl_x = (w - hl_w) // 2
        # Vertical center, biased a little above middle.
        hl_y = max(top_pad, h // 2 - hl_h - 40)
        self.headline.move(hl_x, hl_y)

        self.subline.setFixedWidth(min(580, avail_w))
        self.subline.adjustSize()
        sub_w, sub_h = self.subline.width(), self.subline.height()
        self.subline.move((w - sub_w) // 2, hl_y + hl_h + 24)

        # TypingMessages over the phone screen: bottom-[32%] left-[48.5%]
        # with -translate-x-1/2.
        tw, th = self.typing.width(), self.typing.height()
        ty = int(h * (1 - 0.32)) - th
        tx = int(w * 0.485) - tw // 2
        self.typing.move(tx, ty)


# ----- Main window --------------------------------------------------------


class ChannelRow(QFrame):
    """One channel: name + small download button."""

    download_clicked = pyqtSignal(int)

    def __init__(self, channel: discord.TextChannel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._channel_id = channel.id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(8)

        label = QLabel(f"# {channel.name}")
        label.setStyleSheet(f"background:transparent; color:{INK}; font-size:14px;")
        layout.addWidget(label, 1)

        cat = channel.category.name if channel.category else ""
        if cat:
            tag = QLabel(cat)
            tag.setStyleSheet(f"background:transparent; color:{INK_40}; font-size:12px;")
            layout.addWidget(tag)

        self.btn = GhostButton("Download")
        self.btn.setMinimumHeight(28)
        self.btn.clicked.connect(lambda: self.download_clicked.emit(self._channel_id))
        layout.addWidget(self.btn)


class MainWindow(QMainWindow):
    _save_done = pyqtSignal(str)
    _save_failed = pyqtSignal(str)
    _log = pyqtSignal(str)

    def __init__(self, service: DiscordService) -> None:
        super().__init__()
        self.service = service
        self._current_guild: Optional[discord.Guild] = None

        self.setWindowTitle("dot. — quiet discord browser")
        self.resize(1280, 880)
        self.setStyleSheet(GLOBAL_QSS)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(CREAM))
        self.setPalette(pal)

        # Scrollable content (hero + functional area).
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setStyleSheet(f"background: {CREAM};")
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.hero = Hero()
        v.addWidget(self.hero)
        v.addWidget(self._build_functional())
        self._scroll.setWidget(content)
        self.setCentralWidget(self._scroll)

        # Floating navbar: positioned in resizeEvent on top of scroll content.
        self.navbar = Navbar(self)
        self.navbar.cta.setText("Linking up…")
        self.navbar.cta.setEnabled(False)
        self.navbar.raise_()

        # Service signals
        self.service.ready.connect(self._on_ready)
        self.service.error.connect(self._on_error)
        # Internal cross-thread signals
        self._save_done.connect(self._notify_save_done)
        self._save_failed.connect(self._notify_save_failed)
        self._log.connect(self._on_log)

    # -- Functional area (servers + channels) ---------------------------

    def _build_functional(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setStyleSheet(f"background: {CREAM};")
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(40, 32, 40, 56)
        outer.setSpacing(20)

        section_title = QLabel("Browse quietly.")
        section_title.setStyleSheet(
            f"background:transparent; font-family:{FONT_SERIF};"
            f"font-size:32px; color:{INK}; letter-spacing:-0.5px;"
        )
        section_title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(section_title)

        sub = QLabel(
            "Pick a server, save its channels. Files are written, never run."
        )
        sub.setStyleSheet(f"background:transparent; color:{INK_60}; font-size:14px;")
        outer.addWidget(sub)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        outer.addLayout(cols, 1)

        cols.addWidget(self._build_server_panel(), 1)
        cols.addWidget(self._build_channel_panel(), 2)
        return wrapper

    def _panel_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumHeight(420)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        header = QLabel(title)
        header.setStyleSheet(
            f"background:transparent; font-family:{FONT_SERIF};"
            f"font-size:22px; color:{INK};"
        )
        layout.addWidget(header)
        return card, layout

    def _build_server_panel(self) -> QFrame:
        card, layout = self._panel_card("Servers")
        self.server_status = QLabel("Linking up…")
        self.server_status.setStyleSheet(
            f"background:transparent; color:{INK_60}; font-size:12px;"
        )
        layout.addWidget(self.server_status)
        self.server_list = QListWidget()
        self.server_list.setSpacing(2)
        self.server_list.itemSelectionChanged.connect(self._on_server_selected)
        layout.addWidget(self.server_list, 1)
        return card

    def _build_channel_panel(self) -> QFrame:
        card, layout = self._panel_card("Channels")

        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.channel_status = QLabel("Pick a server.")
        self.channel_status.setStyleSheet(
            f"background:transparent; color:{INK_60}; font-size:12px;"
        )
        head_row.addWidget(self.channel_status, 1)
        head_row.addWidget(QLabel("Limit:"))
        self.limit_box = QSpinBox()
        self.limit_box.setRange(50, 100000)
        self.limit_box.setSingleStep(50)
        self.limit_box.setValue(500)
        head_row.addWidget(self.limit_box)
        self.download_all_btn = CTAButton("Download all")
        self.download_all_btn.setEnabled(False)
        self.download_all_btn.clicked.connect(self._download_all_channels)
        head_row.addWidget(self.download_all_btn)
        layout.addLayout(head_row)

        # Scrollable list of channel rows (each with its own download button).
        self.channel_scroll = QScrollArea()
        self.channel_scroll.setWidgetResizable(True)
        self.channel_container = QWidget()
        self.channel_layout = QVBoxLayout(self.channel_container)
        self.channel_layout.setContentsMargins(0, 0, 0, 0)
        self.channel_layout.setSpacing(8)
        self.channel_layout.addStretch(1)
        self.channel_scroll.setWidget(self.channel_container)
        layout.addWidget(self.channel_scroll, 1)
        return card

    # -- Service callbacks ---------------------------------------------

    def _on_ready(self) -> None:
        me = self.service.me
        who = str(me) if me else "you"
        self.navbar.cta.setText("Linked up")
        self.navbar.cta.setEnabled(False)
        self.server_status.setText(f"Hi {who}. Loading guilds…")
        self._refresh_servers()

    def _on_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Discord", msg)
        self.server_status.setText(msg)

    def _on_log(self, line: str) -> None:
        self.server_status.setText(line[:80])

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
        # Clear all existing rows.
        while self.channel_layout.count() > 1:
            item = self.channel_layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w:
                w.deleteLater()
        if not self._current_guild:
            return
        channels = self.service.text_channels(self._current_guild.id)
        self.channel_status.setText(
            f"{len(channels)} channels in {self._current_guild.name}"
        )
        self.download_all_btn.setEnabled(bool(channels))
        for ch in channels:
            row = ChannelRow(ch)
            row.download_clicked.connect(self._download_one_channel)
            self.channel_layout.insertWidget(self.channel_layout.count() - 1, row)

    # -- Downloads ------------------------------------------------------

    def _download_one_channel(self, channel_id: int) -> None:
        ch = self.service.get_channel(channel_id)
        if ch is None:
            return
        guild_name = self._current_guild.name if self._current_guild else "dm"
        dest = downloads_root() / "discord-browser" / safe_name(guild_name)
        limit = self.limit_box.value()

        def emit_log(line: str) -> None:
            self._log.emit(line)

        fut = self.service.submit(
            export_channel(
                ch, dest,
                client=self.service.client,
                limit=limit,
                log=emit_log,
            )
        )

        def done(f: Future) -> None:
            if f.exception():
                self._save_failed.emit(str(f.exception()))
                return
            stats: ExportStats = f.result()
            body = (
                f"{stats.label}\n"
                f"  {stats.messages} messages, {stats.attachments} attachments, "
                f"{stats.cdn_files} CDN files, {stats.other_links} links\n"
                f"\n{stats.folder}"
            )
            if stats.errors:
                body += f"\n\n{len(stats.errors)} error(s) — see _export.log"
            self._save_done.emit(body)

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
            "Files are written to disk, never run.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        dest = downloads_root() / "discord-browser" / safe_name(self._current_guild.name)
        limit = self.limit_box.value()
        self.download_all_btn.setEnabled(False)

        def emit_log(line: str) -> None:
            self._log.emit(line)

        fut = self.service.submit(
            export_channels(
                channels, dest,
                client=self.service.client,
                limit=limit,
                log=emit_log,
            )
        )

        def done(f: Future) -> None:
            self.download_all_btn.setEnabled(True)
            if f.exception():
                self._save_failed.emit(str(f.exception()))
                return
            stats_list = f.result()
            body = summarize(stats_list) + f"\n\n{dest}"
            self._save_done.emit(body)

        fut.add_done_callback(done)

    def _notify_save_done(self, body: str) -> None:
        QMessageBox.information(self, "Download finished", body)

    def _notify_save_failed(self, err: str) -> None:
        QMessageBox.warning(self, "Download failed", err)

    # -- Floating navbar layout ---------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Pill navbar: top-6, w-95% max-w-5xl, centered, z-50.
        nav_max = 1024  # max-w-5xl
        nav_w = min(int(self.width() * 0.95), nav_max)
        nav_h = 56
        nav_x = (self.width() - nav_w) // 2
        nav_y = 24
        self.navbar.setGeometry(nav_x, nav_y, nav_w, nav_h)
        self.navbar.raise_()


# ----- Font setup helper --------------------------------------------------


def install_optional_fonts() -> None:
    """Best-effort: load any TTFs in ./fonts so the QSS family resolves."""
    folder = Path(__file__).resolve().parent / "fonts"
    if not folder.exists():
        return
    for f in folder.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))
    for f in folder.glob("*.otf"):
        QFontDatabase.addApplicationFont(str(f))
