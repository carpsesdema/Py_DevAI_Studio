# ui/dialogs/llm_terminal_window.py
import logging
from typing import Optional

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont, QCloseEvent, QFontDatabase

# Assuming constants.py is accessible
try:
    from utils import constants
except ImportError:
    # Fallback for direct execution or if path issues occur
    class constants:
        CHAT_FONT_FAMILY = "Arial"
        CHAT_FONT_SIZE = 10
    logging.warning("LlmTerminalWindow: Could not import constants, using fallback.")

logger = logging.getLogger(__name__)

class LlmTerminalWindow(QWidget):
    """
    A non-modal window to display LLM communication logs.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("LLM Communication Log")
        self.setObjectName("LlmTerminalWindow")
        self.setMinimumSize(600, 400)
        # self.setModal(False) # QWidget is non-modal by default when shown

        self._log_text_edit: Optional[QTextEdit] = None
        self._init_ui()
        logger.info("LlmTerminalWindow initialized.")

    def _init_ui(self):
        """Initialize the widgets for the dialog."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5) # Small margins
        main_layout.setSpacing(5)

        # Log Display Area
        self._log_text_edit = QTextEdit()
        self._log_text_edit.setObjectName("LlmLogTextEdit")
        self._log_text_edit.setReadOnly(True)

        # Set a monospace font, dark theme friendly
        # Using QFontDatabase.systemFont for better cross-platform compatibility
        # than hardcoding a specific font name that might not exist.
        log_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        log_font.setPointSize(constants.CHAT_FONT_SIZE -1) # Slightly smaller than main chat
        self._log_text_edit.setFont(log_font)

        # Basic dark theme styling (can be enhanced with QSS later)
        self._log_text_edit.setStyleSheet("""
            QTextEdit#LlmLogTextEdit {
                background-color: #21252B; /* Dark background */
                color: #ABB2BF; /* Light gray text */
                border: 1px solid #3A3F4B;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        main_layout.addWidget(self._log_text_edit, 1) # Text edit takes most space

        # Optional: Add a clear button if desired
        # clear_button = QPushButton("Clear Log")
        # clear_button.clicked.connect(self.clear_log)
        # button_layout = QHBoxLayout()
        # button_layout.addStretch()
        # button_layout.addWidget(clear_button)
        # main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    @pyqtSlot(str)
    def add_log_entry(self, text: str):
        """Appends a new log entry to the text edit and scrolls to the bottom."""
        if self._log_text_edit:
            self._log_text_edit.append(text) # append() also handles scrolling
            # self._log_text_edit.verticalScrollBar().setValue(
            #     self._log_text_edit.verticalScrollBar().maximum()
            # )
        else:
            logger.warning("LlmTerminalWindow: _log_text_edit is None, cannot add log entry.")

    @pyqtSlot()
    def clear_log(self):
        """Clears all text from the log display."""
        if self._log_text_edit:
            self._log_text_edit.clear()
            logger.info("LLM Terminal log cleared.")
        else:
            logger.warning("LlmTerminalWindow: _log_text_edit is None, cannot clear log.")

    def closeEvent(self, event: QCloseEvent):
        """Override close event to hide the window instead of destroying it."""
        logger.debug("LlmTerminalWindow closeEvent: Hiding window.")
        self.hide()
        event.ignore() # Prevent the window from being destroyed


if __name__ == '__main__':
    # Simple test application
    import sys
    from PyQt6.QtWidgets import QApplication, QPushButton

    logging.basicConfig(level=logging.DEBUG)

    app = QApplication(sys.argv)

    # Create a dummy parent window to show the terminal
    main_dummy_window = QWidget()
    main_dummy_window.setWindowTitle("Main App (Dummy)")
    main_dummy_window.setGeometry(100, 100, 300, 100)
    dummy_layout = QVBoxLayout(main_dummy_window)
    btn_show_terminal = QPushButton("Show LLM Terminal")
    dummy_layout.addWidget(btn_show_terminal)
    main_dummy_window.show()

    # Create and manage the terminal window
    llm_terminal_instance = LlmTerminalWindow()

    def show_terminal():
        llm_terminal_instance.show()
        llm_terminal_instance.activateWindow()
        llm_terminal_instance.raise_()
        # Test adding logs
        llm_terminal_instance.add_log_entry("Test Log Entry 1: Hello from the terminal!")
        llm_terminal_instance.add_log_entry("[System]: This is a system message.")
        for i in range(5):
            llm_terminal_instance.add_log_entry(f"Scroll test line {i+1}")


    btn_show_terminal.clicked.connect(show_terminal)

    sys.exit(app.exec())