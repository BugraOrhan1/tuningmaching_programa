"""Documented OS folder navigation only; WinOLS editing stays manual."""
from pathlib import Path


def open_project_folder(path: str) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    folder = Path(path).resolve()
    if not folder.is_dir():
        raise ValueError("Selecteer een bestaande projectmap")
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
        raise OSError("Projectmap kon niet worden geopend")
