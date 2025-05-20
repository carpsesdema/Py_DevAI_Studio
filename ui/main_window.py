# PyDevAI_Studio/ui/main_window.py PART 1
import logging
import os
import asyncio
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QLabel, QSizePolicy, QMessageBox, QApplication, QMainWindow, QDialog,
    QFileDialog, QProgressDialog
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer, QSize, QEvent, QPoint
from PyQt6.QtGui import QIcon, QCloseEvent

from utils import constants
from core.app_settings import AppSettings
from core.ai_comms_logger import AICommsLogger
from core.orchestrator import AppOrchestrator
from core.code_generation_coordinator import CodeGenerationCoordinator
from services.code_processing_service import CodeProcessingService

try:
    from .left_panel import LeftControlPanel
except ImportError:
    LeftControlPanel = type("LeftControlPanel", (QWidget,), {})
try:
    from .chat_pane import ChatPane
except ImportError:
    ChatPane = type("ChatPane", (QWidget,), {})
try:
    from .code_editor_pane import CodeEditorPane
except ImportError:
    CodeEditorPane = type("CodeEditorPane", (QWidget,), {})
try:
    from .project_explorer_pane import ProjectExplorerPane
except ImportError:
    ProjectExplorerPane = type("ProjectExplorerPane", (QWidget,), {})
try:
    from .llm_log_terminal import LlmLogTerminal
except ImportError:
    LlmLogTerminal = type("LlmLogTerminal", (QWidget,), {})
try:
    from .dialogs.settings_dialog import SettingsDialog
except ImportError:
    SettingsDialog = type("SettingsDialog", (QDialog,), {})
try:
    from .dialogs.ai_comms_viewer_dialog import AICommsViewerDialog
except ImportError:
    AICommsViewerDialog = type("AICommsViewerDialog", (QDialog,), {})
try:
    from .dialogs.personality_dialog import PersonalityDialog
except ImportError:
    PersonalityDialog = type("PersonalityDialog", (QDialog,), {})
try:
    from .dialogs.rag_viewer_dialog import RAGViewerDialog
except ImportError:
    RAGViewerDialog = type("RAGViewerDialog", (QDialog,), {})
    logging.error("Failed to import RAGViewerDialog from ui.dialogs")
try:
    from .dialogs.project_management_dialog import ProjectManagementDialog # New
except ImportError:
    ProjectManagementDialog = type("ProjectManagementDialog", (QDialog,), {})
    logging.error("Failed to import ProjectManagementDialog from ui.dialogs")


logger = logging.getLogger(constants.APP_NAME)


