# ui/code_editor_pane.py
import logging
import os
from typing import Optional, Dict, Any, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel,
    QSizePolicy, QMessageBox, QApplication, QSplitter, QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtGui import QFont, QSyntaxHighlighter, QIcon, QTextOption
from PyQt6.QtCore import Qt, pyqtSlot, QTimer, pyqtSignal, QSize

from utils import constants
from core.orchestrator import AppOrchestrator # For AppSettings

try:
    from utils.syntax_highlighter import PythonSyntaxHighlighter
    SYNTAX_HIGHLIGHTER_AVAILABLE = True
except ImportError:
    PythonSyntaxHighlighter = None # type: ignore
    SYNTAX_HIGHLIGHTER_AVAILABLE = False
    logging.warning("CodeEditorPane: PythonSyntaxHighlighter not found. Syntax highlighting will be disabled.")

logger = logging.getLogger(constants.APP_NAME)

class CodeEditorPane(QWidget):
    # Emits a dictionary of {file_path: content} for approved files
    files_approved_for_saving = pyqtSignal(dict)
    # For opening a single existing file (from ProjectExplorer)
    open_single_file_requested = pyqtSignal(str)


    FILE_CONTENT_ROLE = Qt.ItemDataRole.UserRole + 1
    FILE_IS_ERROR_ROLE = Qt.ItemDataRole.UserRole + 2

    def __init__(self, orchestrator: AppOrchestrator, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.settings = orchestrator.get_settings() # orchestrator provides settings
        self.setObjectName("CodeEditorPane")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.editor_area: Optional[QTextEdit] = None
        self.file_list_tree: Optional[QTreeWidget] = None # New: For listing multiple files
        self.current_file_label: Optional[QLabel] = None # To show which file is active
        self.save_all_button: Optional[QPushButton] = None # New: For approving and saving all
        self.copy_button: Optional[QPushButton] = None
        self.clear_all_button: Optional[QPushButton] = None # New: To clear the viewer

        self._current_file_path_active_in_editor: Optional[str] = None
        self._generated_file_contents: Dict[str, Tuple[str, bool]] = {} # {path: (content, is_error)}
        self._syntax_highlighter: Optional[QSyntaxHighlighter] = None
        self._copy_feedback_timer: Optional[QTimer] = None

        self._init_ui()
        self._connect_signals()
        self._apply_initial_state()
        logger.info("CodeEditorPane initialized (Multi-File Ready).")

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Top bar for current file info and actions
        top_bar_layout = QHBoxLayout()
        self.current_file_label = QLabel("No file selected / generated.")
        self.current_file_label.setObjectName("CodeEditorFilePathLabel")
        self.current_file_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top_bar_layout.addWidget(self.current_file_label)

        self.copy_button = QPushButton()
        self.copy_button.setObjectName("CodeEditorCopyButton")
        self.copy_button.setToolTip("Copy current file's code to clipboard")
        copy_icon_path = os.path.join(constants.ASSETS_DIR, "copy_icon.svg") # Assuming icon exists
        if os.path.exists(copy_icon_path): self.copy_button.setIcon(QIcon(copy_icon_path))
        else: self.copy_button.setText("Copy")
        self.copy_button.setIconSize(QSize(16, 16)); self.copy_button.setFixedSize(QSize(30, 26))
        self.copy_button.setEnabled(False)
        top_bar_layout.addWidget(self.copy_button)
        main_layout.addLayout(top_bar_layout)

        # Main splitter for file list and editor
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("CodeEditorSplitter")

        self.file_list_tree = QTreeWidget()
        self.file_list_tree.setObjectName("GeneratedFilesTree")
        self.file_list_tree.setHeaderLabels(["Generated Files"])
        self.file_list_tree.setMinimumWidth(180)
        self.file_list_tree.setMaximumWidth(400)
        splitter.addWidget(self.file_list_tree)

        self.editor_area = QTextEdit()
        self.editor_area.setObjectName("CodeTextEdit")
        code_font_family = self.settings.get("code_font_family", constants.CODE_FONT_FAMILY)
        code_font_size = self.settings.get("code_font_size", constants.CODE_FONT_SIZE)
        editor_font = QFont(code_font_family, code_font_size)
        self.editor_area.setFont(editor_font)
        self.editor_area.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.editor_area.setAcceptRichText(False)
        self.editor_area.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.editor_area.setReadOnly(True) # Default to read-only
        splitter.addWidget(self.editor_area)
        splitter.setSizes([200, 500]) # Initial sizes for splitter

        main_layout.addWidget(splitter, 1) # Editor area takes expanding space

        # Bottom button bar
        bottom_button_layout = QHBoxLayout()
        self.clear_all_button = QPushButton("Clear Viewer")
        self.clear_all_button.setToolTip("Clear all generated files from this viewer")
        self.clear_all_button.setEnabled(False)
        bottom_button_layout.addWidget(self.clear_all_button)
        bottom_button_layout.addStretch(1)
        self.save_all_button = QPushButton("Approve & Save All Files")
        self.save_all_button.setObjectName("CodeEditorSaveAllButton")
        self.save_all_button.setToolTip("Approve all successfully generated files and request saving to disk")
        self.save_all_button.setEnabled(False)
        bottom_button_layout.addWidget(self.save_all_button)
        main_layout.addLayout(bottom_button_layout)

        self.setLayout(main_layout)

        if SYNTAX_HIGHLIGHTER_AVAILABLE and PythonSyntaxHighlighter:
            self._syntax_highlighter = PythonSyntaxHighlighter(self.editor_area.document())

    def _connect_signals(self) -> None:
        if self.file_list_tree:
            self.file_list_tree.currentItemChanged.connect(self._on_file_selection_changed)
        if self.copy_button:
            self.copy_button.clicked.connect(self._handle_copy_action)
        if self.clear_all_button:
            self.clear_all_button.clicked.connect(self.clear_all_files)
        if self.save_all_button:
            self.save_all_button.clicked.connect(self._handle_save_all_action)
        # Connection for open_single_file_requested will be made by MainWindow/ProjectExplorer

    def _apply_initial_state(self) -> None:
        self.update_status_display(None) # No file initially selected
        self.editor_area.setReadOnly(True)

    @pyqtSlot(str, str, bool) # file_path, content, is_error
    def add_or_update_generated_file(self, file_path: str, content: str, is_error: bool):
        logger.info(f"CodeEditorPane: Adding/Updating file: {file_path}, IsError: {is_error}")
        self._generated_file_contents[file_path] = (content, is_error)

        found_item: Optional[QTreeWidgetItem] = None
        for i in range(self.file_list_tree.topLevelItemCount()):
            item = self.file_list_tree.topLevelItem(i)
            if item and item.text(0) == file_path:
                found_item = item
                break

        if found_item:
            found_item.setData(0, self.FILE_CONTENT_ROLE, content)
            found_item.setData(0, self.FILE_IS_ERROR_ROLE, is_error)
            if is_error:
                found_item.setForeground(0, Qt.GlobalColor.red) # Or a theme color
            else:
                found_item.setForeground(0, self.palette().text().color()) # Reset color
        else:
            item = QTreeWidgetItem(self.file_list_tree)
            item.setText(0, file_path)
            item.setData(0, self.FILE_CONTENT_ROLE, content)
            item.setData(0, self.FILE_IS_ERROR_ROLE, is_error)
            if is_error:
                item.setForeground(0, Qt.GlobalColor.red)
            self.file_list_tree.setCurrentItem(item) # Select new item

        self.clear_all_button.setEnabled(True)
        self.save_all_button.setEnabled(any(not err for _, err in self._generated_file_contents.values()))

        # If this is the first file or the currently displayed one, update editor
        if len(self._generated_file_contents) == 1 or self._current_file_path_active_in_editor == file_path:
            if not self.file_list_tree.currentItem() or self.file_list_tree.currentItem().text(0) != file_path:
                 if found_item: self.file_list_tree.setCurrentItem(found_item)
                 # else new item already selected
            else: # currentItem is already correct, force display update
                 self._display_file_content(file_path, content, is_error)


    @pyqtSlot(QTreeWidgetItem, QTreeWidgetItem)
    def _on_file_selection_changed(self, current: Optional[QTreeWidgetItem], previous: Optional[QTreeWidgetItem]):
        if current:
            file_path = current.text(0)
            content, is_error = self._generated_file_contents.get(file_path, (f"# Content for {file_path} not found internally", True))
            self._display_file_content(file_path, content, is_error)
        else:
            self._display_file_content(None, "", False) # Clear editor if no selection

    def _display_file_content(self, file_path: Optional[str], content: str, is_error: bool):
        self._current_file_path_active_in_editor = file_path
        self.update_status_display(file_path)
        self.editor_area.setReadOnly(True) # Generated code is initially read-only

        if is_error:
            self.editor_area.setStyleSheet("QTextEdit { color: #FF6B6B; }") # Error color
            self.editor_area.setPlainText(content)
        else:
            self.editor_area.setStyleSheet("") # Reset to default style
            self.editor_area.setPlainText(content)
            if self._syntax_highlighter and file_path and file_path.lower().endswith(".py"):
                self._syntax_highlighter.setDocument(self.editor_area.document())
                self._syntax_highlighter.rehighlight()
            elif self._syntax_highlighter:
                self._syntax_highlighter.setDocument(None) # Disable for non-python

        self.copy_button.setEnabled(bool(content and not is_error))

    def update_status_display(self, display_path: Optional[str] = None) -> None:
        if not self.current_file_label: return
        if display_path:
            self.current_file_label.setText(os.path.basename(display_path))
            self.current_file_label.setToolTip(display_path)
        else:
            self.current_file_label.setText("No file selected.")
            self.current_file_label.setToolTip("")

    @pyqtSlot()
    def _handle_copy_action(self) -> None:
        # ... (copy logic remains the same as your previous single-file version, using self.editor_area.toPlainText()) ...
        if not self.editor_area or not self.copy_button: return
        text_to_copy = self.editor_area.toPlainText()
        if not text_to_copy or (self._current_file_path_active_in_editor and self._generated_file_contents.get(self._current_file_path_active_in_editor, ("",True))[1]):
            # Don't copy if it's an error message for the current file
            return

        try:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text_to_copy)
                logger.info(f"Copied content of '{self._current_file_path_active_in_editor or 'current view'}' to clipboard.")
                original_icon = self.copy_button.icon()
                checkmark_icon_path = os.path.join(constants.ASSETS_DIR, "checkmark_icon.svg")
                if os.path.exists(checkmark_icon_path): self.copy_button.setIcon(QIcon(checkmark_icon_path))
                else: self.copy_button.setText("Copied!")
                self.copy_button.setEnabled(False)
                if self._copy_feedback_timer: self._copy_feedback_timer.stop()
                self._copy_feedback_timer = QTimer(self)
                self._copy_feedback_timer.setSingleShot(True)
                self._copy_feedback_timer.timeout.connect(lambda: self._reset_copy_button(original_icon))
                self._copy_feedback_timer.start(1500)
            else: logger.error("CodeEditorPane: Clipboard not accessible.")
        except Exception as e:
            logger.exception(f"Error copying code from editor: {e}")
            QMessageBox.warning(self, "Copy Error", f"Could not copy code: {e}")


    def _reset_copy_button(self, original_icon: QIcon) -> None:
        if self.copy_button:
            if not original_icon.isNull(): self.copy_button.setIcon(original_icon)
            else: self.copy_button.setText("Copy")
            self.copy_button.setEnabled(bool(self.editor_area and self.editor_area.toPlainText() and not (self._current_file_path_active_in_editor and self._generated_file_contents.get(self._current_file_path_active_in_editor, ("",True))[1])))


    @pyqtSlot()
    def clear_all_files(self):
        if not self._generated_file_contents: return
        reply = QMessageBox.question(self, "Clear Generated Files",
                                     "Are you sure you want to clear all files from this viewer?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._generated_file_contents.clear()
            self.file_list_tree.clear()
            self.editor_area.clear()
            self.update_status_display(None)
            self.copy_button.setEnabled(False)
            self.save_all_button.setEnabled(False)
            self.clear_all_button.setEnabled(False)
            self._current_file_path_active_in_editor = None
            logger.info("CodeEditorPane: Cleared all generated files.")

    @pyqtSlot()
    def _handle_save_all_action(self):
        if not self._generated_file_contents:
            QMessageBox.information(self, "No Files", "There are no files to save.")
            return

        approved_files_content: Dict[str, str] = {}
        for path, (content, is_error) in self._generated_file_contents.items():
            if not is_error and content is not None:
                approved_files_content[path] = content
            else:
                logger.warning(f"Skipping file '{path}' from saving due to error or no content.")

        if not approved_files_content:
            QMessageBox.information(self, "No Valid Files", "No successfully generated files available to save.")
            return

        logger.info(f"CodeEditorPane: Emitting files_approved_for_saving with {len(approved_files_content)} files.")
        self.files_approved_for_saving.emit(approved_files_content)
        # Optionally, clear viewer after approval or keep them for reference
        # self.clear_all_files() # Or just disable save button


    # Slot to handle opening a single existing file (e.g., from ProjectExplorer)
    @pyqtSlot(str)
    def display_single_file(self, file_path: str):
        logger.info(f"CodeEditorPane: Request to display single file: {file_path}")
        self.clear_all_files() # Clear any generated files first

        if not self.orchestrator or not self.orchestrator.get_file_manager():
            self._display_file_content(file_path, f"# Error: FileManager not available to load {file_path}", True)
            return

        content, error = self.orchestrator.get_file_manager().read_file(file_path) # Assumes read_file takes absolute or resolvable relative
        if error or content is None:
            self._display_file_content(file_path, f"# Error loading {os.path.basename(file_path)}:\n# {error}", True)
        else:
            # Add to tree as a single item
            item = QTreeWidgetItem(self.file_list_tree)
            item.setText(0, file_path) # Show full path or relative
            item.setData(0, self.FILE_CONTENT_ROLE, content)
            item.setData(0, self.FILE_IS_ERROR_ROLE, False)
            self.file_list_tree.setCurrentItem(item)
            self._generated_file_contents[file_path] = (content, False) # Store it as if it were "generated" for consistency
            self._display_file_content(file_path, content, False)
            self.editor_area.setReadOnly(False) # Allow editing for existing files opened this way
            self.copy_button.setEnabled(True)
            self.save_all_button.setEnabled(False) # 'Save All' is for generated sets
            self.clear_all_button.setEnabled(True)