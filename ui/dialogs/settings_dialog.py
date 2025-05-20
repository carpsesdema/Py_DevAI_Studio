# PyDevAI_Studio/ui/dialogs/settings_dialog.py
import logging
from typing import Optional, Dict, Any, cast

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel, QLineEdit,
    QPushButton, QSpacerItem, QSizePolicy, QFontComboBox, QSpinBox, QCheckBox,
    QFormLayout, QGroupBox, QScrollArea, QDialogButtonBox
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot

from utils import constants
from core.app_settings import AppSettings
from core.orchestrator import AppOrchestrator

logger = logging.getLogger(constants.APP_NAME)


class SettingsDialog(QDialog):
    settings_applied = pyqtSignal()

    def __init__(self, settings: AppSettings, orchestrator: AppOrchestrator, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.orchestrator = orchestrator
        self.setWindowTitle("Application Settings")
        self.setMinimumSize(600, 500)
        self.setObjectName("SettingsDialog")

        self._ui_widgets: Dict[str, QWidget] = {}

        self._init_ui()
        self._load_settings()
        self._connect_signals()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        general_tab_widget = QWidget()
        general_layout = QFormLayout(general_tab_widget)
        general_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._add_general_settings(general_layout)
        self.tab_widget.addTab(general_tab_widget, "General")

        llm_providers_main_tab_widget = QWidget()
        llm_providers_main_layout = QVBoxLayout(llm_providers_main_tab_widget)
        self.llm_provider_tabs = QTabWidget()
        llm_providers_main_layout.addWidget(self.llm_provider_tabs)
        self._add_llm_provider_settings()
        self.tab_widget.addTab(llm_providers_main_tab_widget, "LLM Providers")

        rag_tab_widget = QWidget()
        rag_layout = QFormLayout(rag_tab_widget)
        rag_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._add_rag_settings(rag_layout)
        self.tab_widget.addTab(rag_tab_widget, "RAG")

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply)
        main_layout.addWidget(self.button_box)

    def _add_widget_with_label(self, layout: QFormLayout, label_text: str, widget: QWidget,
                               setting_key: Optional[str] = None):
        layout.addRow(QLabel(label_text), widget)
        if setting_key:
            self._ui_widgets[setting_key] = widget

    def _add_general_settings(self, layout: QFormLayout):
        ui_font_family_combo = QFontComboBox()
        ui_font_family_combo.setEditable(False)
        self._add_widget_with_label(layout, "UI Font Family:", ui_font_family_combo, "ui_font_family")

        ui_font_size_spin = QSpinBox()
        ui_font_size_spin.setRange(8, 20)
        self._add_widget_with_label(layout, "UI Font Size:", ui_font_size_spin, "ui_font_size")

        code_font_family_combo = QFontComboBox()
        code_font_family_combo.setEditable(False)
        self._add_widget_with_label(layout, "Code Font Family:", code_font_family_combo, "code_font_family")

        code_font_size_spin = QSpinBox()
        code_font_size_spin.setRange(8, 18)
        self._add_widget_with_label(layout, "Code Font Size:", code_font_size_spin, "code_font_size")

        theme_combo = QLineEdit("dark (placeholder - not editable)")
        theme_combo.setReadOnly(True)
        self._add_widget_with_label(layout, "Theme:", theme_combo, "theme")

        autosave_checkbox = QCheckBox("Automatically save settings on change")
        self._add_widget_with_label(layout, "Autosave:", autosave_checkbox, "autosave_settings")

    def _add_llm_provider_settings(self):
        for provider in constants.LLMProvider:
            provider_key = provider.value
            provider_tab = QWidget()
            provider_layout = QFormLayout(provider_tab)
            provider_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

            group_box = QGroupBox(f"{provider_key} Settings")
            group_box_layout = QFormLayout(group_box)

            if provider == constants.LLMProvider.OLLAMA:
                ollama_host_edit = QLineEdit()
                self._add_widget_with_label(group_box_layout, "Ollama Host URL:", ollama_host_edit,
                                            f"llm_providers.{provider_key}.host")
            else:
                api_key_edit = QLineEdit()
                api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
                self._add_widget_with_label(group_box_layout, "API Key:", api_key_edit,
                                            f"llm_providers.{provider_key}.api_key")

            default_chat_model_edit = QLineEdit()
            self._add_widget_with_label(group_box_layout, "Default Chat Model ID:", default_chat_model_edit,
                                        f"llm_providers.{provider_key}.default_chat_model")

            default_coding_model_edit = QLineEdit()
            self._add_widget_with_label(group_box_layout, "Default Coding Model ID:", default_coding_model_edit,
                                        f"llm_providers.{provider_key}.default_coding_model")

            provider_layout.addWidget(group_box)
            self.llm_provider_tabs.addTab(provider_tab, provider_key)

    def _add_rag_settings(self, layout: QFormLayout):
        embedding_model_edit = QLineEdit()
        embedding_model_edit.setReadOnly(True)
        self._add_widget_with_label(layout, "Embedding Model:", embedding_model_edit, "rag_embedding_model")

        rag_top_k_spin = QSpinBox()
        rag_top_k_spin.setRange(1, 20)
        self._add_widget_with_label(layout, "Top K Results:", rag_top_k_spin, "rag_top_k")

        rag_chunk_size_spin = QSpinBox()
        rag_chunk_size_spin.setRange(100, 8000)
        rag_chunk_size_spin.setSingleStep(50)
        self._add_widget_with_label(layout, "Chunk Size (chars):", rag_chunk_size_spin, "rag_chunk_size")

        rag_chunk_overlap_spin = QSpinBox()
        rag_chunk_overlap_spin.setRange(0, 1000)
        rag_chunk_overlap_spin.setSingleStep(20)
        self._add_widget_with_label(layout, "Chunk Overlap (chars):", rag_chunk_overlap_spin, "rag_chunk_overlap")

    def _connect_signals(self):
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).clicked.connect(self.accept)
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        self.button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply_settings)

    def _load_settings(self):
        logger.debug("Loading settings into dialog UI.")
        for key, widget in self._ui_widgets.items():
            value = self.settings.get(key)
            if isinstance(widget, QLineEdit):
                widget.setText(str(value) if value is not None else "")
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value) if isinstance(value, (int, float)) else widget.minimum())
            elif isinstance(widget, QFontComboBox):
                current_font = QFont(str(value) if value else constants.DEFAULT_FONT_FAMILY)
                widget.setCurrentFont(current_font)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value) if value is not None else False)

    def _save_settings(self):
        logger.info("Saving settings from dialog UI.")
        changed_keys = []
        for key, widget in self._ui_widgets.items():
            current_value_in_settings = self.settings.get(key)
            new_value: Any = None

            if isinstance(widget, QLineEdit):
                new_value = widget.text()
            elif isinstance(widget, QSpinBox):
                new_value = widget.value()
            elif isinstance(widget, QFontComboBox):
                new_value = widget.currentFont().family()
            elif isinstance(widget, QCheckBox):
                new_value = widget.isChecked()

            if new_value is not None and str(new_value) != str(current_value_in_settings):
                self.settings.set(key, new_value)
                changed_keys.append(key)
                logger.debug(f"Setting '{key}' changed to '{new_value}'")

        if changed_keys:
            self.settings.save()
            logger.info(f"Saved {len(changed_keys)} settings. Changed keys: {', '.join(changed_keys)}")
        else:
            logger.info("No settings were changed.")
        return changed_keys

    @pyqtSlot()
    def _apply_settings(self):
        changed_keys = self._save_settings()
        if changed_keys:
            self.settings_applied.emit()

    def accept(self):
        self._apply_settings()
        super().accept()

    def reject(self):
        super().reject()