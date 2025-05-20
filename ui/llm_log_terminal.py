import logging
from typing import Optional

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QSizePolicy, QApplication
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont, QFontDatabase

from utils import constants
from core.ai_comms_logger import AICommsLogger

logger = logging.getLogger(constants.APP_NAME)


class LlmLogTerminal(QWidget):
    MAX_TEXT_BLOCK_COUNT = 1500  # Increased buffer for more log history

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("LlmLogTerminalWidget")
        self.setMinimumSize(600, 150)  # Adjusted default size

        self._comms_logger_service: Optional[AICommsLogger] = None
        try:
            self._comms_logger_service = AICommsLogger.get_instance()
        except Exception as e:
            logger.error(f"LlmLogTerminal: Failed to get AICommsLogger instance: {e}")

        self._log_display: Optional[QTextEdit] = None
        self._clear_button: Optional[QPushButton] = None
        self._copy_button: Optional[QPushButton] = None

        self._init_widgets()
        self._init_layout()
        self._connect_signals()
        self._load_buffered_logs()
        logger.info("LlmLogTerminal initialized.")

    def _init_widgets(self) -> None:
        log_font_family = self.font().family()  # Use default UI font or a monospace one
        log_font_size = constants.DEFAULT_FONT_SIZE - 1  # Slightly smaller

        code_font_family_setting = constants.CODE_FONT_FAMILY
        if "JetBrains Mono" in QFontDatabase.families():  # Check if custom font loaded
            log_font_family = "JetBrains Mono"
        elif code_font_family_setting:
            log_font_family = code_font_family_setting

        log_font = QFont(log_font_family, log_font_size)
        log_font.setStyleHint(QFont.StyleHint.Monospace)

        self._log_display = QTextEdit()
        self._log_display.setObjectName("LlmLogDisplayArea")
        self._log_display.setReadOnly(True)
        self._log_display.setFont(log_font)
        self._log_display.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._log_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._log_display.setStyleSheet(
            "QTextEdit { background-color: #2B2B2B; color: #A9B7C6; border: 1px solid #3C3F41; }")

        self._clear_button = QPushButton("Clear Log")
        self._clear_button.setToolTip("Clear all messages from this viewer.")
        self._clear_button.setObjectName("LlmLogClearButton")

        self._copy_button = QPushButton("Copy All")
        self._copy_button.setToolTip("Copy the entire log to the clipboard.")
        self._copy_button.setObjectName("LlmLogCopyButton")

        button_style = "QPushButton { padding: 4px 8px; background-color: #4A4A4A; border: 1px solid #555555; border-radius: 3px; } QPushButton:hover { background-color: #555555; } QPushButton:pressed { background-color: #3D3D3D; }"
        self._clear_button.setStyleSheet(button_style)
        self._copy_button.setStyleSheet(button_style)

    def _init_layout(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(3)

        if self._log_display:
            main_layout.addWidget(self._log_display, 1)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(5)
        button_layout.addStretch(1)
        if self._copy_button: button_layout.addWidget(self._copy_button)
        if self._clear_button: button_layout.addWidget(self._clear_button)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def _connect_signals(self) -> None:
        if self._comms_logger_service:
            self._comms_logger_service.newLogMessage.connect(self._append_log_message)
        if self._clear_button:
            self._clear_button.clicked.connect(self._clear_display)
        if self._copy_button:
            self._copy_button.clicked.connect(self._copy_all_to_clipboard)

    def _load_buffered_logs(self) -> None:
        if self._log_display and self._comms_logger_service:
            buffered_logs = self._comms_logger_service.get_buffered_logs()
            if buffered_logs:
                self._log_display.setPlainText("\n".join(buffered_logs))  # Use setPlainText for initial load
                self._scroll_to_bottom()

    @pyqtSlot(str)
    def _append_log_message(self, message: str) -> None:
        if self._log_display:
            doc = self._log_display.document()
            if doc.blockCount() > self.MAX_TEXT_BLOCK_COUNT:
                cursor = self._log_display.textCursor()
                cursor.movePosition(cursor.MoveOperation.Start)
                cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor,
                                    int(doc.blockCount() * 0.1))  # Select first 10%
                cursor.removeSelectedText()
                cursor.deleteChar()  # Remove the newline that might be left

            self._log_display.append(message)
            # No need to call _scroll_to_bottom here if append handles it,
            # but explicit call ensures it if append's behavior changes or is complex.
            # self._scroll_to_bottom() # append usually scrolls, but can be explicit

    def _scroll_to_bottom(self) -> None:
        if self._log_display:
            scrollbar = self._log_display.verticalScrollBar()
            if scrollbar:
                scrollbar.setValue(scrollbar.maximum())

    @pyqtSlot()
    def _clear_display(self) -> None:
        if self._log_display:
            self._log_display.clear()
            logger.info("LLM Log Terminal display cleared by user.")
        if self._comms_logger_service:
            self._comms_logger_service.clear_buffer()

    @pyqtSlot()
    def _copy_all_to_clipboard(self) -> None:
        if self._log_display:
            try:
                clipboard = QApplication.clipboard()
                if clipboard:
                    clipboard.setText(self._log_display.toPlainText())
                    logger.info("LLM Log Terminal content copied to clipboard.")
                else:
                    logger.error("LLM Log Terminal: Could not access system clipboard.")
            except Exception as e:
                logger.exception(f"LLM Log Terminal: Error copying log content: {e}")

    def cleanup(self) -> None:
        if self._comms_logger_service:
            try:
                self._comms_logger_service.newLogMessage.disconnect(self._append_log_message)
            except TypeError:  # Already disconnected or never connected
                pass
            except Exception as e_disc:
                logger.error(f"LlmLogTerminal: Error disconnecting signal: {e_disc}")
        logger.info("LlmLogTerminal cleaned up signal connection.")