import logging
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt6.QtCore import pyqtSlot, Qt, pyqtSignal

from utils import constants
from core.orchestrator import AppOrchestrator
from core.project_manager import Project  # For type hinting if needed
from core.ai_comms_logger import AICommsLogger  # For potential direct logging if needed

logger = logging.getLogger(constants.APP_NAME)

try:
    from .components.chat_display_area import ChatDisplayArea
    from .components.chat_input_bar import ChatInputBar
    from .components.chat_message_delegate import ChatMessage  # For type hinting
except ImportError:
    logger.critical("ChatPane: Failed to import custom UI components. Using placeholders.")
    ChatDisplayArea = type("ChatDisplayArea", (QWidget,), {
        "add_message_to_model": lambda self, msg: None,
        "load_history_into_model": lambda self, hist: None,
        "clear_model_display": lambda self: None,
        "start_streaming_in_model": lambda self, msg: None,
        "append_stream_chunk_to_model": lambda self, chunk: None,
        "finalize_stream_in_model": lambda self: None,
        "update_message_in_model": lambda self, idx, msg: None,
    })
    ChatInputBar = type("ChatInputBar", (QWidget,), {
        "sendMessageRequested": pyqtSignal(str, list),
        "handle_busy_state": lambda self, busy: None,
        "clear_text": lambda self: None,
        "set_focus": lambda self: None,
        "set_enabled": lambda self, enabled: None,
    })
    ChatMessage = dict


