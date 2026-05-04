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


def _prompt_token(app: QApplication) -> str | None:
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


def main() -> int:
    app = QApplication(sys.argv)
    install_optional_fonts()

    token = _prompt_token(app)
    if not token:
        QMessageBox.critical(None, "discord.", "A token is required.")
        return 1

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    service = DiscordService(token)
    window = MainWindow(service, loop)
    window.show()

    with loop:
        loop.create_task(service.start())
        loop.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
