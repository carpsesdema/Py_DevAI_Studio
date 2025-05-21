# SynAva_1.0/ui/dialogs/code_viewer_dialog.py
# Contains the CodeViewerWindow class, extracted from the original dialogs.py

import logging
from datetime import datetime
from typing import Optional, Dict

from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal # Added pyqtSignal
from PyQt6.QtGui import QIcon, QFontDatabase, QTextOption
# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QSplitter,
    QApplication, QMessageBox, QTreeWidget, QTreeWidgetItem, QWidget
)

# --- Local Imports ---
try:
    from utils import constants
    from utils.constants import CHAT_FONT_FAMILY, CHAT_FONT_SIZE
    from utils.syntax_highlighter import PythonSyntaxHighlighter
    from ui.widgets import load_icon, COPY_ICON, CHECK_ICON # Added load_icon

    # --- NEW: Icon for Apply Button ---
    APPLY_ICON = load_icon("save_icon.svg") # Assuming you have a save_icon.svg
    # --- END NEW ---

except ImportError as e:
    logging.error(f"Error importing dependencies in code_viewer_dialog.py: {e}. Check relative paths.")
    class constants: CHAT_FONT_FAMILY = "Arial"; CHAT_FONT_SIZE = 10
    class PythonSyntaxHighlighter: pass
    COPY_ICON, CHECK_ICON, APPLY_ICON = QIcon(), QIcon(), QIcon()


logger = logging.getLogger(__name__)