class ChatPane(QWidget):
    send_message_to_chat_llm = pyqtSignal(list, str)  # messages: List[ChatMessage], request_id: str
    user_typed_message_for_display = pyqtSignal(object)  # ChatMessage object

    def __init__(self, orchestrator: AppOrchestrator, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.settings = orchestrator.get_settings()
        self.comms_logger = orchestrator.get_comms_logger()
        self.setObjectName("ChatPane")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.chat_display_area: Optional[ChatDisplayArea] = None
        self.chat_input_bar: Optional[ChatInputBar] = None

        self._current_project_id: Optional[str] = None
        self._is_llm_busy: bool = False

        self._init_ui()
        self._connect_signals()
        logger.info("ChatPane initialized.")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.chat_display_area = ChatDisplayArea(self)
        self.chat_input_bar = ChatInputBar(self)

        layout.addWidget(self.chat_display_area, 1)
        layout.addWidget(self.chat_input_bar)

        self.setLayout(layout)

    def _connect_signals(self) -> None:
        if self.chat_input_bar:
            self.chat_input_bar.sendMessageRequested.connect(self._handle_send_message_requested)

        if self.orchestrator and self.orchestrator.get_llm_manager():
            llm_manager = self.orchestrator.get_llm_manager()
            # Note: chat_llm_response_received is connected by MainWindow to ChatPane's public slots

    def async_initialize_chat_pane(self) -> None:  # Renamed from initialize_chat_pane to avoid conflict
        logger.info("ChatPane asynchronous initialization...")
        # Any async setup for chat pane specifically
        if self.chat_input_bar:
            self.chat_input_bar.set_focus()
        self.update_busy_state(False)  # Initial state

    @pyqtSlot(str, list)  # text, image_data_list
    def _handle_send_message_requested(self, text: str, image_data_list: List[Dict[str, Any]]) -> None:
        if not text.strip() and not image_data_list:
            logger.info("Empty message send request ignored.")
            return

        if self._is_llm_busy:
            logger.warning("Chat LLM is busy. Send request ignored.")
            # Optionally show a message to the user via status bar
            return

        import uuid
        user_message_id = str(uuid.uuid4())

        user_parts = []
        if text.strip():
            user_parts.append(text.strip())
        if image_data_list:
            user_parts.extend(image_data_list)

        user_chat_message = ChatMessage(
            role="user",
            content=text.strip(),  # Main text content
            image_data=image_data_list if image_data_list else None,
            metadata={"id": user_message_id, "timestamp": self._get_timestamp()}
        )

        self.user_typed_message_for_display.emit(user_chat_message)  # For MainWindow to add to model

        if self.chat_input_bar:
            self.chat_input_bar.clear_text()

        llm_request_id = str(uuid.uuid4())

        # Prepare history for LLM
        # This needs to get history from the ProjectManager for the current project
        history_for_llm: List[ChatMessage] = []
        if self.orchestrator and self.orchestrator.get_project_manager() and self._current_project_id:
            project_manager = self.orchestrator.get_project_manager()
            raw_history = project_manager.get_chat_history(self._current_project_id)  # Assuming this method exists
            if raw_history:
                for msg_dict in raw_history:  # Assuming history is list of dicts from ProjectManager
                    try:
                        # Reconstruct ChatMessage objects if ProjectManager stores dicts
                        # This part depends heavily on how ProjectManager stores history
                        history_for_llm.append(ChatMessage(
                            role=msg_dict.get("role", "user"),
                            content=msg_dict.get("content", ""),
                            image_data=msg_dict.get("image_data"),
                            metadata=msg_dict.get("metadata")
                        ))
                    except Exception as e_hist:
                        logger.error(f"Error reconstructing history message: {e_hist}")
            history_for_llm.append(user_chat_message)  # Add current user message

        elif self._current_project_id:  # No history but project exists
            history_for_llm.append(user_chat_message)
        else:  # No project context, send current message only
            history_for_llm.append(user_chat_message)

        self.send_message_to_chat_llm.emit(history_for_llm, llm_request_id)

        placeholder_ai_message = ChatMessage(
            role="assistant",
            content="",
            metadata={"id": llm_request_id, "is_streaming": True, "timestamp": self._get_timestamp()}
        )
        if self.chat_display_area:
            self.chat_display_area.start_streaming_in_model(placeholder_ai_message)

    def _get_timestamp(self) -> str:
        import datetime
        return datetime.datetime.now().isoformat()

    @pyqtSlot(str)  # project_id
    def load_chat_history(self, project_id: str) -> None:
        self._current_project_id = project_id
        logger.info(f"ChatPane: Loading history for project ID: {project_id}")
        if self.chat_display_area:
            history_to_load: List[ChatMessage] = []
            if self.orchestrator and self.orchestrator.get_project_manager():
                raw_history = self.orchestrator.get_project_manager().get_chat_history(project_id)
                if raw_history:
                    for msg_dict in raw_history:
                        try:
                            history_to_load.append(ChatMessage(
                                role=msg_dict.get("role", "user"),
                                content=msg_dict.get("content", ""),
                                image_data=msg_dict.get("image_data"),
                                metadata=msg_dict.get("metadata")
                            ))
                        except Exception as e_load_hist:
                            logger.error(f"Error reconstructing loaded history message: {e_load_hist}")

            self.chat_display_area.load_history_into_model(history_to_load)
        if self.chat_input_bar:
            self.chat_input_bar.set_focus()

    def clear_chat_display(self) -> None:
        if self.chat_display_area:
            self.chat_display_area.clear_model_display()


@pyqtSlot(bool)
def update_busy_state(self, is_busy: bool) -> None:
    self._is_llm_busy = is_busy
    if self.chat_input_bar:
        self.chat_input_bar.handle_busy_state(is_busy)
    logger.debug(f"ChatPane busy state updated: {is_busy}")


@pyqtSlot(object)  # ChatMessage
def add_user_message_to_display(self, message: ChatMessage) -> None:
    if self.chat_display_area:
        self.chat_display_area.add_message_to_model(message)


@pyqtSlot(str, bool)  # message_text, is_error
def add_message_from_llm(self, message_text: str, is_error: bool) -> None:
    if not self.chat_display_area:
        logger.error("ChatDisplayArea not available to add LLM message.")
        return

    if self._is_llm_busy and not is_error:  # If it's a streaming chunk
        self.chat_display_area.append_stream_chunk_to_model(message_text)
    else:  # First part of a stream, a complete non-streamed message, or an error
        # This logic needs to be more robust to handle message IDs for updates
        # For now, assuming this is called to finalize a stream or show a full error
        if self._is_llm_busy and not is_error:  # Finalizing a stream
            self.chat_display_area.finalize_stream_in_model()
            # The last message in display_area's model should be the one to update
            # This might need adjustment if multiple requests can be in flight.
            # For now, assuming one active stream.
            model = self.chat_display_area.get_model()
            if model and model.rowCount() > 0:
                last_msg_idx = model.rowCount() - 1
                last_msg_obj = model.getMessage(last_msg_idx)
                if last_msg_obj and last_msg_obj.role == "assistant" and \
                        last_msg_obj.metadata and last_msg_obj.metadata.get("is_streaming"):

                    # Update existing placeholder with full content
                    last_msg_obj.content = self.chat_display_area.get_last_message_full_text()  # Assuming a method to get full streamed text
                    last_msg_obj.metadata["is_streaming"] = False
                    if is_error:  # Should not happen if finalizing stream
                        last_msg_obj.role = "error"
                    self.chat_display_area.update_message_in_model(last_msg_idx, last_msg_obj)
                else:  # Should not happen, but as a fallback, add new
                    final_message = ChatMessage(role="error" if is_error else "assistant", content=message_text,
                                                metadata={"timestamp": self._get_timestamp()})
                    self.chat_display_area.add_message_to_model(final_message)
            else:  # No messages, add new
                final_message = ChatMessage(role="error" if is_error else "assistant", content=message_text,
                                            metadata={"timestamp": self._get_timestamp()})
                self.chat_display_area.add_message_to_model(final_message)

        else:  # A full error message or a non-streamed complete message
            final_message = ChatMessage(role="error" if is_error else "assistant", content=message_text,
                                        metadata={"timestamp": self._get_timestamp()})
            self.chat_display_area.add_message_to_model(final_message)

        if is_error:
            self.update_busy_state(False)  # Ensure input is re-enabled on error.


def set_input_focus(self) -> None:
    if self.chat_input_bar:
        self.chat_input_bar.set_focus()


def set_enabled(self, enabled: bool) -> None:
    if self.chat_input_bar:
        self.chat_input_bar.set_enabled(enabled)
    # self.chat_display_area.setEnabled(enabled) # Display area usually stays enabled.py