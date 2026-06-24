"""
Custom Qt widgets used by the main window.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QFontMetrics
from PySide6.QtWidgets import QTextEdit


class DropTextEdit(QTextEdit):
    """A QTextEdit that accepts file drops with visual drag-hover feedback.

    Features:
      - Shows a dashed accent-coloured border when a file is dragged over.
      - Displays placeholder text when the editor is empty.
      - Emits ``files_dropped`` with the local file path on drop.
    """

    files_dropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drag_active = False
        self._placeholder_text = "Type or drop a code file here..."
        # PERF (v1.7): cache the placeholder QFontMetrics and colour
        # so paintEvent does not allocate them on every repaint.
        self._ph_color = QColor("#9aa0a6")
        self._ph_fm: Optional[QFontMetrics] = None
        self._ph_font: Optional[QFont] = None

    # ── placeholder ──────────────────────────────────────────────────
    def setPlaceholderText(self, text: str) -> None:
        self._placeholder_text = text
        # Re-trigger paint when empty.
        self.viewport().update()

    def placeholderText(self) -> str:
        return self._placeholder_text

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # Draw placeholder text if the editor is empty and not focused.
        if not self.toPlainText() and not self.hasFocus():
            # PERF (v1.7): cache QFontMetrics across paint events.
            # Only rebuild when the widget's font changes.
            font = self.font()
            if self._ph_font is not font:
                self._ph_font = font
                self._ph_fm = QFontMetrics(font)
            fm = self._ph_fm
            rect = self.viewport().rect().adjusted(8, 8, -8, -8)
            painter = QPainter(self.viewport())
            painter.setPen(self._ph_color)
            painter.drawText(rect, Qt.AlignTop | Qt.TextWordWrap, self._placeholder_text)
            painter.end()

    # ── drag/drop ─────────────────────────────────────────────────────
    def dragEnterEvent(self, event) -> None: 
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drag_active = True
            self.setProperty("dropActive", "true")
            self.style().unpolish(self)
            self.style().polish(self)
            self.viewport().update()
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None: 
        self._drag_active = False
        self.setProperty("dropActive", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event) -> None: 
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  
        self._drag_active = False
        self.setProperty("dropActive", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.viewport().update()
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    self.files_dropped.emit(url.toLocalFile())
                    break
        else:
            super().dropEvent(event)