class CodeViewerWindow(QDialog):
    CODE_CONTENT_ROLE = Qt.ItemDataRole.UserRole + 10
    # --- NEW SIGNAL ---
    # Emits: project_id, relative_filepath, new_content, focus_prefix
    apply_change_requested = pyqtSignal(str, str, str, str)
    # --- END NEW SIGNAL ---

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Code Viewer")
        self.setObjectName("CodeViewerWindow")
        self.setMinimumSize(700, 500)
        self.setModal(False)

        self._file_contents: Dict[str, str] = {} # filename: content
        # --- NEW: Store original content for diffing and context for applying ---
        self._original_file_contents: Dict[str, Optional[str]] = {} # filename: original_content or None if new
        self._current_filename: Optional[str] = None
        self._current_project_id_for_apply: Optional[str] = None
        self._current_focus_prefix_for_apply: Optional[str] = None
        self._current_content_is_modification: bool = False # Is the current view an AI mod?
        # --- END NEW ---

        self._init_widgets()
        self._init_layout()
        self._connect_signals()
        self._attach_highlighter()

    def _init_widgets(self):
        code_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        code_font.setPointSize(constants.CHAT_FONT_SIZE)
        self.code_font = code_font

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.file_tree = QTreeWidget()
        self.file_tree.setObjectName("CodeFileTree")
        self.file_tree.setHeaderLabels(["File / Block"])
        self.file_tree.setMinimumWidth(200)
        self.file_tree.header().setStretchLastSection(True)

        self.code_edit = QTextEdit()
        self.code_edit.setObjectName("CodeViewerEdit")
        self.code_edit.setReadOnly(True)
        self.code_edit.setFont(self.code_font)
        self.code_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.code_edit.setWordWrapMode(QTextOption.WrapMode.NoWrap)

        self.copy_button = QPushButton(" Copy Code")
        self.copy_button.setToolTip("Copy the code currently shown")
        if not COPY_ICON.isNull(): self.copy_button.setIcon(COPY_ICON)
        self.copy_button.setEnabled(False)

        # --- NEW: Apply Button ---
        self.apply_button = QPushButton(" Apply & Save Change")
        self.apply_button.setToolTip("Save this AI-generated version to the local file")
        if not APPLY_ICON.isNull(): self.apply_button.setIcon(APPLY_ICON)
        self.apply_button.setEnabled(False) # Disabled initially
        self.apply_button.setObjectName("ApplyChangeButton")
        # --- END NEW ---

        self.clear_button = QPushButton("Clear All")
        self.clear_button.setToolTip("Remove all listed files/blocks")
        self.clear_button.setEnabled(False)

        self.close_button = QPushButton("Close")
        self.close_button.setToolTip("Hide this window")

    def _init_layout(self):
        layout = QVBoxLayout(self)
        self.splitter.addWidget(self.file_tree)
        self.splitter.addWidget(self.code_edit)
        self.splitter.setSizes([220, 480])
        layout.addWidget(self.splitter, 1)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.copy_button)
        # --- NEW: Add Apply button to layout ---
        button_layout.addWidget(self.apply_button)
        # --- END NEW ---
        button_layout.addStretch()
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _connect_signals(self):
        self.file_tree.currentItemChanged.connect(self._display_selected_file_content)
        self.copy_button.clicked.connect(self._copy_selected_code_with_feedback)
        # --- NEW: Connect Apply button ---
        self.apply_button.clicked.connect(self._handle_apply_change)
        # --- END NEW ---
        self.clear_button.clicked.connect(self.clear_viewer)
        self.close_button.clicked.connect(self.hide)

    def _attach_highlighter(self):
        self.highlighter = None
        try:
            self.highlighter = PythonSyntaxHighlighter(self.code_edit.document())
            logger.info("CodeViewerWindow: PythonSyntaxHighlighter attached.")
        except Exception as e_hl:
            logger.error(f"Error attaching PythonSyntaxHighlighter: {e_hl}")

    # --- MODIFIED: update_or_add_file to accept modification context ---
    def update_or_add_file(self,
                           filename: str,
                           content: str,
                           is_ai_modification: bool = False,
                           original_content: Optional[str] = None,
                           project_id_for_apply: Optional[str] = None,
                           focus_prefix_for_apply: Optional[str] = None):
        if not filename:
            logger.warning("Attempted to add/update file with empty filename.")
            return

        self._file_contents[filename] = content
        # --- NEW: Store original content if this is a modification ---
        if is_ai_modification:
            self._original_file_contents[filename] = original_content # Could be None if it's a new file in a modification sequence
        # --- END NEW ---
        self.clear_button.setEnabled(True)

        found_item = None
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            if item and item.text(0) == filename:
                found_item = item
                break

        if found_item:
            logger.debug(f"Updating existing file in Code Viewer: {filename}")
            self.file_tree.setCurrentItem(found_item)
            if self._current_filename == filename: # If re-selecting the same, force content update
                self._display_selected_file_content(found_item, None,
                                                    is_ai_modification, project_id_for_apply, focus_prefix_for_apply)
        else:
            logger.debug(f"Adding new file to Code Viewer: {filename}")
            new_item = QTreeWidgetItem(self.file_tree)
            new_item.setText(0, filename)
            new_item.setToolTip(0, filename)
            self.file_tree.setCurrentItem(new_item) # This will trigger _display_selected_file_content

        # If the newly added/updated file is the one being selected, store its modification context
        # This is also handled in _display_selected_file_content, but setting it here ensures
        # it's available if the selection doesn't "change" but content does.
        if self.file_tree.currentItem() and self.file_tree.currentItem().text(0) == filename:
            self._current_content_is_modification = is_ai_modification
            self._current_project_id_for_apply = project_id_for_apply if is_ai_modification else None
            self._current_focus_prefix_for_apply = focus_prefix_for_apply if is_ai_modification else None
            self.apply_button.setEnabled(is_ai_modification and bool(content))

        if not self.isVisible(): self.show()
        self.activateWindow(); self.raise_()
    # --- END MODIFIED ---

    def add_code_block(self, language: str, code_content: str):
        timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
        lang_display = language.strip().capitalize() if language.strip() else "Code"
        block_name = f"{lang_display} Block ({timestamp})"
        # Code blocks from chat are not direct AI modifications of local files
        self.update_or_add_file(block_name, code_content, is_ai_modification=False)


    def clear_viewer(self):
        if not self._file_contents: return
        response = QMessageBox.question(self, "Confirm Clear",
                                        "Remove all items from the Code Viewer?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
        if response == QMessageBox.StandardButton.Yes:
            self._file_contents.clear()
            self._original_file_contents.clear() # NEW
            self.file_tree.clear()
            self.code_edit.clear()
            self.copy_button.setEnabled(False)
            self.apply_button.setEnabled(False) # NEW
            self.clear_button.setEnabled(False)
            self._current_filename = None
            self._current_project_id_for_apply = None # NEW
            self._current_focus_prefix_for_apply = None # NEW
            self._current_content_is_modification = False # NEW
            logger.info("Cleared all files/blocks from CodeViewerWindow.")

    # --- MODIFIED: _display_selected_file_content to handle modification context ---
    @pyqtSlot(QTreeWidgetItem, QTreeWidgetItem)
    def _display_selected_file_content(self, current_item: Optional[QTreeWidgetItem],
                                       previous_item: Optional[QTreeWidgetItem],
                                       # --- NEW: Optional params passed if called directly by update_or_add_file ---
                                       is_mod_override: Optional[bool] = None,
                                       proj_id_override: Optional[str] = None,
                                       focus_override: Optional[str] = None
                                       # --- END NEW ---
                                       ):
        self._reset_copy_button_icon()
        self.apply_button.setEnabled(False) # Disable by default, enable if conditions met
        self._current_content_is_modification = False
        self._current_project_id_for_apply = None
        self._current_focus_prefix_for_apply = None

        if current_item is None:
            self.code_edit.clear()
            self.copy_button.setEnabled(False)
            self._current_filename = None
            return

        filename = current_item.text(0)
        self._current_filename = filename
        code_content = self._file_contents.get(filename)

        if code_content is not None:
            # --- TODO: Implement DIFF VIEW here ---
            # For now, just display the (potentially new) content.
            # If self._original_file_contents.get(filename) exists and is different,
            # this is where you'd generate and display a diff.
            # For simplicity in this step, we just show the `code_content`.
            self.code_edit.setPlainText(code_content)
            if self.highlighter:
                try: self.highlighter.rehighlight()
                except Exception as e_rh: logger.error(f"Error rehighlighting code for {filename}: {e_rh}")
            self.copy_button.setEnabled(True)

            # --- NEW: Enable Apply button if this is a modification ---
            # Check if this display was triggered by an override (e.g. update_or_add_file)
            if is_mod_override is not None:
                self._current_content_is_modification = is_mod_override
                self._current_project_id_for_apply = proj_id_override if is_mod_override else None
                self._current_focus_prefix_for_apply = focus_override if is_mod_override else None
            else: # Infer from stored original content (less direct, update_or_add_file should be source of truth)
                if filename in self._original_file_contents: # This implies it was part of a mod sequence
                    self._current_content_is_modification = True
                    # How to get project_id and focus_prefix here if not passed?
                    # This indicates update_or_add_file needs to robustly set these instance vars
                    # For now, we rely on the overrides or prior setting.
                    # This part might need refinement if selection changes without update_or_add_file being the trigger for mod context.

            self.apply_button.setEnabled(self._current_content_is_modification and bool(code_content))
            # --- END NEW ---

        else:
            logger.warning(f"Content not found in dictionary for selected file: {filename}")
            self.code_edit.setPlainText(f"[Error: Content not found for {filename}]")
            self.copy_button.setEnabled(False)
    # --- END MODIFIED ---

    # --- NEW: Handler for Apply Button ---
    @pyqtSlot()
    def _handle_apply_change(self):
        if not self._current_filename or \
           not self._current_content_is_modification or \
           self._current_project_id_for_apply is None or \
           self._current_focus_prefix_for_apply is None: # Technically focus_prefix can be empty string for project root
            logger.warning("Apply change clicked but context is missing or not a modification.")
            QMessageBox.warning(self, "Apply Error", "Cannot apply change: Missing context or not an AI modification.")
            return

        new_content = self._file_contents.get(self._current_filename)
        if new_content is None: # Should not happen if button is enabled
            logger.error(f"Apply change: Content for '{self._current_filename}' is None.")
            QMessageBox.critical(self, "Internal Error", "Content for current file is missing.")
            return

        logger.info(f"Emitting apply_change_requested for: Proj='{self._current_project_id_for_apply}', "
                    f"File='{self._current_filename}', Focus='{self._current_focus_prefix_for_apply}'")
        self.apply_change_requested.emit(
            self._current_project_id_for_apply,
            self._current_filename, # This is the relative path
            new_content,
            self._current_focus_prefix_for_apply
        )
        # Optionally, disable apply button after emitting, or give feedback
        self.apply_button.setEnabled(False) # Prevent double-clicks
        self.apply_button.setText(" Applying...")
        # We'll need a signal back from ChangeApplierService to re-enable/reset it
    # --- END NEW ---

    def _copy_selected_code_with_feedback(self):
        code_to_copy = self.code_edit.toPlainText()
        if not code_to_copy or self._current_filename is None:
            logger.warning("Attempted to copy empty or unselected code from CodeViewerWindow.")
            return
        if code_to_copy.startswith("[Error:"): return

        try:
            clipboard = QApplication.clipboard()
            if not clipboard: raise RuntimeError("Clipboard not accessible.")
            clipboard.setText(code_to_copy)
            logger.info(f"Copied code for '{self._current_filename}' from viewer.")
            if not CHECK_ICON.isNull(): self.copy_button.setIcon(CHECK_ICON)
            self.copy_button.setEnabled(False)
            QTimer.singleShot(1500, self._reset_copy_button_icon)
        except Exception as e:
            logger.exception(f"Error copying code from viewer: {e}")
            QMessageBox.warning(self, "Copy Error", f"Could not copy code:\n{e}")

    def _reset_copy_button_icon(self):
        if not COPY_ICON.isNull(): self.copy_button.setIcon(COPY_ICON)
        self.copy_button.setEnabled(bool(self._current_filename) and self._current_filename in self._file_contents)

    def showEvent(self, event):
        super().showEvent(event)
        if self.file_tree.topLevelItemCount() > 0 and self.file_tree.currentItem() is None:
            self.file_tree.setCurrentItem(self.file_tree.topLevelItem(0))
        elif self.file_tree.currentItem():
            # When shown, re-trigger display to correctly set apply button state
            self._display_selected_file_content(self.file_tree.currentItem(), None,
                                                is_mod_override=self._current_content_is_modification,
                                                proj_id_override=self._current_project_id_for_apply,
                                                focus_override=self._current_focus_prefix_for_apply)
        self.activateWindow(); self.raise_()

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    # --- NEW: Method to reset Apply button state, perhaps called after successful apply/RAG sync ---
    # This would typically be called via a slot connected to a signal from ChangeApplierService/MainWindow
    @pyqtSlot(str) # Takes filename that was processed
    def handle_apply_completed(self, processed_filename: str):
        logger.debug(f"CodeViewer: Apply completed for {processed_filename}. Resetting button.")
        if self._current_filename == processed_filename:
            self.apply_button.setText(" Apply & Save Change")
            if not APPLY_ICON.isNull(): self.apply_button.setIcon(APPLY_ICON)
            # Re-evaluate if it can be applied again (e.g., if user wants to re-apply or if there was an error)
            # For now, let's assume after one apply, it's "done" for this version.
            self.apply_button.setEnabled(False) # Or re-enable based on state
            self._current_content_is_modification = False # Mark current content as "applied" or no longer a pending mod