class MainWindow(QMainWindow):
    def __init__(self, app_settings: AppSettings, comms_logger: AICommsLogger, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = app_settings
        self.comms_logger = comms_logger
        self.orchestrator: Optional[AppOrchestrator] = None

        self.left_panel: Optional[LeftControlPanel] = None
        self.project_explorer_pane: Optional[ProjectExplorerPane] = None
        self.chat_pane: Optional[ChatPane] = None
        self.code_editor_pane: Optional[CodeEditorPane] = None
        self.llm_log_terminal: Optional[LlmLogTerminal] = None
        self._ai_comms_viewer_dialog: Optional[AICommsViewerDialog] = None
        self._personality_dialog: Optional[PersonalityDialog] = None
        self._rag_viewer_dialog: Optional[RAGViewerDialog] = None
        self._project_management_dialog: Optional[ProjectManagementDialog] = None

        self.status_bar_label: Optional[QLabel] = None
        self._status_clear_timer: Optional[QTimer] = None

        self.code_processing_service: Optional[CodeProcessingService] = None
        self.code_generation_coordinator: Optional[CodeGenerationCoordinator] = None

        self._init_window_properties()
        self._init_ui_and_core_components()
        self._connect_signals()

        logger.info("MainWindow initialized.")

    def _init_window_properties(self) -> None:
        self.setWindowTitle(constants.APP_NAME)
        self.setObjectName("PyDevAIStudioMainWindow")
        geometry = self.settings.get("main_window_geometry")
        if geometry and isinstance(geometry, list) and len(geometry) == 4:
            self.setGeometry(geometry[0], geometry[1], geometry[2], geometry[3])
        else:
            self.setGeometry(100, 100, 1350, 850)

        state_hex = self.settings.get("main_window_state")
        if state_hex and isinstance(state_hex, str):
            try:
                self.restoreState(bytes.fromhex(state_hex))
            except Exception as e:
                logger.warning(f"Could not restore main window state: {e}")

    def _init_ui_and_core_components(self) -> None:
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QHBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.orchestrator = AppOrchestrator(app_settings=self.settings, comms_logger=self.comms_logger)
        if not self.orchestrator.get_llm_manager() or \
                not self.orchestrator.get_file_manager() or \
                not self.orchestrator.get_project_manager():
            QMessageBox.critical(self, "Init Error",
                                 "Core components (LLM, File, Project Manager) failed to initialize in Orchestrator.")
            QApplication.quit()
            return

        try:
            self.code_processing_service = CodeProcessingService()
        except Exception as e:
            logger.critical(f"Failed to initialize CodeProcessingService: {e}", exc_info=True)
            QMessageBox.critical(self, "Init Error", f"CodeProcessingService failed: {e}")
            QApplication.quit()
            return

        try:
            self.code_generation_coordinator = CodeGenerationCoordinator(
                llm_manager=self.orchestrator.get_llm_manager(),
                file_manager=self.orchestrator.get_file_manager(),
                settings=self.settings,
                code_processor=self.code_processing_service,
                project_manager=self.orchestrator.get_project_manager(),
                parent=self
            )
        except Exception as e:
            logger.critical(f"Failed to initialize CodeGenerationCoordinator: {e}", exc_info=True)
            QMessageBox.critical(self, "Init Error", f"CodeGenerationCoordinator failed: {e}")
            QApplication.quit()
            return

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setObjectName("MainWindowSplitter")
        main_splitter.setHandleWidth(2)

        self.left_panel = LeftControlPanel(orchestrator=self.orchestrator, settings=self.settings)
        self.project_explorer_pane = ProjectExplorerPane(orchestrator=self.orchestrator)

        left_section_splitter = QSplitter(Qt.Orientation.Vertical)
        left_section_splitter.addWidget(self.project_explorer_pane)
        left_section_splitter.addWidget(self.left_panel)
        left_section_splitter.setSizes([self.height() // 3, 2 * self.height() // 3])

        main_splitter.addWidget(left_section_splitter)

        right_main_panel = QWidget()
        right_main_layout = QVBoxLayout(right_main_panel)
        right_main_layout.setContentsMargins(0, 0, 0, 0);
        right_main_layout.setSpacing(0)

        top_right_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_right_splitter.setObjectName("TopRightSplitter")

        self.chat_pane = ChatPane(orchestrator=self.orchestrator)
        self.code_editor_pane = CodeEditorPane(orchestrator=self.orchestrator)

        top_right_splitter.addWidget(self.chat_pane)
        top_right_splitter.addWidget(self.code_editor_pane)
        top_right_splitter.setSizes([self.width() // 2, self.width() // 2])

        bottom_splitter = QSplitter(Qt.Orientation.Vertical)
        bottom_splitter.setObjectName("BottomSplitter")
        bottom_splitter.addWidget(top_right_splitter)
        self.llm_log_terminal = LlmLogTerminal()
        bottom_splitter.addWidget(self.llm_log_terminal)

        total_right_height = self.height() - (self.statusBar().height() if self.statusBar() else 20)
        log_terminal_height = self.settings.get("log_terminal_height", max(150, int(total_right_height * 0.25)))
        top_right_height = total_right_height - log_terminal_height
        bottom_splitter.setSizes([max(200, top_right_height), max(100, log_terminal_height)])

        right_main_layout.addWidget(bottom_splitter)
        main_splitter.addWidget(right_main_panel)

        main_splitter_sizes = self.settings.get("splitter_sizes_main", [max(280, int(self.width() * 0.22)),
                                                                        max(400, int(self.width() * 0.78))])
        main_splitter.setSizes(main_splitter_sizes)
        main_splitter.setStretchFactor(0, 0);
        main_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(main_splitter)
        self.central_widget.setLayout(main_layout)
        self._setup_status_bar()

    def _setup_status_bar(self) -> None:
        self.status_bar_label = QLabel("Initializing...")
        self.statusBar().addPermanentWidget(self.status_bar_label)
        self.statusBar().setStyleSheet("QStatusBar { border-top: 1px solid #454545; }")
        self.update_status("Ready.", "#98c379")

    async def async_initialize_components(self) -> None:
        logger.info("MainWindow starting asynchronous initialization of components...")
        if self.orchestrator:
            await self.orchestrator.initialize_async_services()

        if self.left_panel:
            self.left_panel.load_initial_settings()
            await self.left_panel.async_populate_llm_combos()

        if self.chat_pane and self.orchestrator.get_project_manager():
            self.chat_pane.async_initialize_chat_pane()
            active_project_id = self.orchestrator.get_project_manager().get_active_project_id()
            if active_project_id:
                self.chat_pane.load_chat_history(active_project_id)

        if self.project_explorer_pane and self.orchestrator.get_project_manager() and self.left_panel:
            active_project_id = self.orchestrator.get_project_manager().get_active_project_id()
            if active_project_id:
                self.project_explorer_pane.load_project_by_id(active_project_id)
            self.left_panel.update_project_list(self.orchestrator.get_project_manager().get_project_name_map())

        self.update_window_title()
        logger.info("MainWindow asynchronous initialization complete.")
        self.update_status("Application initialized successfully.", "#98c379", True, 3000)# PyDevAI_Studio/ui/main_window.py PART 2
    def _connect_signals(self) -> None:
        logger.info("MainWindow connecting signals...")
        if not self.orchestrator or not self.left_panel or not self.chat_pane or \
           not self.code_editor_pane or not self.project_explorer_pane or \
           not self.code_generation_coordinator:
            logger.critical("Cannot connect signals: One or more crucial UI/core components are None.")
            return

        project_manager = self.orchestrator.get_project_manager()
        if project_manager:
            project_manager.active_project_changed.connect(self._handle_active_project_changed_globally)
            project_manager.project_list_updated.connect(self.left_panel.update_project_list)
            self.left_panel.create_project_requested.connect(lambda: project_manager.show_project_management_dialog(self))
            self.left_panel.project_selected_from_ui.connect(project_manager.set_active_project_id)

        llm_manager = self.orchestrator.get_llm_manager()
        if llm_manager:
            self.left_panel.chat_llm_changed.connect(llm_manager.set_active_chat_llm)
            self.left_panel.coding_llm_changed.connect(llm_manager.set_active_coding_llm)
            self.left_panel.temperature_changed.connect(self._handle_temperature_change_from_ui)

        self.left_panel.open_file_requested.connect(self.code_editor_pane.display_single_file)
        self.left_panel.open_settings_requested.connect(self._show_settings_dialog)
        self.left_panel.view_llm_comms_requested.connect(self._show_ai_comms_viewer_dialog)
        self.left_panel.configure_persona_requested.connect(self._show_personality_dialog)
        self.left_panel.view_project_rag_requested.connect(self._show_rag_viewer_dialog)
        self.left_panel.manage_global_rag_requested.connect(self._show_rag_viewer_dialog)
        self.left_panel.upload_files_to_project_requested.connect(self._handle_upload_files_to_active_project_rag) # New
        self.left_panel.upload_folder_to_project_requested.connect(self._handle_upload_folder_to_active_project_rag) # New


        if llm_manager:
            self.chat_pane.send_message_to_chat_llm.connect(llm_manager.send_to_chat_llm)
            self.chat_pane.user_typed_message_for_display.connect(self._handle_user_message_to_chat_pane_model)

        if llm_manager:
            llm_manager.chat_llm_response_received.connect(self._handle_chat_llm_response)
            llm_manager.llm_error_occurred.connect(self._handle_llm_error)
            llm_manager.active_llms_changed.connect(self._handle_active_llms_changed_in_core)
            llm_manager.coding_instructions_generated.connect(self.code_generation_coordinator.start_generation_sequence)
            llm_manager.instruction_generation_failed.connect(self.code_generation_coordinator._handle_instruction_generation_failure)

        self.project_explorer_pane.file_selected_for_editing.connect(self.code_editor_pane.display_single_file)

        self.code_generation_coordinator.file_code_generated.connect(self.code_editor_pane.add_or_update_generated_file)
        self.code_generation_coordinator.generation_progress_updated.connect(
            lambda msg, cur, tot: self.update_status(msg, "#61afef")
        )
        self.code_generation_coordinator.generation_sequence_complete.connect(self._handle_generation_sequence_complete)
        self.code_generation_coordinator.generation_error_occurred.connect(
            lambda err_msg: self._handle_error("CodeGeneration", err_msg)
        )
        self.code_generation_coordinator.all_files_written_to_disk.connect(self._handle_all_files_written)
        self.code_generation_coordinator.file_write_error.connect(self._handle_file_write_error)

        self.code_editor_pane.files_approved_for_saving.connect(self.code_generation_coordinator.handle_files_approved_for_saving)

    @pyqtSlot()
    def _handle_create_project_dialog(self):
        project_manager = self.orchestrator.get_project_manager()
        if project_manager:
            project_manager.show_project_management_dialog(self)
        else:
            self.update_status("Project Manager not available.", "#e06c75", True, 3000)


    @pyqtSlot(object)
    def _handle_user_message_to_chat_pane_model(self, message: Any):
        if self.chat_pane:
            self.chat_pane.add_user_message_to_display(message)
            if self.orchestrator and self.orchestrator.get_project_manager():
                active_project_id = self.orchestrator.get_project_manager().get_active_project_id()
                if active_project_id:
                    self.orchestrator.get_project_manager().add_message_to_history(
                        project_id=active_project_id,
                        message_dict=message.to_dict()
                    )

    @pyqtSlot(str)
    def _handle_active_project_changed_globally(self, project_id: Optional[str]):
        logger.info(f"MainWindow: Global active project changed to: {project_id}")
        if self.left_panel:
            self.left_panel.update_active_project_selection(project_id)
        if self.project_explorer_pane:
            self.project_explorer_pane.load_project_by_id(project_id if project_id else None)


        if self.chat_pane:
            self.chat_pane.load_chat_history(project_id if project_id else "")

        if self.code_editor_pane:
            self.code_editor_pane.clear_all_files()

        self.update_window_title(project_id)
        active_project_name = "None"
        if self.orchestrator and self.orchestrator.get_project_manager() and project_id:
             project = self.orchestrator.get_project_manager().get_project_by_id(project_id)
             if project: active_project_name = project.name
        self.update_status(f"Active project: {active_project_name}", "#61afef")
        if self.orchestrator and self.orchestrator.get_rag_service(): # Re-initialize RAG for new active project
            asyncio.create_task(self.orchestrator.get_rag_service().initialize_rag_for_active_project())


    @pyqtSlot(float)
    def _handle_temperature_change_from_ui(self, temperature: float):
        if self.orchestrator and self.orchestrator.get_llm_manager():
            self.orchestrator.get_llm_manager().set_chat_llm_temperature(temperature)
            self.update_status(f"Chat LLM temperature set to {temperature:.2f}", "#61afef", True, 2000)

    @pyqtSlot(str, str, bool)
    def _handle_active_llms_changed_in_core(self, provider_name: str, model_id: str, is_chat_llm: bool):
        logger.info(f"MainWindow: Core LLM change. Provider: {provider_name}, Model: {model_id}, IsChat: {is_chat_llm}")
        if self.left_panel:
            self.left_panel.update_llm_selection_from_core(provider_name, model_id, is_chat_llm)
        self.update_window_title()
        llm_type_str = "Chat LLM" if is_chat_llm else "Coding LLM"
        self.update_status(f"{llm_type_str} set to: {model_id.split('/')[-1]} ({provider_name})", "#98c379", True, 3000)

    @pyqtSlot(str, bool)
    def _handle_chat_llm_response(self, message_text_chunk: str, is_final_or_error: bool):
        if self.chat_pane:
            if is_final_or_error:
                if "Error:" in message_text_chunk:
                    self.chat_pane.add_message_from_llm(message_text_chunk, True)
                    self.chat_pane.update_busy_state(False)
                else:
                    self.chat_pane.add_message_from_llm(message_text_chunk, False) # Final chunk
                    self.chat_pane.update_busy_state(False)
            else: # Streaming chunk
                self.chat_pane.update_busy_state(True)
                self.chat_pane.add_message_from_llm(message_text_chunk, False)


    @pyqtSlot(str, str)
    def _handle_llm_error(self, llm_type: str, error_message: str):
        logger.error(f"MainWindow: LLM Error from {llm_type} LLM: {error_message}")
        self.update_status(f"Error from {llm_type} LLM: {error_message[:100]}...", "#e06c75", True, 5000)
        if self.chat_pane and llm_type.lower() == "chat":
            self.chat_pane.add_message_from_llm(f"LLM Error: {error_message}", True)
            self.chat_pane.update_busy_state(False)

    @pyqtSlot(str, bool)
    def _handle_generation_sequence_complete(self, final_message: str, was_successful: bool):
        self.update_status(final_message, "#98c379" if was_successful else "#e5c07b", True, 5000)
        if was_successful and "written" in final_message.lower():
            if self.project_explorer_pane:
                self.project_explorer_pane._refresh_view()

    @pyqtSlot(list)
    def _handle_all_files_written(self, written_file_paths: List[str]):
        self.update_status(f"Successfully wrote {len(written_file_paths)} files to disk.", "#98c379", True, 4000)
        if self.project_explorer_pane:
            self.project_explorer_pane._refresh_view()

    @pyqtSlot(str, str)
    def _handle_file_write_error(self, file_path: str, error_msg: str):
        self.update_status(f"Error writing file '{file_path}': {error_msg}", "#e06c75", True, 6000)
        QMessageBox.critical(self, "File Write Error", f"Failed to write file:\n{file_path}\n\nError: {error_msg}")

    def update_status(self, message: str, color: str = "#abb2bf", is_temporary: bool = False, duration_ms: int = 3000) -> None:
        if self.status_bar_label:
            self.status_bar_label.setText(message)
            self.status_bar_label.setStyleSheet(f"QLabel {{ color: {color}; padding-left: 5px; }}")
            if self._status_clear_timer: self._status_clear_timer.stop()
            if is_temporary:
                if not self._status_clear_timer:
                    self._status_clear_timer = QTimer(self)
                    self._status_clear_timer.setSingleShot(True)
                    self._status_clear_timer.timeout.connect(lambda: self.update_status(f"Ready. Active Project: {self.orchestrator.get_project_manager().get_active_project().name if self.orchestrator and self.orchestrator.get_project_manager() and self.orchestrator.get_project_manager().get_active_project() else 'None'}", "#98c379"))
                self._status_clear_timer.start(duration_ms)

    def update_window_title(self, project_id: Optional[str] = None) -> None:
        title_parts = [constants.APP_NAME]
        current_project_id = project_id
        if not current_project_id and self.orchestrator and self.orchestrator.get_project_manager():
            active_proj = self.orchestrator.get_project_manager().get_active_project()
            if active_proj: current_project_id = active_proj.id

        if current_project_id and self.orchestrator and self.orchestrator.get_project_manager():
            proj = self.orchestrator.get_project_manager().get_project_by_id(current_project_id)
            if proj and proj.name: title_parts.append(proj.name)

        if self.orchestrator and self.orchestrator.get_llm_manager():
            chat_llm_info = self.orchestrator.get_llm_manager().get_active_chat_llm_info()
            if chat_llm_info and chat_llm_info.get("model_id_short"):
                title_parts.append(f"Chat: {chat_llm_info['model_id_short']}")
        self.setWindowTitle(" - ".join(title_parts))

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("MainWindow closeEvent triggered.")
        self.settings.set("main_window_geometry", [self.x(), self.y(), self.width(), self.height()])
        self.settings.set("main_window_state", self.saveState().toHex().data().decode())

        main_splitter = self.findChild(QSplitter, "MainWindowSplitter")
        if main_splitter: self.settings.set("splitter_sizes_main", main_splitter.sizes())

        log_terminal = self.findChild(LlmLogTerminal)
        if log_terminal and isinstance(log_terminal, LlmLogTerminal):
            self.settings.set("log_terminal_height", log_terminal.height())

        self.settings.save()
        self.cleanup_before_exit()
        super().closeEvent(event)
        instance = QApplication.instance()
        if instance:
            instance.quit()


    def cleanup_before_exit(self) -> None:
        logger.info("MainWindow performing cleanup before exit...")
        if self._ai_comms_viewer_dialog and self._ai_comms_viewer_dialog.isVisible():
            self._ai_comms_viewer_dialog.done(0)
        if self._personality_dialog and self._personality_dialog.isVisible():
            self._personality_dialog.done(0)
        if self._rag_viewer_dialog and self._rag_viewer_dialog.isVisible():
            self._rag_viewer_dialog.done(0)
        if self._project_management_dialog and self._project_management_dialog.isVisible():
            self._project_management_dialog.done(0)
        if self.llm_log_terminal and hasattr(self.llm_log_terminal, 'cleanup'):
            self.llm_log_terminal.cleanup()
        if self.orchestrator:
            self.orchestrator.shutdown_services()
        logger.info("MainWindow cleanup finished.")

    @pyqtSlot(str, str, Optional[str])
    def _handle_chat_llm_changed_from_ui(self, provider_name: str, model_id: str, api_key: Optional[str]):
        if self.orchestrator and self.orchestrator.get_llm_manager():
            asyncio.create_task(
                self.orchestrator.get_llm_manager().set_active_chat_llm(provider_name, model_id, api_key)
            )

    @pyqtSlot(str, str, Optional[str])
    def _handle_coding_llm_changed_from_ui(self, provider_name: str, model_id: str, api_key: Optional[str]):
        if self.orchestrator and self.orchestrator.get_llm_manager():
            asyncio.create_task(
                self.orchestrator.get_llm_manager().set_active_coding_llm(provider_name, model_id, api_key)
            )

    def _handle_error(self, source: str, message: str) -> None:
        logger.error(f"Error from {source}: {message}")
        QMessageBox.warning(self, f"{source} Error", message)
        self.update_status(f"{source} Error: {message[:100]}...", "#e06c75", True, 5000)

    @pyqtSlot()
    def _show_settings_dialog(self):
        if not self.orchestrator or not self.settings:
            logger.error("Cannot show settings: Orchestrator or AppSettings not available.")
            QMessageBox.critical(self, "Error", "Cannot open settings dialog: Core components missing.")
            return

        dialog = SettingsDialog(settings=self.settings, orchestrator=self.orchestrator, parent=self)
        dialog.settings_applied.connect(self._handle_settings_applied)

        llm_manager = self.orchestrator.get_llm_manager()
        prev_chat_config = None
        prev_coding_config = None
        if llm_manager:
            prev_chat_info = llm_manager.get_active_chat_llm_info()
            if prev_chat_info["provider_name"] and prev_chat_info["model_id"]:
                 prev_chat_settings = self.settings.get_llm_provider_settings(prev_chat_info["provider_name"])
                 prev_chat_config = (prev_chat_info["provider_name"], prev_chat_info["model_id"],
                                     prev_chat_settings.get("api_key") if prev_chat_settings else None)

            prev_coding_info = llm_manager.get_active_coding_llm_info()
            if prev_coding_info["provider_name"] and prev_coding_info["model_id"]:
                prev_coding_settings = self.settings.get_llm_provider_settings(prev_coding_info["provider_name"])
                prev_coding_config = (prev_coding_info["provider_name"], prev_coding_info["model_id"],
                                      prev_coding_settings.get("api_key") if prev_coding_settings else None)

        if dialog.exec():
            logger.info("Settings dialog accepted.")
            if llm_manager and (prev_chat_config or prev_coding_config) :
                self._check_and_reconfigure_active_llms(llm_manager, prev_chat_config, prev_coding_config)
        else:
            logger.info("Settings dialog cancelled.")

    def _check_and_reconfigure_active_llms(self, llm_manager, prev_chat_config, prev_coding_config):
        current_chat_info = llm_manager.get_active_chat_llm_info()
        current_chat_provider_settings = self.settings.get_llm_provider_settings(current_chat_info["provider_name"]) if current_chat_info["provider_name"] else None
        current_chat_api_key = current_chat_provider_settings.get("api_key") if current_chat_provider_settings else None

        if prev_chat_config and current_chat_info["provider_name"] and current_chat_info["model_id"]:
            prev_provider, prev_model, prev_key = prev_chat_config
            if prev_provider != current_chat_info["provider_name"] or \
               prev_model != current_chat_info["model_id"] or \
               (prev_key != current_chat_api_key and prev_provider != constants.LLMProvider.OLLAMA.value):
                logger.info(f"Chat LLM configuration changed. Reconfiguring: {current_chat_info['provider_name']} - {current_chat_info['model_id']}")
                asyncio.create_task(llm_manager.set_active_chat_llm(current_chat_info["provider_name"], current_chat_info["model_id"], current_chat_api_key))

        current_coding_info = llm_manager.get_active_coding_llm_info()
        current_coding_provider_settings = self.settings.get_llm_provider_settings(current_coding_info["provider_name"]) if current_coding_info["provider_name"] else None
        current_coding_api_key = current_coding_provider_settings.get("api_key") if current_coding_provider_settings else None

        if prev_coding_config and current_coding_info["provider_name"] and current_coding_info["model_id"]:
            prev_provider_code, prev_model_code, prev_key_code = prev_coding_config
            if prev_provider_code != current_coding_info["provider_name"] or \
               prev_model_code != current_coding_info["model_id"] or \
               (prev_key_code != current_coding_api_key and prev_provider_code != constants.LLMProvider.OLLAMA.value):
                logger.info(f"Coding LLM configuration changed. Reconfiguring: {current_coding_info['provider_name']} - {current_coding_info['model_id']}")
                asyncio.create_task(llm_manager.set_active_coding_llm(current_coding_info["provider_name"], current_coding_info["model_id"], current_coding_api_key))

    @pyqtSlot()
    def _handle_settings_applied(self):
        logger.info("SettingsDialog reported settings have been applied.")
        self.update_status("Settings updated.", "#98c379", True, 3000)
        if self.left_panel:
            self.left_panel.load_initial_settings()
            asyncio.create_task(self.left_panel.async_populate_llm_combos())

        if self.orchestrator and self.orchestrator.get_llm_manager():
            llm_manager = self.orchestrator.get_llm_manager()
            chat_info = llm_manager.get_active_chat_llm_info()
            if chat_info["provider_name"] and chat_info["model_id"]:
                provider_settings = self.settings.get_llm_provider_settings(chat_info["provider_name"])
                api_key = provider_settings.get("api_key") if provider_settings else None
                asyncio.create_task(llm_manager.set_active_chat_llm(chat_info["provider_name"], chat_info["model_id"], api_key))

            coding_info = llm_manager.get_active_coding_llm_info()
            if coding_info["provider_name"] and coding_info["model_id"]:
                provider_settings = self.settings.get_llm_provider_settings(coding_info["provider_name"])
                api_key = provider_settings.get("api_key") if provider_settings else None
                asyncio.create_task(llm_manager.set_active_coding_llm(coding_info["provider_name"], coding_info["model_id"], api_key))

        if self.orchestrator and self.orchestrator.get_rag_service():
             logger.info("RAG settings changed. RAGService may need re-initialization for some changes to take full effect (e.g., chunk size for new documents).")

    @pyqtSlot()
    def _show_ai_comms_viewer_dialog(self):
        if self._ai_comms_viewer_dialog is None:
            self._ai_comms_viewer_dialog = AICommsViewerDialog(self)
            self._ai_comms_viewer_dialog.finished.connect(self._on_ai_comms_viewer_closed)

        if not self._ai_comms_viewer_dialog.isVisible():
            self._ai_comms_viewer_dialog.show()
            self._ai_comms_viewer_dialog.activateWindow()
            self._ai_comms_viewer_dialog.raise_()
        else:
            self._ai_comms_viewer_dialog.activateWindow()
            self._ai_comms_viewer_dialog.raise_()

    @pyqtSlot(int)
    def _on_ai_comms_viewer_closed(self, result: int):
        logger.debug(f"AICommsViewerDialog closed with result: {result}")

    @pyqtSlot()
    def _show_personality_dialog(self):
        if not self.settings:
            logger.error("Cannot show Personality Dialog: AppSettings not available.")
            return

        if self._personality_dialog is None:
            self._personality_dialog = PersonalityDialog(settings=self.settings, parent=self)
            self._personality_dialog.prompts_updated.connect(self._handle_prompts_updated)
            self._personality_dialog.finished.connect(self._on_personality_dialog_closed)

        if not self._personality_dialog.isVisible():
            self._personality_dialog.show()
            self._personality_dialog.activateWindow()
            self._personality_dialog.raise_()
        else:
            self._personality_dialog.activateWindow()
            self._personality_dialog.raise_()

    @pyqtSlot()
    def _handle_prompts_updated(self):
        logger.info("PersonalityDialog reported prompts have been updated in settings.")
        self.update_status("AI persona prompts updated.", "#98c379", True, 3000)

        if self.orchestrator and self.orchestrator.get_llm_manager():
            llm_manager = self.orchestrator.get_llm_manager()
            chat_info = llm_manager.get_active_chat_llm_info()
            if chat_info["provider_name"] and chat_info["model_id"]:
                provider_settings = self.settings.get_llm_provider_settings(chat_info["provider_name"])
                api_key = provider_settings.get("api_key") if provider_settings else None
                asyncio.create_task(llm_manager.set_active_chat_llm(chat_info["provider_name"], chat_info["model_id"], api_key))

            coding_info = llm_manager.get_active_coding_llm_info()
            if coding_info["provider_name"] and coding_info["model_id"]:
                provider_settings = self.settings.get_llm_provider_settings(coding_info["provider_name"])
                api_key = provider_settings.get("api_key") if provider_settings else None
                asyncio.create_task(llm_manager.set_active_coding_llm(coding_info["provider_name"], coding_info["model_id"], api_key))

    @pyqtSlot(int)
    def _on_personality_dialog_closed(self, result: int):
        logger.debug(f"PersonalityDialog closed with result: {result}")

    @pyqtSlot()
    def _show_rag_viewer_dialog(self):
        if not self.orchestrator:
            logger.error("Cannot show RAG Viewer: Orchestrator not available.")
            QMessageBox.critical(self, "Error", "Cannot open RAG Viewer: Orchestrator missing.")
            return

        sender_button = self.sender()
        target_collection_id: Optional[str] = None

        if self.left_panel:
            if sender_button == self.left_panel.view_project_rag_button:
                if self.orchestrator.get_project_manager():
                    active_project = self.orchestrator.get_project_manager().get_active_project()
                    if active_project and self.orchestrator.get_rag_service():
                        target_collection_id = self.orchestrator.get_rag_service()._get_project_rag_collection_id(active_project.id)
                        logger.info(f"RAG Viewer requested for Project: {active_project.name} (Coll ID: {target_collection_id})")
                    elif active_project:
                         logger.warning(f"RAG Viewer requested for Project {active_project.name}, but RAG service missing.")
                    else:
                        logger.info("RAG Viewer (Project) requested, but no active project. Will show global if available.")
                        target_collection_id = constants.GLOBAL_RAG_COLLECTION_ID # Default to global
            elif sender_button == self.left_panel.manage_global_rag_button:
                target_collection_id = constants.GLOBAL_RAG_COLLECTION_ID
                logger.info(f"RAG Viewer requested for Global Collection (Coll ID: {target_collection_id})")

        if self._rag_viewer_dialog is None:
            self._rag_viewer_dialog = RAGViewerDialog(orchestrator=self.orchestrator, parent=self)
            self._rag_viewer_dialog.finished.connect(self._on_rag_viewer_dialog_closed)

        if not self._rag_viewer_dialog.isVisible():
            self._rag_viewer_dialog.show()
            if self._rag_viewer_dialog._collections_combo:
                if target_collection_id:
                    combo = self._rag_viewer_dialog._collections_combo
                    for i in range(combo.count()):
                        if combo.itemData(i) == target_collection_id:
                            combo.setCurrentIndex(i)
                            self._rag_viewer_dialog._update_ui_for_selected_collection()
                            break
                elif self._rag_viewer_dialog._collections_combo.count() > 0:
                    self._rag_viewer_dialog._on_collection_selected(0)


            self._rag_viewer_dialog.activateWindow()
            self._rag_viewer_dialog.raise_()
        else:
            if target_collection_id and self._rag_viewer_dialog._collections_combo:
                combo = self._rag_viewer_dialog._collections_combo
                current_selected_id = combo.itemData(combo.currentIndex()) if combo.currentIndex() >=0 else None
                if current_selected_id != target_collection_id:
                    for i in range(combo.count()):
                        if combo.itemData(i) == target_collection_id:
                            combo.setCurrentIndex(i)
                            break
            self._rag_viewer_dialog.activateWindow()
            self._rag_viewer_dialog.raise_()

    @pyqtSlot(int)
    def _on_rag_viewer_dialog_closed(self, result: int):
        logger.debug(f"RAGViewerDialog closed with result: {result}")
        if self.left_panel:
            self.left_panel.update_rag_button_state()

    @pyqtSlot()
    async def _handle_upload_files_to_active_project_rag(self):
        if not self.orchestrator or not self.orchestrator.get_project_manager() or not self.orchestrator.get_rag_service():
            QMessageBox.warning(self, "Error", "Core services not available for RAG operation.")
            return

        active_project = self.orchestrator.get_project_manager().get_active_project()
        if not active_project:
            QMessageBox.information(self, "No Active Project", "Please select or create a project to add files to its RAG.")
            return

        active_project_id = active_project.id # This is the semantic project ID

        file_dialog = QFileDialog(self, f"Select Files to Add to RAG for Project: {active_project.name}")
        allowed_ext_str = " ".join(f"*{ext}" for ext in constants.ALLOWED_TEXT_EXTENSIONS if ext not in ['.pdf', '.docx'])
        pdf_ext_str = "*.pdf"; docx_ext_str = "*.docx"
        filter_str = f"Supported Text Files ({allowed_ext_str});;PDF Documents ({pdf_ext_str});;Word Documents ({docx_ext_str});;All Files (*)"
        file_dialog.setNameFilter(filter_str)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)

        if file_dialog.exec():
            file_paths = file_dialog.selectedFiles()
            if file_paths:
                rag_service = self.orchestrator.get_rag_service()
                progress_dialog = QProgressDialog(f"Adding files to '{active_project.name}' RAG...", "Cancel", 0, len(file_paths), self)
                progress_dialog.setWindowModality(Qt.WindowModality.WindowModal); progress_dialog.setMinimumDuration(500)
                progress_dialog.setValue(0); QApplication.processEvents()

                success_count, failure_count, error_msgs = 0,0,[]
                for i, file_path in enumerate(file_paths):
                    if progress_dialog.wasCanceled(): break
                    progress_dialog.setLabelText(f"Processing: {os.path.basename(file_path)} ({i+1}/{len(file_paths)})")
                    added, msg = await rag_service.add_file_to_rag(file_path, project_id=active_project_id)
                    if added: success_count += 1
                    else: failure_count += 1; error_msgs.append(f"{os.path.basename(file_path)}: {msg}")
                    progress_dialog.setValue(i + 1); QApplication.processEvents()
                progress_dialog.close()

                summary = f"Project RAG Update: {success_count} added, {failure_count} failed."
                self.update_status(summary, "#98c379" if failure_count == 0 else "#e5c07b", True, 4000)
                if failure_count > 0:
                    QMessageBox.warning(self, "RAG File Add Issues", f"{summary}\nErrors:\n" + "\n".join(error_msgs[:5]))
                if self.left_panel: self.left_panel.update_rag_button_state()


    @pyqtSlot()
    async def _handle_upload_folder_to_active_project_rag(self):
        if not self.orchestrator or not self.orchestrator.get_project_manager() or not self.orchestrator.get_rag_service():
            QMessageBox.warning(self, "Error", "Core services not available for RAG operation.")
            return

        active_project = self.orchestrator.get_project_manager().get_active_project()
        if not active_project:
            QMessageBox.information(self, "No Active Project", "Please select or create a project to add a folder to its RAG.")
            return

        active_project_id = active_project.id # Semantic project ID

        folder_path = QFileDialog.getExistingDirectory(self, f"Select Folder to Add to RAG for Project: {active_project.name}")
        if folder_path:
            rag_service = self.orchestrator.get_rag_service()

            self.setEnabled(False); QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            prog_msg = QMessageBox(QMessageBox.Icon.Information, "Processing Folder", f"Processing folder for '{active_project.name}' RAG. This may take some time...", QMessageBox.StandardButton.NoButton, self)
            prog_msg.setWindowModality(Qt.WindowModality.ApplicationModal); prog_msg.show(); QApplication.processEvents()

            try:
                success_count, failure_count, error_msgs = await rag_service.add_folder_to_rag(folder_path, project_id=active_project_id)
            finally:
                prog_msg.close(); QApplication.restoreOverrideCursor(); self.setEnabled(True)

            summary = f"Project RAG Folder Update: {success_count} files added, {failure_count} failed/skipped."
            self.update_status(summary, "#98c379" if failure_count == 0 else "#e5c07b", True, 4000)
            if failure_count > 0:
                QMessageBox.warning(self, "RAG Folder Add Issues", f"{summary}\nErrors/Skipped:\n" + "\n".join(error_msgs[:5]))
            if self.left_panel: self.left_panel.update_rag_button_state()