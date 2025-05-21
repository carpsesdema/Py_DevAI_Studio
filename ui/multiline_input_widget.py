# Llama_Syn/ui/multiline_input_widget.py
# UPDATED FILE - Standard Enter to Send, Shift+Enter for Newline

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtGui import QFont, QFontMetrics, QTextOption, QKeyEvent
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit

from utils import constants

logger = logging.getLogger(__name__)


class MultilineInputWidget(QWidget):
    sendMessageRequested = pyqtSignal()
    textChanged = pyqtSignal()

    MIN_LINES = 1
    MAX_LINES = 8
    LINE_PADDING = 8

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("MultilineInputWidget")

        self._text_edit: Optional[QTextEdit] = None
        self._min_height: int = 30
        self._max_height: int = 200

        self._init_ui()
        self._calculate_height_limits()
        self._connect_signals()
        self._update_height()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._text_edit = QTextEdit(self)
        self._text_edit.setObjectName("UserInputTextEdit")
        self._text_edit.setAcceptRichText(False)
        self._text_edit.setWordWrapMode(QTextOption.WrapMode.WordWrap)

        try:
            font = QFont(constants.CHAT_FONT_FAMILY, constants.CHAT_FONT_SIZE)
            self._text_edit.setFont(font)
        except Exception as e:
            logger.error(f"Error setting font for MultilineInputWidget: {e}")

        layout.addWidget(self._text_edit)
        self.setLayout(layout)

    def _calculate_height_limits(self):
        if not self._text_edit:
            return
        try:
            fm = QFontMetrics(self._text_edit.font())
            line_height = fm.height()
            min_base = line_height * self.MIN_LINES
            max_base = line_height * self.MAX_LINES
            doc_margin = int(self._text_edit.document().documentMargin())
            vertical_padding = self.LINE_PADDING + (doc_margin * 2)
            self._min_height = min_base + vertical_padding
            self._max_height = max_base + vertical_padding
            logger.debug(
                f"Calculated height limits: Min={self._min_height}, Max={self._max_height} (lineH={line_height})")
        except Exception as e:
            logger.error(f"Error calculating height limits: {e}. Using defaults.")

    def _connect_signals(self):
        if self._text_edit:
            self._text_edit.textChanged.connect(self.textChanged.emit)
            self._text_edit.textChanged.connect(self._update_height)

    @pyqtSlot()
    def _update_height(self):
        if not self._text_edit:
            return

        vp_width = self._text_edit.viewport().width()
        effective_width = vp_width if vp_width > 0 else self.width()
        if effective_width > 0:
            self._text_edit.document().setTextWidth(effective_width)

        doc_height = self._text_edit.document().size().height()
        doc_margin = int(self._text_edit.document().documentMargin())
        vertical_padding = self.LINE_PADDING + (doc_margin * 2)
        target_height = int(doc_height + vertical_padding)
        clamped_height = max(self._min_height, min(target_height, self._max_height))

        if self.height() != clamped_height:
            logger.debug(
                f"Resizing MultilineInput: docH={doc_height:.1f} -> targetH={target_height} -> clampedH={clamped_height}")
            self.setFixedHeight(clamped_height)
            self.updateGeometry()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()

        is_enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        is_shift_pressed = modifiers & Qt.KeyboardModifier.ShiftModifier

        if is_enter and not is_shift_pressed:
            logger.debug("Enter pressed (no Shift) in MultilineInputWidget, emitting sendMessageRequested.")
            self.sendMessageRequested.emit()
            event.accept()
        elif is_enter and is_shift_pressed:
            logger.debug("Shift+Enter pressed in MultilineInputWidget, allowing default newline insertion.")
            super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def get_text(self) -> str:
        return self._text_edit.toPlainText().strip() if self._text_edit else ""

    def clear_text(self):
        if self._text_edit:
            self._text_edit.clear()
            self.setFixedHeight(self._min_height)
            self.updateGeometry()

    def set_focus(self):
        if self._text_edit:
            self._text_edit.setFocus()

    def set_enabled(self, enabled: bool):
        if self._text_edit:
            self._text_edit.setEnabled(enabled)

    def setPlainText(self, text: str):
        if self._text_edit:
            self._text_edit.setPlainText(text)
            QTimer.singleShot(0, self._update_height)