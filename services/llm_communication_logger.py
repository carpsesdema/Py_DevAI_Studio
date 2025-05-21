# services/llm_communication_logger.py
import logging

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class LlmCommunicationLogger(QObject):
    """
    A service responsible for receiving and formatting log messages
    related to LLM communications and emitting them for display.
    """
    new_terminal_log_entry = pyqtSignal(str)  # Signal to send formatted log string

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        logger.info("LlmCommunicationLogger initialized.")

    def log_message(self, prefix: str, message: str):
        """
        Formats a message with a prefix and emits it for the terminal.
        Example prefixes: "[Planner AI]", "[Code LLM]", "[System]", "[RAG]"
        """
        if not message:  # Don't log empty messages
            return

        # Simple formatting for now, can be expanded (e.g., timestamps)
        formatted_log_entry = f"{prefix}: {message.strip()}"
        logger.debug(f"LlmCommunicationLogger emitting: {formatted_log_entry}")
        self.new_terminal_log_entry.emit(formatted_log_entry)

    # --- Future specialized logging methods can be added here ---
    # def log_planner_action(self, action_description: str):
    #     self.log_message("[Planner AI]", action_description)

    # def log_coder_request(self, filename: str, instruction_summary: str):
    #     self.log_message("[Code LLM Req]", f"File: {filename} - Task: {instruction_summary[:100]}...")

    # def log_coder_response_chunk(self, filename: str, chunk_preview: str):
    #     self.log_message("[Code LLM Res]", f"File: {filename} - Chunk: {chunk_preview[:70]}...")

    # def log_system_process(self, process_description: str):
    #     self.log_message("[System Process]", process_description)

    # def log_error(self, component: str, error_message: str):
    #     self.log_message(f"[ERROR - {component}]", error_message)


if __name__ == '__main__':
    # Simple test for the logger
    from PyQt6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QWidget, QPushButton
    import sys

    logging.basicConfig(level=logging.DEBUG)

    app = QApplication(sys.argv)

    test_window = QWidget()
    test_window.setWindowTitle("Logger Test")
    layout = QVBoxLayout(test_window)
    log_display = QTextEdit()
    log_display.setReadOnly(True)
    button = QPushButton("Send Test Log")
    layout.addWidget(log_display)
    layout.addWidget(button)
    test_window.show()

    logger_instance = LlmCommunicationLogger()

    # Connect the signal to the QTextEdit's append slot
    logger_instance.new_terminal_log_entry.connect(log_display.append)


    def send_sample_logs():
        logger_instance.log_message("[Test System]", "This is a test system message.")
        logger_instance.log_message("[Test Planner]", "Planning to take over the world... or just make coffee.")
        logger_instance.log_message("[Test Coder]", "```python\nprint('Hello from test coder!')\n```")


    button.clicked.connect(send_sample_logs)

    sys.exit(app.exec())
