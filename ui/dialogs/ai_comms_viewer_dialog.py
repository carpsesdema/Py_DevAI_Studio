# PyDevAI_Studio/ui/dialogs/ai_comms_viewer_dialog.py
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QDialogButtonBox, QApplication, QWidget
)
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtCore import pyqtSlot, Qt

from utils import constants
from core.ai_comms_logger import AICommsLogger

logger = logging.getLogger(constants.APP_NAME)


class AICommsViewerDialog(QDialog):
    MAX_TEXT_BLOCK_COUNT = 2000  # Buffer for this specific viewer

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("AI Communication Log Viewer")
        self.setMinimumSize(700, 500)
        self.setObjectName("AICommsViewerDialog")

        self._comms_logger_service: Optional[AICommsLogger] = None
        try:
            self._comms_logger_service = AICommsLogger.get_instance()
        except Exception as e:
            logger.error(f"AICommsViewerDialog: Failed to get AICommsLogger instance: {e}")

        self._log_display: Optional[QTextEdit] = None
        self._clear_button: Optional[QPushButton] = None
        self._copy_button: Optional[QPushButton] = None
        self._close_button: Optional[QPushButton] = None  # Standard close

        self._init_ui()
        self._connect_signals()
        self._load_initial_logs()
        self._ensure_connected_to_logger_service()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        log_font_family = self.font().family()
        log_font_size = constants.DEFAULT_FONT_SIZE - 1
        code_font_family_setting = constants.CODE_FONT_FAMILY
        if "JetBrains Mono" in QFontDatabase.families():
            log_font_family = "JetBrains Mono"
        elif code_font_family_setting:
            log_font_family = code_font_family_setting

        log_font = QFont(log_font_family, log_font_size)
        log_font.setStyleHint(QFont.StyleHint.Monospace)

        self._log_display = QTextEdit()
        self._log_display.setObjectName("AICommsDialogDisplayArea")
        self._log_display.setReadOnly(True)
        self._log_display.setFont(log_font)
        self._log_display.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._log_display.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c; }"
        )
        main_layout.addWidget(self._log_display, 1)

        button_layout = QHBoxLayout()
        self._clear_button = QPushButton("Clear Log")
        self._copy_button = QPushButton("Copy All")

        button_style = "QPushButton { padding: 5px 10px; background-color: #3a3d40; border: 1px solid #555555; border-radius: 3px; } QPushButton:hover { background-color: #4a4d50; } QPushButton:pressed { background-color: #2a2d30; }"
        self._clear_button.setStyleSheet(button_style)
        self._copy_button.setStyleSheet(button_style)

        button_layout.addWidget(self._clear_button)
        button_layout.addWidget(self._copy_button)
        button_layout.addStretch(1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._close_button = self.button_box.button(QDialogButtonBox.StandardButton.Close)  # Get reference
        if self._close_button: self._close_button.setStyleSheet(button_style)

        button_layout.addWidget(self.button_box)
        main_layout.addLayout(button_layout)

    def _connect_signals(self):
        if self._clear_button:
            self._clear_button.clicked.connect(self._clear_log_display_and_buffer)
        if self._copy_button:
            self._copy_button.clicked.connect(self._copy_all_logs)
        if self.button_box:
            self.button_box.rejected.connect(self.reject)  # Close button triggers reject

    def _ensure_connected_to_logger_service(self):
        if self._comms_logger_service:
            try:
                # Attempt to disconnect first to avoid multiple connections if dialog is reopened
                self._comms_logger_service.newLogMessage.disconnect(self._append_log_message)
            except TypeError:
                pass  # Signal was not connected
            self._comms_logger_service.newLogMessage.connect(self._append_log_message)
            logger.debug("AICommsViewerDialog connected to AICommsLogger.newLogMessage")

    def _load_initial_logs(self):
        if self._log_display and self._comms_logger_service:
            buffered_logs = self._comms_logger_service.get_buffered_logs()
            if buffered_logs:
                self._log_display.setPlainText("\n".join(buffered_logs))
                self._scroll_to_bottom()
            logger.info(f"AICommsViewerDialog loaded {len(buffered_logs)} buffered log messages.")

    @pyqtSlot(str)
    def _append_log_message(self, message: str):
        if self._log_display:
            doc = self._log_display.document()
            if doc.blockCount() > self.MAX_TEXT_BLOCK_COUNT:
                cursor = self._log_display.textCursor()
                cursor.movePosition(cursor.MoveOperation.Start)
                cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, int(doc.blockCount() * 0.1))
                cursor.removeSelectedText()
                cursor.deleteChar()
            self._log_display.append(message)

    def _scroll_to_bottom(self):
        if self._log_display:
            scrollbar = self._log_display.verticalScrollBar()
            if scrollbar:
                scrollbar.setValue(scrollbar.maximum())

    @pyqtSlot()
    def _clear_log_display_and_buffer(self):
        if self._log_display:
            self._log_display.clear()
        if self._comms_logger_service:
            self._comms_logger_service.clear_buffer()
        logger.info("AI Comms Viewer display and AICommsLogger buffer cleared by user.")

    @pyqtSlot()
    def _copy_all_logs(self):
        if self._log_display:
            try:
                clipboard = QApplication.clipboard()
                if clipboard:
                    clipboard.setText(self._log_display.toPlainText())
                    logger.info("AI Comms log content copied to clipboard.")
                else:
                    logger.error("AI Comms Viewer: Could not access system clipboard.")
            except Exception as e:
                logger.exception(f"AI Comms Viewer: Error copying log content: {e}")

    def done(self, result: int):
        logger.debug(f"AICommsViewerDialog done with result: {result}. Disconnecting from logger service.")
        if self._comms_logger_service:
            try:
                self._comms_logger_service.newLogMessage.disconnect(self._append_log_message)
                logger.debug("AICommsViewerDialog disconnected from AICommsLogger.newLogMessage")
            except TypeError:
                logger.debug("AICommsViewerDialog: Signal newLogMessage was already disconnected or never connected.")
            except Exception as e_disc:
                logger.error(f"AICommsViewerDialog: Error disconnecting signal on done: {e_disc}")
        super().done(result)

    def closeEvent(self, event):
        logger.debug("AICommsViewerDialog closeEvent triggered.")
        # done() method will handle disconnection
        super().closeEvent(event)