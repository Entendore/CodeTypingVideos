"""
Code Typing Video Generator — application entry point.

Creates the input/, output/, tmp/ folders, configures logging,
launches the QApplication, applies the global professional stylesheet,
and shows the main window.

Run with:
    python -m code_typing_generator.app
or (when installed as a script):
    python app.py
"""

from __future__ import annotations

import logging
import os
import sys

if __name__ == "__main__" and __package__ is None:
    _dir = os.path.dirname(os.path.abspath(__file__))
    if _dir not in sys.path:
        sys.path.insert(0, os.path.dirname(_dir))  # parent dir so "import code_typing_generator.xxx" works
    # Register the package in sys.modules so relative imports resolve.
    _pkg_name = "code_typing_generator"
    __package__ = _pkg_name
    import types
    _pkg = types.ModuleType(_pkg_name)
    _pkg.__path__ = [_dir]
    _pkg.__package__ = _pkg_name
    _pkg.__file__ = os.path.join(_dir, "__init__.py")
    sys.modules[_pkg_name] = _pkg

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .config import (
    configure_logging, ensure_cwd_dirs, app_stylesheet,
    UI_FONT_STACK, UI_PALETTE,
)
from .main_window import MainWindow


def main() -> int:
    configure_logging(level=logging.INFO)
    ensure_cwd_dirs()

    app = QApplication(sys.argv)
    app.setApplicationName("Code Typing Video Generator")
    app.setOrganizationName("Z.ai")
    app.setStyle("Fusion")

    # Use a professional default font on systems that have it; Qt's
    # font substitution will pick the closest match otherwise.
    default_font = QFont(UI_FONT_STACK.split(",")[0].strip().strip("'\""), 10)
    app.setFont(default_font)

    # Apply the global dark stylesheet defined in config.py.
    app.setStyleSheet(app_stylesheet())

    # Set the app palette so native dialogs (file open, message boxes)
    # also inherit the dark theme rather than clashing with it.
    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    p = UI_PALETTE
    pal.setColor(QPalette.Window, QColor(p["bg_app"]))
    pal.setColor(QPalette.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.Base, QColor(p["bg_input"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["bg_panel"]))
    pal.setColor(QPalette.Text, QColor(p["text"]))
    pal.setColor(QPalette.Button, QColor(p["bg_panel"]))
    pal.setColor(QPalette.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(p["bg_panel"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["text"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["text_dim"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["text_dim"]))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
