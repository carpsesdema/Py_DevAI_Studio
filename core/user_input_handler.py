# core/user_input_handler.py
import logging
import uuid  # Make sure uuid is imported
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import ChatMessage, USER_ROLE
from core.modification_coordinator import ModificationCoordinator
# --- END CORRECTED IMPORT ---
from core.project_context_manager import ProjectContextManager
# --- CORRECTED IMPORT ---
from core.user_input_processor import UserInputProcessor, ProcessResult  # Import ProcessResult

# Conditional import for ProjectSummaryCoordinator
if TYPE_CHECKING:
    from core.project_summary_coordinator import ProjectSummaryCoordinator

logger = logging.getLogger(__name__)


class UserInputHandler(QObject):
    # Existing signals
    normal_chat_request_ready = pyqtSignal(list)  # List[ChatMessage]
    # --- MODIFIED: Renamed for clarity, this is for BOOTSTRAP ---
    bootstrap_sequence_start_requested = pyqtSignal(str, list, str, str)  # query, image_data, context_rag, focus_prefix
    # --- END MODIFIED ---

    # --- NEW SIGNAL for MODIFY EXISTING ---
    modification_existing_sequence_start_requested = pyqtSignal(str, list, list, str,
                                                                str)  # query, image_data, target_files, context_rag, focus_prefix
    # --- END NEW SIGNAL ---

    modification_user_input_received = pyqtSignal(str, str)  # user_command, action_type
    processing_error_occurred = pyqtSignal(str)
    user_command_for_display_only = pyqtSignal(ChatMessage)

    def __init__(self,
                 user_input_processor: UserInputProcessor,
                 project_context_manager: ProjectContextManager,
                 modification_coordinator: Optional[ModificationCoordinator],
                 project_summary_coordinator: Optional['ProjectSummaryCoordinator'],
                 parent: Optional[QObject] = None):
        super().__init__(parent)

        if not all([user_input_processor, project_context_manager]):
            err_msg = "UserInputHandler requires UserInputProcessor and ProjectContextManager."
            logger.critical(err_msg)
            raise ValueError(err_msg)

        self._uip = user_input_processor
        self._pcm = project_context_manager
        self._mc = modification_coordinator
        self._psc = project_summary_coordinator

        if self._psc:
            logger.info("UserInputHandler initialized with ProjectSummaryCoordinator.")
        else:
            logger.warning(
                "UserInputHandler initialized WITHOUT ProjectSummaryCoordinator. Manual summary command disabled.")
        logger.info("UserInputHandler initialized.")

    def handle_user_message(self,
                            text: str,
                            image_data: List[Dict[str, Any]],
                            focus_paths: Optional[List[str]],
                            rag_available: bool,
                            rag_initialized_for_project: bool):
        user_query_text_raw = text.strip()
        is_mod_active = self._mc and self._mc.is_active() if self._mc else False
        current_pid = self._pcm.get_active_project_id() if self._pcm else None
        if not current_pid:
            logger.error("UserInputHandler: Could not determine current_project_id from ProjectContextManager.")
            self.processing_error_occurred.emit("Internal error: Active project context not found.")
            return

        try:
            proc_result: ProcessResult = self._uip.process(  # Add type hint for proc_result
                user_query_text=user_query_text_raw,
                image_data=image_data or [],
                is_modification_active=is_mod_active,
                current_project_id=current_pid,
                focus_paths=focus_paths,
                rag_available=rag_available,
                rag_initialized=rag_initialized_for_project
            )
        except Exception as e_uip:
            logger.exception(f"UserInputHandler: UserInputProcessor encountered an error: {e_uip}")
            self.processing_error_occurred.emit(f"Error processing your input: {e_uip}")
            return

        action = proc_result.action_type
        payload = proc_result.prompt_or_history  # This name might be confusing now, it's generic payload

        logger.info(f"UserInputHandler: UIP returned action '{action}'.")

        if action == "NORMAL_CHAT":
            if isinstance(proc_result.prompt_or_history, list) and proc_result.prompt_or_history and isinstance(
                    proc_result.prompt_or_history[0], ChatMessage):
                logger.debug(
                    f"UserInputHandler: NORMAL_CHAT. Emitting clean UI message from raw text: '{user_query_text_raw[:100]}...'")
                ui_message_parts = [user_query_text_raw] + (image_data or [])
                ui_chat_message_for_display = ChatMessage(role=USER_ROLE, parts=ui_message_parts)
                self.normal_chat_request_ready.emit([ui_chat_message_for_display])
            else:
                logger.error(
                    f"UserInputHandler: NORMAL_CHAT action received invalid payload: {proc_result.prompt_or_history}")
                self.processing_error_occurred.emit("Internal error preparing chat message.")

        elif action == "START_MODIFICATION":  # This is now for BOOTSTRAP
            logger.info("UserInputHandler: Handling START_MODIFICATION (Bootstrap).")
            original_query = proc_result.original_query or ""
            context_for_mc = proc_result.original_context or ""
            focus_prefix_for_mc = proc_result.original_focus_prefix or ""
            self.bootstrap_sequence_start_requested.emit(  # Emit renamed signal
                original_query, image_data or [], context_for_mc, focus_prefix_for_mc
            )

        # --- NEW: Handle START_MODIFICATION_EXISTING ---
        elif action == "START_MODIFICATION_EXISTING":
            logger.info("UserInputHandler: Handling START_MODIFICATION_EXISTING.")
            original_query = proc_result.original_query or ""
            identified_files = proc_result.identified_target_files or []
            context_for_mc = proc_result.original_context or ""
            focus_prefix_for_mc = proc_result.original_focus_prefix or ""

            self.modification_existing_sequence_start_requested.emit(
                original_query,
                image_data or [],
                identified_files,
                context_for_mc,
                focus_prefix_for_mc
            )
        # --- END NEW ---

        elif action in ["NEXT_MODIFICATION", "REFINE_MODIFICATION", "COMPLETE_MODIFICATION"]:
            user_command_for_mc = payload  # Here, payload is indeed the user_command string
            if isinstance(user_command_for_mc, str):
                self.modification_user_input_received.emit(user_command_for_mc, action)
            else:
                logger.error(
                    f"UserInputHandler: Modification action '{action}' received non-string payload: {user_command_for_mc}")
                self.processing_error_occurred.emit(f"Internal error processing modification command for '{action}'.")

        elif action == "REQUEST_PROJECT_SUMMARY":
            project_id_for_summary = str(payload) if payload else None  # Payload is project_id here
            original_query_for_ui = proc_result.original_query

            if not project_id_for_summary:
                logger.error("UserInputHandler: REQUEST_PROJECT_SUMMARY action received invalid project_id in payload.")
                self.processing_error_occurred.emit("Internal error: Could not determine project for summary.")
                return

            if original_query_for_ui:
                ui_message_parts = [original_query_for_ui]
                ui_chat_message = ChatMessage(role=USER_ROLE, parts=ui_message_parts, id=str(uuid.uuid4()))
                self.user_command_for_display_only.emit(ui_chat_message)
                logger.debug(
                    f"Emitted user's summary command (ID: {ui_chat_message.id}, Text: '{original_query_for_ui[:50]}...') for UI display ONLY.")

            if self._psc:
                logger.info(
                    f"UserInputHandler: Calling ProjectSummaryCoordinator to generate summary for project '{project_id_for_summary}'.")
                self._psc.generate_project_summary(project_id_for_summary)
            else:
                logger.error("ProjectSummaryCoordinator not available. Cannot process summary request.")
                self.processing_error_occurred.emit("Project summary feature is currently unavailable.")

        elif action == "NO_ACTION":
            logger.info("UserInputHandler: UserInputProcessor determined no action required.")
            # Optionally, display the user's message if it wasn't a command that got consumed
            if user_query_text_raw:  # If there was actual text input
                ui_message_parts = [user_query_text_raw] + (image_data or [])
                ui_chat_message_for_display = ChatMessage(role=USER_ROLE, parts=ui_message_parts)
                self.normal_chat_request_ready.emit([ui_chat_message_for_display])

        else:
            logger.error(f"UserInputHandler: Unknown action type from UserInputProcessor: {action}")
            self.processing_error_occurred.emit(f"Unknown internal action: {action}")