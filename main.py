"""Entry point for the Discord browser GUI.

Usage:
    DISCORD_TOKEN=... python main.py
    # or just `python main.py` and paste the token in the dialog.

Notes:
    - Self-bots violate the Discord Terms of Service. Use at your own risk.
    - Downloaded attachments are written to disk only — never executed.
"""
from __future__ import annotations

import asyncio
import os
import sys

import qasync
from PyQt6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox

from discord_service import DiscordService
from gui import MainWindow, install_optional_fonts


def _prompt_token() -> str | None:
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if token:
        return token
    text, ok = QInputDialog.getText(
        None,
        "discord. — token",
        "Paste your Discord user token:",
        QLineEdit.EchoMode.Password,
    )
    if not ok:
        return None
    text = text.strip()
    return text or None


async def _amain() -> None:
    app = QApplication.instance()
    assert app is not None  # qasync.run created it for us
    install_optional_fonts()

    token = _prompt_token()
    if not token:
        QMessageBox.critical(None, "discord.", "A token is required.")
        return

    loop = asyncio.get_event_loop()
    close_event = asyncio.Event()
    app.aboutToQuit.connect(close_event.set)

    service = DiscordService(token)
    window = MainWindow(service, loop)
    window.show()

    asyncio.ensure_future(service.start())
    try:
        await close_event.wait()
    finally:
        await service.stop()


def main() -> int:
    # qasync.run sets up a QApplication, installs the qasync event loop,
    # and runs the coroutine until completion. This is the documented
    # pattern — using `with loop: loop.run_forever()` leaves Qt's event
    # processing un-pumped and hangs discord.py-self at "connecting".
    if QApplication.instance() is None:
        QApplication(sys.argv)
    try:
        qasync.run(_amain())
    except asyncio.CancelledError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
