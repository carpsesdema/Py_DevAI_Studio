# services/llm_communication_logger.py
import logging
from datetime import datetime  # Added for timestamp in rich output
import html  # For escaping message content for HTML
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

# --- Rich Imports for awesome terminal styling! ---
try:
    from rich.console import Console
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None  # type: ignore
    Text = None  # type: ignore
    logging.warning("LlmCommunicationLogger: 'rich' library not found. System terminal output will not be styled.")
# --- End Rich Imports ---

logger = logging.getLogger(__name__)

# --- Configuration for Log Styling ---

# Styles for Rich (actual system terminal)
RICH_SENDER_STYLES = {
    "ERROR": "bold red", "WARN": "bold orange3",
    "PLANNER AI": "bold cyan", "CODE LLM": "bold green",
    "SYSTEM": "bold yellow", "USER": "bold dodger_blue1",
    "RAG": "bold magenta1", "PROCESS": "bold blue",
    "INFO": "dim",
}
RICH_DEFAULT_SENDER_STYLE = "bold"
RICH_TIMESTAMP_STYLE = "dim"

# Styles for HTML (GUI's LLM Terminal Window)
# Using hex colors for HTML.
HTML_SENDER_STYLES = {
    # Keyword: (text_color_hex, is_bold)
    "ERROR": ("#FF4444", True), "WARN": ("#FFA500", True),  # Red, Orange
    "PLANNER AI": ("#00FFFF", True),  # Cyan
    "CODE LLM": ("#00FF00", True),  # Green
    "SYSTEM": ("#FFFF00", True),  # Yellow
    "USER": ("#1E90FF", True),  # DodgerBlue
    "RAG": ("#FF00FF", True),  # Magenta
    "PROCESS": ("#0077FF", True),  # A nice blue
    "INFO": ("#AAAAAA", False),  # Dim gray
}
HTML_DEFAULT_SENDER_STYLE = ("#DCDCDC", True)  # Default: Light Gray, Bold
HTML_TIMESTAMP_COLOR = "#888888"  # Dim gray for timestamp in HTML


# --- End Log Styling Configuration ---


class LlmCommunicationLogger(QObject):
    """
    A service responsible for receiving and formatting log messages
    related to LLM communications.
    - Prints styled output to the system console if 'rich' is available.
    - Emits HTML formatted log strings for the GUI's LLM Terminal.
    """
    new_terminal_log_entry = pyqtSignal(str)  # Signal to send formatted HTML log string

    _console: Optional[Console] = None
    if RICH_AVAILABLE and Console:
        _console = Console()

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        logger.info("LlmCommunicationLogger initialized.")
        if not RICH_AVAILABLE and self._console is None:
            logger.info("LlmCommunicationLogger: 'rich' not available, system console output will be plain.")

    def log_message(self, prefix: str, message: str):
        if not message:
            return

        timestamp_dt = datetime.now()
        rich_timestamp_str = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        html_timestamp_str = timestamp_dt.strftime("%H:%M:%S")  # Simpler for GUI

        # --- Rich System Terminal Output (Styled) ---
        if RICH_AVAILABLE and self._console and Text:
            text_for_rich_console = Text()
            text_for_rich_console.append(f"[{rich_timestamp_str}] ", style=RICH_TIMESTAMP_STYLE)
            chosen_rich_style = RICH_DEFAULT_SENDER_STYLE
            prefix_upper = prefix.upper()
            for keyword, style in RICH_SENDER_STYLES.items():
                if keyword in prefix_upper:
                    chosen_rich_style = style
                    break
            text_for_rich_console.append(f"{prefix}: ", style=chosen_rich_style)
            text_for_rich_console.append(message.strip())
            try:
                self._console.print(text_for_rich_console)
            except Exception as e_rich:
                # Fallback to plain print if rich fails for some reason (e.g. complex content)
                print(f"RICH_PRINT_ERROR: [{rich_timestamp_str}] {prefix}: {message.strip()} (Error: {e_rich})")
        # --- End Rich System Terminal Output ---

        # --- HTML for GUI Terminal ---
        chosen_html_color, chosen_html_bold = HTML_DEFAULT_SENDER_STYLE
        prefix_upper_html = prefix.upper()
        for keyword, (color_hex, is_bold) in HTML_SENDER_STYLES.items():
            if keyword in prefix_upper_html:
                chosen_html_color = color_hex
                chosen_html_bold = is_bold
                break

        # Escape the main message content to prevent HTML injection issues
        escaped_message = html.escape(message.strip())

        # Construct HTML string
        html_parts = [
            f'<span style="color: {HTML_TIMESTAMP_COLOR};">[{html_timestamp_str}]</span> '
        ]
        prefix_style_str = f'color: {chosen_html_color};'
        if chosen_html_bold:
            prefix_style_str += ' font-weight: bold;'

        html_parts.append(f'<span style="{prefix_style_str}">{html.escape(prefix)}:</span> ')
        # Regular message text color (can be made configurable if needed, for now default)
        html_parts.append(f'<span style="color: #DCDCDC;">{escaped_message}</span>')

        formatted_log_entry_for_gui = "".join(html_parts)
        self.new_terminal_log_entry.emit(formatted_log_entry_for_gui)


