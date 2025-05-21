import logging
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt6.QtCore import pyqtSlot, Qt, pyqtSignal

from utils import constants
from core.orchestrator import AppOrchestrator
from core.project_manager import Project
from core.ai_comms_logger import AICommsLogger
from .components.chat_display_area import ChatDisplayArea
from .components.chat_input_bar import ChatInputBar
from core.models import ChatMessage
from core.message_enums import MessageLoadingState

logger = logging.getLogger(constants.APP_NAME)

class ChatPane(QWidget):
    send_message_to_chat_llm = pyqtSignal(list, str)
    user_typed_message_for_display = pyqtSignal(object)

    def __init__(self, orchestrator: AppOrchestrator, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.settings = orchestrator.get_settings()
        self.comms_logger = orchestrator.get_comms_logger()
        self.setObjectName("ChatPane")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.chat_display_area = None
        self.chat_input_bar = None

        self._current_project_id = None
        self._is_llm_busy = False

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
            if hasattr(self.chat_input_bar, 'sendMessageRequested') and isinstance(self.chat_input_bar.sendMessageRequested, pyqtSignal):
                self.chat_input_bar.sendMessageRequested.connect(self._handle_send_message_requested)

        if self.orchestrator and self.orchestrator.get_llm_manager():
            llm_manager = self.orchestrator.get_llm_manager()

    def async_initialize_chat_pane(self) -> None:
        logger.info("ChatPane asynchronous initialization...")
        if self.chat_input_bar:
            self.chat_input_bar.set_focus_to_input()
        self.update_busy_state(False)

    @pyqtSlot(str, list)
    def _handle_send_message_requested(self, text: str, image_data_list: List[Dict[str, Any]]) -> None:
        if not text.strip() and not image_data_list:
            logger.info("Empty message send request ignored.")
            return

        if self._is_llm_busy:
            logger.warning("Chat LLM is busy. Send request ignored.")
            return

        import uuid
        user_message_id = str(uuid.uuid4())

        user_chat_message = ChatMessage(
            role="user",
            content=text.strip(),
            image_data=image_data_list if image_data_list else None,
            metadata={"id": user_message_id, "timestamp": self._get_timestamp()}
        )

        if hasattr(self, 'user_typed_message_for_display') and isinstance(self.user_typed_message_for_display, pyqtSignal):
            self.user_typed_message_for_display.emit(user_chat_message)

        if self.chat_input_bar:
            self.chat_input_bar.clear_input()

        llm_request_id = str(uuid.uuid4())

        history_for_llm = []
        if self.orchestrator and self.orchestrator.get_project_manager() and self._current_project_id:
            project_manager = self.orchestrator.get_project_manager()
            raw_history = project_manager.get_chat_history(self._current_project_id)
            if raw_history:
                for msg_dict in raw_history:
                    try:
                        history_for_llm.append(ChatMessage.from_dict(msg_dict))
                    except AttributeError:
                        history_for_llm.append(ChatMessage(
                            role=msg_dict.get("role", "user"),
                            content=msg_dict.get("content", ""),
                            image_data=msg_dict.get("image_data"),
                            metadata=msg_dict.get("metadata"),
                            id=msg_dict.get("id"),
                            loading_state=msg_dict.get("loading_state")
                        ))
            history_for_llm.append(user_chat_message)
        else:
            history_for_llm.append(user_chat_message)

        if hasattr(self, 'send_message_to_chat_llm') and isinstance(self.send_message_to_chat_llm, pyqtSignal):
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

    @pyqtSlot(str)
    def load_chat_history(self, project_id: str) -> None:
        self._current_project_id = project_id
        logger.info(f"ChatPane: Loading history for project ID: {project_id}")
        if self.chat_display_area:
            history_to_load = []
            if self.orchestrator and self.orchestrator.get_project_manager():
                raw_history = self.orchestrator.get_project_manager().get_chat_history(project_id)
                if raw_history:
                    for msg_dict in raw_history:
                        try:
                            history_to_load.append(ChatMessage.from_dict(msg_dict))
                        except AttributeError:
                            history_to_load.append(ChatMessage(
                                role=msg_dict.get("role", "user"),
                                content=msg_dict.get("content", ""),
                                image_data=msg_dict.get("image_data"),
                                metadata=msg_dict.get("metadata")
                            ))

            self.chat_display_area.load_history_into_model(history_to_load)
        if self.chat_input_bar:
            self.chat_input_bar.set_focus_to_input()

    def clear_chat_display(self) -> None:
        if self.chat_display_area:
            self.chat_display_area.clear_model_display()

    @pyqtSlot(bool)
    def update_busy_state(self, is_busy: bool) -> None:
        self._is_llm_busy = is_busy
        if self.chat_input_bar:
            self.chat_input_bar.handle_busy_state(is_busy)
        logger.debug(f"ChatPane busy state updated: {is_busy}")

    @pyqtSlot(object)
    def add_user_message_to_display(self, message: ChatMessage) -> None:
        if self.chat_display_area:
            self.chat_display_area.add_message_to_model(message)

    @pyqtSlot(str, bool)
    def add_message_from_llm(self, message_text: str, is_error: bool) -> None:
        if not self.chat_display_area:
            logger.error("ChatDisplayArea not available to add LLM message.")
            return

        if self._is_llm_busy and not is_error:
            self.chat_display_area.append_stream_chunk_to_model(message_text)
        else:
            if self._is_llm_busy:
                self.chat_display_area.finalize_stream_in_model()

            if is_error:
                error_message_obj = ChatMessage(role="error", content=message_text,
                                                metadata={"timestamp": self._get_timestamp()})
                self.chat_display_area.add_message_to_model(error_message_obj)
            else:
                if message_text:
                    final_message = ChatMessage(role="assistant", content=message_text,
                                                metadata={"timestamp": self._get_timestamp()})
                    self.chat_display_area.add_message_to_model(final_message)

            self.update_busy_state(False)


    def set_input_focus(self) -> None:
        if self.chat_input_bar:
            self.chat_input_bar.set_focus_to_input()

    def set_enabled(self, enabled: bool) -> None:
        if self.chat_input_bar:
            self.chat_input_bar.set_enabled(enabled)