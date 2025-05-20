# PyDevAI_Studio/ui/left_panel.py PART 1
import logging
import os
import asyncio
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QSizePolicy,
    QTreeView, QComboBox, QGroupBox, QHBoxLayout, QSlider, QDoubleSpinBox,
    QStyle, QFrame
)
from PyQt6.QtGui import QFont, QIcon, QStandardItemModel, QStandardItem
from PyQt6.QtCore import pyqtSignal, Qt, QSize, pyqtSlot, QModelIndex

try:
    import qtawesome as qta

    QTAWESOME_AVAILABLE = True
except ImportError:
    qta = None
    QTAWESOME_AVAILABLE = False

from utils import constants
from core.orchestrator import AppOrchestrator
from core.app_settings import AppSettings

logger = logging.getLogger(constants.APP_NAME)


class LeftControlPanel(QWidget):
    create_project_requested = pyqtSignal()
    project_selected_from_ui = pyqtSignal(str)

    new_chat_session_requested = pyqtSignal()
    manage_chat_sessions_requested = pyqtSignal() # Placeholder for now

    upload_files_to_project_requested = pyqtSignal() # Placeholder for now
    upload_folder_to_project_requested = pyqtSignal() # Placeholder for now
    view_project_rag_requested = pyqtSignal()
    manage_global_rag_requested = pyqtSignal()


    view_generated_code_requested = pyqtSignal()
    view_llm_comms_requested = pyqtSignal()
    configure_persona_requested = pyqtSignal()
    open_settings_requested = pyqtSignal()
    open_file_requested = pyqtSignal(str)

    chat_llm_changed = pyqtSignal(str, str, object) # MODIFIED: Optional[str] -> object
    coding_llm_changed = pyqtSignal(str, str, object) # MODIFIED: Optional[str] -> object
    temperature_changed = pyqtSignal(float)

    _PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole + 1
    _TEMP_SLIDER_MIN = 0
    _TEMP_SLIDER_MAX = 200
    _TEMP_PRECISION_FACTOR = 100.0

    def __init__(self, orchestrator: AppOrchestrator, settings: AppSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.settings = settings
        self.setObjectName("LeftControlPanel")
        self.setMinimumWidth(280)
        self.setMaximumWidth(450)

        self._is_programmatic_selection_change: bool = False
        self._is_programmatic_llm_change: bool = False
        self._is_programmatic_temp_change: bool = False

        self._init_widgets()
        self._init_layout()
        self._connect_signals()

        logger.info("LeftControlPanel initialized.")

    def _load_qta_icon(self, icon_name: str, color: str = "#D0D0D0") -> QIcon:
        if qta:
            try:
                return qta.icon(icon_name, color=color)
            except Exception as e:
                logger.warning(f"Failed to load qta icon '{icon_name}': {e}")
        return QIcon()

    def _load_asset_icon(self, filename: str) -> QIcon:
        path = os.path.join(constants.ASSETS_DIR, filename)
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
            logger.warning(f"Asset icon loaded but is null: {path}")
        else:
            logger.warning(f"Asset icon not found: {path}")
        return QIcon()

    def _init_widgets(self) -> None:
        self.button_font = QFont(self.settings.get("ui_font_family", constants.DEFAULT_FONT_FAMILY),
                                 self.settings.get("ui_font_size", constants.DEFAULT_FONT_SIZE) - 1)
        button_style = "QPushButton { text-align: left; padding: 7px 10px; border: 1px solid #404040; background-color: #383838; } QPushButton:hover { background-color: #454545; } QPushButton:pressed { background-color: #303030; }"
        group_font = QFont(self.settings.get("ui_font_family", constants.DEFAULT_FONT_FAMILY),
                           self.settings.get("ui_font_size", constants.DEFAULT_FONT_SIZE), QFont.Weight.Bold)
        group_style = "QGroupBox { margin-top: 6px; border: 1px solid #404040; border-radius: 4px; padding-top: 15px;} QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 5px; background-color: #313335; border-radius: 3px; color: #E0E0E0;}"

        icon_size = QSize(16, 16)

        self.projects_group = QGroupBox("PROJECTS")
        self.projects_group.setFont(group_font)
        self.projects_group.setStyleSheet(group_style)

        self.create_project_button = QPushButton(" New Project")
        self.create_project_button.setFont(self.button_font)
        self.create_project_button.setIcon(
            self._load_asset_icon("new_folder_icon.svg") or self._load_qta_icon("fa5s.folder-plus"))
        self.create_project_button.setStyleSheet(button_style)
        self.create_project_button.setIconSize(icon_size)

        self.project_tree_model = QStandardItemModel(self)
        self.project_tree_view = QTreeView()
        self.project_tree_view.setModel(self.project_tree_model)
        self.project_tree_view.setHeaderHidden(True)
        self.project_tree_view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.project_tree_view.setAlternatingRowColors(True)
        self.project_tree_view.setStyleSheet(
            "QTreeView { border: 1px solid #404040; background-color: #2E2E2E; } QTreeView::item { padding: 4px; } QTreeView::item:selected { background-color: #4A6984; color: white; }")

        self.llm_config_group = QGroupBox("LLM CONFIGURATION")
        self.llm_config_group.setFont(group_font)
        self.llm_config_group.setStyleSheet(group_style)

        self.chat_llm_label = QLabel("Chat LLM:")
        self.chat_llm_combo = QComboBox()
        self.chat_llm_combo.setFont(self.button_font)
        self.chat_llm_combo.setStyleSheet(
            "QComboBox { padding: 4px; border: 1px solid #404040; background-color: #383838; } QComboBox::drop-down { border: none; } QComboBox QAbstractItemView { background-color: #383838; border: 1px solid #505050; selection-background-color: #4A6984; }")
        self.chat_llm_combo.setMinimumContentsLength(20)

        self.coding_llm_label = QLabel("Coding LLM:")
        self.coding_llm_combo = QComboBox()
        self.coding_llm_combo.setFont(self.button_font)
        self.coding_llm_combo.setStyleSheet(self.chat_llm_combo.styleSheet())
        self.coding_llm_combo.setMinimumContentsLength(20)

        self.temperature_label = QLabel("Chat Temp:")
        self.temperature_slider = QSlider(Qt.Orientation.Horizontal)
        self.temperature_slider.setRange(self._TEMP_SLIDER_MIN, self._TEMP_SLIDER_MAX)
        self.temperature_slider.setStyleSheet(
            "QSlider::groove:horizontal { border: 1px solid #404040; height: 8px; background: #2E2E2E; margin: 2px 0; border-radius: 4px; } QSlider::handle:horizontal { background: #4A6984; border: 1px solid #5A7994; width: 14px; margin: -3px 0; border-radius: 7px; }")

        self.temperature_spinbox = QDoubleSpinBox()
        self.temperature_spinbox.setRange(0.0, 2.0)
        self.temperature_spinbox.setSingleStep(0.01)
        self.temperature_spinbox.setDecimals(2)
        self.temperature_spinbox.setFont(self.button_font)
        self.temperature_spinbox.setFixedWidth(65)
        self.temperature_spinbox.setStyleSheet(
            "QDoubleSpinBox { padding: 3px; border: 1px solid #404040; background-color: #383838; }")

        self.actions_group = QGroupBox("ACTIONS & TOOLS")
        self.actions_group.setFont(group_font)
        self.actions_group.setStyleSheet(group_style)

        self.new_chat_button = QPushButton(" New Chat Session")
        self.new_chat_button.setFont(self.button_font); self.new_chat_button.setIcon(self._load_qta_icon("fa5s.comment-dots")); self.new_chat_button.setStyleSheet(button_style); self.new_chat_button.setIconSize(icon_size)
        self.manage_sessions_button = QPushButton(" Manage Sessions"); self.manage_sessions_button.setFont(self.button_font); self.manage_sessions_button.setIcon(self._load_qta_icon("fa5s.folder-open")); self.manage_sessions_button.setStyleSheet(button_style); self.manage_sessions_button.setIconSize(icon_size)
        self.upload_files_button = QPushButton(" Add Files to Project RAG"); self.upload_files_button.setFont(self.button_font); self.upload_files_button.setIcon(self._load_qta_icon("fa5s.file-upload")); self.upload_files_button.setStyleSheet(button_style); self.upload_files_button.setIconSize(icon_size)
        self.upload_folder_button = QPushButton(" Add Folder to Project RAG"); self.upload_folder_button.setFont(self.button_font); self.upload_folder_button.setIcon(self._load_qta_icon("fa5s.folder-plus", color="#F0B75A")); self.upload_folder_button.setStyleSheet(button_style); self.upload_folder_button.setIconSize(icon_size)
        self.view_project_rag_button = QPushButton(" View Project RAG"); self.view_project_rag_button.setFont(self.button_font); self.view_project_rag_button.setIcon(self._load_qta_icon("fa5s.database")); self.view_project_rag_button.setStyleSheet(button_style); self.view_project_rag_button.setIconSize(icon_size)
        self.manage_global_rag_button = QPushButton(" Manage Global RAG"); self.manage_global_rag_button.setFont(self.button_font); self.manage_global_rag_button.setIcon(self._load_qta_icon("fa5s.globe-americas")); self.manage_global_rag_button.setStyleSheet(button_style); self.manage_global_rag_button.setIconSize(icon_size)
        self.view_code_button = QPushButton(" View Generated Code"); self.view_code_button.setFont(self.button_font); self.view_code_button.setIcon(self._load_qta_icon("fa5s.code")); self.view_code_button.setStyleSheet(button_style); self.view_code_button.setIconSize(icon_size)
        self.view_comms_button = QPushButton(" View LLM Comms Log"); self.view_comms_button.setFont(self.button_font); self.view_comms_button.setIcon(self._load_qta_icon("fa5s.terminal", color="#B7E1F3")); self.view_comms_button.setStyleSheet(button_style); self.view_comms_button.setIconSize(icon_size)
        self.configure_persona_button = QPushButton(" Configure AI Persona"); self.configure_persona_button.setFont(self.button_font); self.configure_persona_button.setIcon(self._load_qta_icon("fa5s.user-cog")); self.configure_persona_button.setStyleSheet(button_style); self.configure_persona_button.setIconSize(icon_size)
        self.settings_button = QPushButton(" Application Settings"); self.settings_button.setFont(self.button_font); self.settings_button.setIcon(self._load_qta_icon("fa5s.cog")); self.settings_button.setStyleSheet(button_style); self.settings_button.setIconSize(icon_size)# PyDevAI_Studio/ui/left_panel.py PART 2
    def _init_layout(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(10)

        projects_layout = QVBoxLayout(self.projects_group)
        projects_layout.setSpacing(6)
        projects_layout.addWidget(self.create_project_button)
        projects_layout.addWidget(self.project_tree_view)
        main_layout.addWidget(self.projects_group)

        llm_config_layout = QVBoxLayout(self.llm_config_group)
        llm_config_layout.setSpacing(6)
        llm_config_layout.addWidget(self.chat_llm_label)
        llm_config_layout.addWidget(self.chat_llm_combo)
        llm_config_layout.addWidget(self.coding_llm_label)
        llm_config_layout.addWidget(self.coding_llm_combo)
        temp_sub_layout = QHBoxLayout()
        temp_sub_layout.addWidget(self.temperature_label)
        temp_sub_layout.addWidget(self.temperature_slider, 1)
        temp_sub_layout.addWidget(self.temperature_spinbox)
        llm_config_layout.addLayout(temp_sub_layout)
        main_layout.addWidget(self.llm_config_group)

        actions_layout = QVBoxLayout(self.actions_group)
        actions_layout.setSpacing(6)
        actions_layout.addWidget(self.new_chat_button); actions_layout.addWidget(self.manage_sessions_button)
        actions_layout.addWidget(self._create_separator())
        actions_layout.addWidget(self.upload_files_button); actions_layout.addWidget(self.upload_folder_button); actions_layout.addWidget(self.view_project_rag_button); actions_layout.addWidget(self.manage_global_rag_button)
        actions_layout.addWidget(self._create_separator())
        actions_layout.addWidget(self.view_code_button); actions_layout.addWidget(self.view_comms_button); actions_layout.addWidget(self.configure_persona_button); actions_layout.addWidget(self.settings_button)
        main_layout.addWidget(self.actions_group)

        main_layout.addStretch(1)
        self.setLayout(main_layout)

    def _create_separator(self) -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("QFrame { border: 1px solid #404040; margin-top: 5px; margin-bottom: 5px; }")
        return separator

    def _connect_signals(self) -> None:
        self.create_project_button.clicked.connect(self.create_project_requested)
        self.project_tree_view.selectionModel().currentChanged.connect(self._handle_project_selection_changed)
        self.new_chat_button.clicked.connect(self.new_chat_session_requested); self.manage_sessions_button.clicked.connect(self.manage_chat_sessions_requested)
        self.upload_files_button.clicked.connect(self.upload_files_to_project_requested); self.upload_folder_button.clicked.connect(self.upload_folder_to_project_requested)
        self.view_project_rag_button.clicked.connect(self.view_project_rag_requested); self.manage_global_rag_button.clicked.connect(self.manage_global_rag_requested)
        self.view_code_button.clicked.connect(self.view_generated_code_requested); self.view_comms_button.clicked.connect(self.view_llm_comms_requested)
        self.configure_persona_button.clicked.connect(self.configure_persona_requested); self.settings_button.clicked.connect(self.open_settings_requested)
        self.chat_llm_combo.currentIndexChanged.connect(self._on_chat_llm_combo_changed)
        self.coding_llm_combo.currentIndexChanged.connect(self._on_coding_llm_combo_changed)
        self.temperature_slider.valueChanged.connect(self._on_temperature_slider_changed)
        self.temperature_spinbox.valueChanged.connect(self._on_temperature_spinbox_changed)
        self.project_tree_view.doubleClicked.connect(self._handle_project_item_double_clicked)

    def load_initial_settings(self) -> None:
        self._is_programmatic_temp_change = True
        temp = self.settings.get("chat_llm_temperature", 0.7)
        self.temperature_slider.setValue(int(temp * self._TEMP_PRECISION_FACTOR))
        self.temperature_spinbox.setValue(temp)
        self._is_programmatic_temp_change = False
        self.update_rag_button_state()

    async def async_populate_llm_combos(self) -> None:
        logger.info("LeftControlPanel: Asynchronously populating LLM comboboxes...")
        self._is_programmatic_llm_change = True
        self.chat_llm_combo.blockSignals(True)
        self.coding_llm_combo.blockSignals(True)
        self.chat_llm_combo.clear()
        self.coding_llm_combo.clear()

        llm_manager = self.orchestrator.get_llm_manager()
        if not llm_manager:
            self.chat_llm_combo.addItem("LLM Manager Not Ready")
            self.coding_llm_combo.addItem("LLM Manager Not Ready")
            self.chat_llm_combo.setEnabled(False)
            self.coding_llm_combo.setEnabled(False)
            self._reblock_llm_signals_and_end_programmatic_change()
            return

        providers = [p for p in constants.LLMProvider]

        for provider_enum_member in providers:
            provider_value = provider_enum_member.value
            provider_settings = self.settings.get_llm_provider_settings(provider_value)
            api_key_for_provider = provider_settings.get("api_key") if provider_settings else None
            models_list, error = await llm_manager.get_available_models_for_provider(provider_value, api_key_for_provider)

            if error:
                logger.warning(f"Could not fetch models for {provider_value}: {error}")
                display_text = f"{provider_value} - (Error: {error[:30]}...)"
                self.chat_llm_combo.addItem(display_text, {"provider": provider_value, "model_id": "ERROR", "error": True})
                self.coding_llm_combo.addItem(display_text, {"provider": provider_value, "model_id": "ERROR", "error": True})
                continue

            if not models_list:
                display_text = f"{provider_value} - (No models found/API key?)"
                self.chat_llm_combo.addItem(display_text, {"provider": provider_value, "model_id": "NONE_FOUND", "error": True})
                self.coding_llm_combo.addItem(display_text, {"provider": provider_value, "model_id": "NONE_FOUND", "error": True})
                continue

            for model_detail in models_list:
                model_id = model_detail.get("id")
                model_name = model_detail.get("name", model_id)
                if not model_id: continue

                item_text = f"{provider_value} - {model_name}"
                item_data = {"provider": provider_value, "model_id": model_id}

                self.chat_llm_combo.addItem(item_text, item_data)
                self.coding_llm_combo.addItem(item_text, item_data)

        self.chat_llm_combo.setEnabled(self.chat_llm_combo.count() > 0 and not self.chat_llm_combo.itemData(0).get("error"))
        self.coding_llm_combo.setEnabled(self.coding_llm_combo.count() > 0 and not self.coding_llm_combo.itemData(0).get("error"))

        active_chat_provider = self.settings.get("active_chat_llm_provider", constants.DEFAULT_CHAT_PROVIDER.value)
        chat_provider_settings = self.settings.get_llm_provider_settings(active_chat_provider)
        active_chat_model = chat_provider_settings.get("default_chat_model", "") if chat_provider_settings else ""
        self._set_combo_selection(self.chat_llm_combo, active_chat_provider, active_chat_model)

        active_coding_provider = self.settings.get("active_coding_llm_provider", constants.DEFAULT_CODING_PROVIDER.value)
        coding_provider_settings = self.settings.get_llm_provider_settings(active_coding_provider)
        active_coding_model = coding_provider_settings.get("default_coding_model", "") if coding_provider_settings else ""
        self._set_combo_selection(self.coding_llm_combo, active_coding_provider, active_coding_model)

        self._reblock_llm_signals_and_end_programmatic_change()
        logger.info("LeftControlPanel: LLM comboboxes populated.")

    def _reblock_llm_signals_and_end_programmatic_change(self):
        self.chat_llm_combo.blockSignals(False)
        self.coding_llm_combo.blockSignals(False)
        self._is_programmatic_llm_change = False

    def _set_combo_selection(self, combo: QComboBox, provider_name: str, model_id: str) -> None:
        if not provider_name or not model_id: return
        for i in range(combo.count()):
            item_data = combo.itemData(i)
            if isinstance(item_data, dict) and \
               item_data.get("provider") == provider_name and \
               item_data.get("model_id") == model_id and \
               not item_data.get("error"):
                if combo.currentIndex() != i:
                    combo.setCurrentIndex(i)
                return
        for i in range(combo.count()):
            item_data = combo.itemData(i)
            if isinstance(item_data, dict) and \
                item_data.get("provider") == provider_name and \
               not item_data.get("error"):
                if combo.currentIndex() != i:
                    combo.setCurrentIndex(i)
                return
        if combo.count() > 0 and not combo.itemData(0).get("error"):
            if combo.currentIndex() != 0:
                 combo.setCurrentIndex(0)

    @pyqtSlot(QModelIndex, QModelIndex)
    def _handle_project_selection_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if self._is_programmatic_selection_change or not current.isValid():
            return
        item = self.project_tree_model.itemFromIndex(current)
        if item:
            project_id = item.data(self._PROJECT_ID_ROLE)
            if isinstance(project_id, str):
                self.project_selected_from_ui.emit(project_id)

    @pyqtSlot(QModelIndex)
    def _handle_project_item_double_clicked(self, index: QModelIndex) -> None:
        if not index.isValid(): return
        item = self.project_tree_model.itemFromIndex(index)
        if item:
            project_id = item.data(self._PROJECT_ID_ROLE)
            if isinstance(project_id, str) and project_id != constants.GLOBAL_RAG_COLLECTION_ID:
                project = self.orchestrator.get_project_manager().get_project_by_id(
                    project_id) if self.orchestrator and self.orchestrator.get_project_manager() else None
                if project and project.path:
                    self.open_file_requested.emit(project.path)

    @pyqtSlot(int)
    def _on_chat_llm_combo_changed(self, index: int) -> None:
        if self._is_programmatic_llm_change or index < 0:
            return
        item_data = self.chat_llm_combo.itemData(index)
        if isinstance(item_data, dict) and not item_data.get("error"):
            provider = item_data.get("provider")
            model_id = item_data.get("model_id")
            if provider and model_id:
                provider_settings = self.settings.get_llm_provider_settings(provider)
                api_key = provider_settings.get("api_key") if provider_settings else None
                self.chat_llm_changed.emit(provider, model_id, api_key)

    @pyqtSlot(int)
    def _on_coding_llm_combo_changed(self, index: int) -> None:
        if self._is_programmatic_llm_change or index < 0:
            return
        item_data = self.coding_llm_combo.itemData(index)
        if isinstance(item_data, dict) and not item_data.get("error"):
            provider = item_data.get("provider")
            model_id = item_data.get("model_id")
            if provider and model_id:
                provider_settings = self.settings.get_llm_provider_settings(provider)
                api_key = provider_settings.get("api_key") if provider_settings else None
                self.coding_llm_changed.emit(provider, model_id, api_key)

    @pyqtSlot(int)
    def _on_temperature_slider_changed(self, value: int) -> None:
        if self._is_programmatic_temp_change: return
        float_value = value / self._TEMP_PRECISION_FACTOR
        self._is_programmatic_temp_change = True
        self.temperature_spinbox.setValue(float_value)
        self._is_programmatic_temp_change = False
        self.temperature_changed.emit(float_value)

    @pyqtSlot(float)
    def _on_temperature_spinbox_changed(self, value: float) -> None:
        if self._is_programmatic_temp_change: return
        slider_value = int(value * self._TEMP_PRECISION_FACTOR)
        self._is_programmatic_temp_change = True
        self.temperature_slider.setValue(slider_value)
        self._is_programmatic_temp_change = False
        self.temperature_changed.emit(value)

    @pyqtSlot(dict)
    def update_project_list(self, projects: Dict[str, str]) -> None:
        self._is_programmatic_selection_change = True
        self.project_tree_model.clear()
        global_item = QStandardItem(constants.GLOBAL_CONTEXT_DISPLAY_NAME)
        global_item.setData(constants.GLOBAL_RAG_COLLECTION_ID, self._PROJECT_ID_ROLE)
        global_item.setIcon(self._load_qta_icon("fa5s.globe") or self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        self.project_tree_model.appendRow(global_item)
        sorted_projects = sorted(projects.items(), key=lambda item: item[1].lower())
        for project_id, project_name in sorted_projects:
            if project_id == constants.GLOBAL_RAG_COLLECTION_ID: continue
            item = QStandardItem(project_name)
            item.setData(project_id, self._PROJECT_ID_ROLE)
            item.setIcon(self._load_asset_icon("new_folder_icon.svg") or self._load_qta_icon("fa5s.folder"))
            self.project_tree_model.appendRow(item)
        active_project_id = self.orchestrator.get_project_manager().get_active_project_id() if self.orchestrator and self.orchestrator.get_project_manager() else None
        self.update_active_project_selection(active_project_id)
        self._is_programmatic_selection_change = False

    @pyqtSlot(str)
    def update_active_project_selection(self, active_project_id: Optional[str]) -> None:
        self._is_programmatic_selection_change = True
        target_id = active_project_id if active_project_id else constants.GLOBAL_RAG_COLLECTION_ID
        for i in range(self.project_tree_model.rowCount()):
            item = self.project_tree_model.item(i)
            if item and item.data(self._PROJECT_ID_ROLE) == target_id:
                idx_to_select = self.project_tree_model.indexFromItem(item)
                if self.project_tree_view.currentIndex() != idx_to_select:
                    self.project_tree_view.setCurrentIndex(idx_to_select)
                self._is_programmatic_selection_change = False
                self.update_rag_button_state()
                return
        if self.project_tree_model.rowCount() > 0:
            global_item_index = self.project_tree_model.index(0,0) # Assuming global is always first
            if self.project_tree_model.itemFromIndex(global_item_index).data(self._PROJECT_ID_ROLE) == constants.GLOBAL_RAG_COLLECTION_ID:
                if self.project_tree_view.currentIndex() != global_item_index:
                    self.project_tree_view.setCurrentIndex(global_item_index)
        self._is_programmatic_selection_change = False
        self.update_rag_button_state()

    def update_rag_button_state(self) -> None:
        active_project_id_from_manager = self.orchestrator.get_project_manager().get_active_project_id() if self.orchestrator and self.orchestrator.get_project_manager() else None

        # Determine which collection is "active" for RAG operations
        # If a specific project is selected in the tree (and it's not the "Global" item), use that.
        # Otherwise, if "Global" is selected or no specific project, RAG ops might target global or active project from manager.
        # For simplicity, "View Project RAG" is tied to the Project Manager's active project.
        # "Add Files/Folder to Project RAG" will also target this active project.
        # "Manage Global RAG" always targets global.
        is_specific_project_active_in_manager = active_project_id_from_manager and active_project_id_from_manager != constants.GLOBAL_RAG_COLLECTION_ID

        self.upload_files_button.setEnabled(is_specific_project_active_in_manager)
        self.upload_folder_button.setEnabled(is_specific_project_active_in_manager)
        self.view_project_rag_button.setEnabled(is_specific_project_active_in_manager) # Button itself refers to "Project RAG"

        rag_service = self.orchestrator.get_rag_service() if self.orchestrator else None
        if rag_service:
            if is_specific_project_active_in_manager:
                project_collection_id = rag_service._get_project_rag_collection_id(active_project_id_from_manager)
                if rag_service.vector_db_service.is_ready(project_collection_id) and \
                   rag_service.vector_db_service.get_collection_size(project_collection_id) > 0:
                    self.view_project_rag_button.setText(" View Project RAG (Active)")
                else:
                     self.view_project_rag_button.setText(" View Project RAG")
            else: # No specific project is active in manager, so "View Project RAG" is just placeholder
                self.view_project_rag_button.setText(" View Project RAG")


            if rag_service.vector_db_service.is_ready(constants.GLOBAL_RAG_COLLECTION_ID) and \
               rag_service.vector_db_service.get_collection_size(constants.GLOBAL_RAG_COLLECTION_ID) > 0:
                self.manage_global_rag_button.setText(" Manage Global RAG (Active)")
            else:
                self.manage_global_rag_button.setText(" Manage Global RAG")
        else: # No RAG service
            self.view_project_rag_button.setText(" View Project RAG")
            self.manage_global_rag_button.setText(" Manage Global RAG")


    @pyqtSlot(str, str, bool)
    def update_llm_selection_from_core(self, provider_name: str, model_id: str, is_chat_llm: bool) -> None:
        self._is_programmatic_llm_change = True
        combo_to_update = self.chat_llm_combo if is_chat_llm else self.coding_llm_combo
        self._set_combo_selection(combo_to_update, provider_name, model_id)
        self._is_programmatic_llm_change = False