if __name__ == '__main__':
    from PyQt6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QWidget, QPushButton
    import sys
    import time

    logging.basicConfig(level=logging.DEBUG)

    app = QApplication(sys.argv)

    test_window = QWidget()
    test_window.setWindowTitle("LLM Log GUI Test")
    layout = QVBoxLayout(test_window)
    log_display_gui = QTextEdit()
    log_display_gui.setReadOnly(True)
    log_display_gui.setFontFamily("Monospace")
    log_display_gui.setStyleSheet("background-color: #21252B; color: #ABB2BF;")  # Base style for the QTextEdit
    button = QPushButton("Send Test Log")
    layout.addWidget(log_display_gui)
    layout.addWidget(button)
    test_window.resize(700, 500)
    test_window.show()

    logger_instance = LlmCommunicationLogger()

    # IMPORTANT: Connect to appendHtml for the GUI test
    logger_instance.new_terminal_log_entry.connect(log_display_gui.appendHtml)

    print("\n" + "=" * 20 + " System Terminal Output (Rich) " + "=" * 20)
    print("The following logs should appear styled in your ACTUAL terminal (if 'rich' is installed).")
    print("They will also appear as STYLED HTML in the GUI window above.")
    print("=" * 70 + "\n")


    def send_sample_logs():
        log_display_gui.appendHtml("<hr>--- Sending Sample Logs ---<hr>")  # GUI separator
        print("\n--- Sending Sample Logs (to actual system terminal) ---")  # Console separator

        logger_instance.log_message("[Test System]",
                                    "This is a test system message with <b>bold HTML attempt</b> and <font color='red'>red text</font>.")
        time.sleep(0.1)
        logger_instance.log_message("[Planner AI]", "Planning to take over the world... or just make coffee. ☕")
        time.sleep(0.1)
        logger_instance.log_message("[Code LLM]",
                                    "```python\n# This is Python code\nprint('Hello from test coder!')\nfor i in range(5):\n    print(f'Iteration {i}')\n```")
        time.sleep(0.1)
        logger_instance.log_message("[RAG Query]", "User asked about 'Python context managers'. Let's find some docs!")
        time.sleep(0.1)
        logger_instance.log_message("[USER ACTION]", "User clicked the 'Generate' button. Exciting!")
        time.sleep(0.1)
        logger_instance.log_message("[System Process]", "Initiating sequence X... Hold on to your hats! 🎩")
        time.sleep(0.1)
        logger_instance.log_message("[ERROR - Code LLM]",
                                    "Failed to parse generated code: Unexpected token 'gah'. Oops! 😱")
        time.sleep(0.1)
        logger_instance.log_message("[WARNING - Planner AI]",
                                    "Plan may be too complex for current token limit. We'll try our best! 👍")
        time.sleep(0.1)
        logger_instance.log_message("[Some Other Prefix]", "This will use the default style. How does it look?")
        time.sleep(0.1)
        logger_instance.log_message("[INFO]", "Just a piece of information here. Nothing to see, move along... 😉")

        log_display_gui.appendHtml("<hr>--- Sample Logs Sent ---<hr>")
        print("\n--- Sample Logs Sent (to actual system terminal) ---\n")


    button.clicked.connect(send_sample_logs)
    send_sample_logs()

    sys.exit(app.exec())