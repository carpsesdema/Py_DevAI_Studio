# PyDevAI_Studio/ui/dialogs/personality_dialog.py
import logging
from typing import Optional, Dict

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QDialogButtonBox,
    QGroupBox, QLabel, QScrollArea, QWidget
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import pyqtSlot, Qt, pyqtSignal

from utils import constants
from core.app_settings import AppSettings

logger = logging.getLogger(constants.APP_NAME)


class PersonalityDialog(QDialog):
    prompts_updated = pyqtSignal()

    def __init__(self, settings: AppSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Configure AI Personas")
        self.setMinimumSize(600, 700)
        self.setObjectName("PersonalityDialog")

        self._chat_llm_prompt_edit: Optional[QTextEdit] = None
        self._coding_llm_prompt_edit: Optional[QTextEdit] = None

        self._init_ui()
        self._load_prompts()
        self._connect_signals()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # Chat LLM (Planner) Persona Section
        chat_persona_group = QGroupBox("Chat LLM (Planner) Persona")
        chat_persona_layout = QVBoxLayout(chat_persona_group)

        chat_info_label = QLabel(
            "This system prompt guides the Chat LLM in understanding user requests and generating structured instructions for the Coding LLM.")
        chat_info_label.setWordWrap(True)
        chat_persona_layout.addWidget(chat_info_label)

        self._chat_llm_prompt_edit = QTextEdit()
        self._chat_llm_prompt_edit.setObjectName("ChatLLMPromptEdit")
        self._chat_llm_prompt_edit.setAcceptRichText(False)
        self._chat_llm_prompt_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        chat_persona_layout.addWidget(self._chat_llm_prompt_edit)
        main_layout.addWidget(chat_persona_group)

        # Coding LLM Persona Section
        coding_persona_group = QGroupBox("Coding LLM Persona")
        coding_persona_layout = QVBoxLayout(coding_persona_group)

        coding_info_label = QLabel(
            "This system prompt instructs the Coding LLM on how to generate Python code, focusing on quality, style (PEP 8, type hints, docstrings), and adherence to instructions.")
        coding_info_label.setWordWrap(True)
        coding_persona_layout.addWidget(coding_info_label)

        self._coding_llm_prompt_edit = QTextEdit()
        self._coding_llm_prompt_edit.setObjectName("CodingLLMPromptEdit")
        self._coding_llm_prompt_edit.setAcceptRichText(False)
        self._coding_llm_prompt_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        coding_persona_layout.addWidget(self._coding_llm_prompt_edit)
        main_layout.addWidget(coding_persona_group)

        # Buttons
        button_layout = QHBoxLayout()
        load_defaults_button = QPushButton("Load Defaults")
        button_layout.addWidget(load_defaults_button)
        button_layout.addStretch(1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_layout.addWidget(self.button_box)
        main_layout.addLayout(button_layout)

        # Connect button actions
        load_defaults_button.clicked.connect(self._load_default_prompts_to_ui)

    def _connect_signals(self):
        self.button_box.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self.accept)
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)

    def _load_prompts(self):
        if self._chat_llm_prompt_edit:
            chat_prompt = self.settings.get(
                "custom_chat_llm_system_prompt") or constants.CHAT_LLM_CODE_INSTRUCTION_SYSTEM_PROMPT
            self._chat_llm_prompt_edit.setPlainText(chat_prompt)

        if self._coding_llm_prompt_edit:
            coding_prompt = self.settings.get("custom_coding_llm_system_prompt") or constants.CODING_LLM_SYSTEM_PROMPT
            self._coding_llm_prompt_edit.setPlainText(coding_prompt)
        logger.debug("Personality prompts loaded into dialog.")

    @pyqtSlot()
    def _load_default_prompts_to_ui(self):
        if self._chat_llm_prompt_edit:
            self._chat_llm_prompt_edit.setPlainText(constants.CHAT_LLM_CODE_INSTRUCTION_SYSTEM_PROMPT)
        if self._coding_llm_prompt_edit:
            self._coding_llm_prompt_edit.setPlainText(constants.CODING_LLM_SYSTEM_PROMPT)
        logger.info("Default prompts loaded into PersonalityDialog UI.")

    def _save_prompts(self):
        prompts_changed = False
        if self._chat_llm_prompt_edit:
            new_chat_prompt = self._chat_llm_prompt_edit.toPlainText()
            current_chat_prompt_setting = self.settings.get("custom_chat_llm_system_prompt")
            default_chat_prompt = constants.CHAT_LLM_CODE_INSTRUCTION_SYSTEM_PROMPT

            if new_chat_prompt != (current_chat_prompt_setting or default_chat_prompt):
                self.settings.set("custom_chat_llm_system_prompt",
                                  new_chat_prompt if new_chat_prompt != default_chat_prompt else None)
                prompts_changed = True
                logger.info("Custom Chat LLM system prompt updated in settings.")

        if self._coding_llm_prompt_edit:
            new_coding_prompt = self._coding_llm_prompt_edit.toPlainText()
            current_coding_prompt_setting = self.settings.get("custom_coding_llm_system_prompt")
            default_coding_prompt = constants.CODING_LLM_SYSTEM_PROMPT

            if new_coding_prompt != (current_coding_prompt_setting or default_coding_prompt):
                self.settings.set("custom_coding_llm_system_prompt",
                                  new_coding_prompt if new_coding_prompt != default_coding_prompt else None)
                prompts_changed = True
                logger.info("Custom Coding LLM system prompt updated in settings.")

        if prompts_changed:
            self.settings.save()  # Explicit save as set may not save if autosave is off for dialog changes
            self.prompts_updated.emit()

    def accept(self):
        self._save_prompts()
        super().accept()

    def reject(self):
        super().reject()