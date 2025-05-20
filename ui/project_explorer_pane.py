import logging
import os
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeView, QFileSystemModel, QMenu, QMessageBox, QSizePolicy
)
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtCore import Qt, QDir, pyqtSlot, QPoint, pyqtSignal, QModelIndex

from utils import constants
from core.orchestrator import AppOrchestrator
from core.project_manager import Project  # For type hinting

logger = logging.getLogger(constants.APP_NAME)


class ProjectExplorerPane(QWidget):
    file_selected_for_editing = pyqtSignal(str)  # Emits absolute file path
    create_new_file_requested = pyqtSignal(str)  # Emits directory path where file should be created
    create_new_folder_requested = pyqtSignal(str)  # Emits parent directory path
    delete_item_requested = pyqtSignal(str)  # Emits absolute path of item to delete
    refresh_explorer_requested = pyqtSignal()

    def __init__(self, orchestrator: AppOrchestrator, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.setObjectName("ProjectExplorerPane")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self.tree_view: Optional[QTreeView] = None
        self.model: Optional[QFileSystemModel] = None

        self._current_project_root: Optional[str] = None

        self._init_ui()
        self._connect_signals()
        logger.info("ProjectExplorerPane initialized.")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tree_view = QTreeView()
        self.tree_view.setObjectName("ProjectFileTree")
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setAnimated(False)  # Set to True for smoother expand/collapse if preferred
        self.tree_view.setIndentation(15)
        self.tree_view.setSortingEnabled(True)
        self.tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.model = QFileSystemModel()
        self.model.setRootPath(QDir.rootPath())  # Set a default root path initially
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)

        # Example: Hide .git, __pycache__, etc.
        # This needs to be more dynamic based on project settings or global ignores
        name_filters = ["*.pyc", "*.pyo", "*.pyd", ".DS_Store"]
        # self.model.setNameFilters(name_filters)
        # self.model.setNameFilterDisables(False) # True = hide, False = gray out

        self.tree_view.setModel(self.model)

        # Hide unnecessary columns (Type, Size, Date Modified)
        self.tree_view.setColumnHidden(1, True)
        self.tree_view.setColumnHidden(2, True)
        self.tree_view.setColumnHidden(3, True)
        self.tree_view.setHeaderHidden(True)  # Hide header if only name is shown

        layout.addWidget(self.tree_view)
        self.setLayout(layout)

    def _connect_signals(self) -> None:
        if self.tree_view:
            self.tree_view.doubleClicked.connect(self._handle_item_double_clicked)
            self.tree_view.customContextMenuRequested.connect(self._show_context_menu)

        # Connect to project manager signals if needed, e.g., when active project changes
        # This is handled by MainWindow which calls load_project_by_id

    def load_project_by_id(self, project_id: Optional[str]) -> None:
        if not self.orchestrator or not self.orchestrator.get_project_manager() or not self.model:
            logger.error("ProjectExplorerPane: Orchestrator or model not available for loading project.")
            return

        if not project_id:
            self.model.setRootPath(QDir.rootPath())  # Or some default "no project" view
            self.tree_view.setRootIndex(self.model.index(QDir.rootPath()))
            self._current_project_root = None
            logger.info("ProjectExplorerPane: No project ID provided, cleared view.")
            return

        project = self.orchestrator.get_project_manager().get_project_by_id(project_id)
        if project and project.path and os.path.isdir(project.path):
            self._current_project_root = project.path
            root_index = self.model.setRootPath(project.path)
            self.tree_view.setRootIndex(root_index)
            self.tree_view.scrollTo(root_index)  # Ensure root is visible
            self.tree_view.expand(root_index)  # Optionally expand the root
            logger.info(f"ProjectExplorerPane: Loaded project '{project.name}' at path '{project.path}'.")
        else:
            self.model.setRootPath(QDir.homePath())  # Fallback if project path invalid
            self.tree_view.setRootIndex(self.model.index(QDir.homePath()))
            self._current_project_root = None
            logger.warning(
                f"ProjectExplorerPane: Project '{project_id}' path invalid or not found. Displaying home directory.")

    @pyqtSlot(QModelIndex)
    def _handle_item_double_clicked(self, index: QModelIndex) -> None:
        if not self.model: return
        file_path = self.model.filePath(index)
        if self.model.isDir(index):
            if self.tree_view.isExpanded(index):
                self.tree_view.collapse(index)
            else:
                self.tree_view.expand(index)
        elif os.path.isfile(file_path):
            self.file_selected_for_editing.emit(file_path)

    @pyqtSlot(QPoint)
    def _show_context_menu(self, position: QPoint) -> None:
        if not self.tree_view or not self.model: return

        index = self.tree_view.indexAt(position)
        file_path = self.model.filePath(index) if index.isValid() else self._current_project_root

        if not file_path:  # If no item selected and no project root, context menu on empty space
            return

        menu = QMenu(self.tree_view)

        if index.isValid() and self.model.isDir(index):
            target_dir_path = file_path
        elif index.isValid() and not self.model.isDir(index):  # It's a file
            target_dir_path = os.path.dirname(file_path)
        elif not index.isValid() and self._current_project_root:  # Right-click on empty space within project
            target_dir_path = self._current_project_root
        else:  # No valid target for new file/folder
            target_dir_path = None

        if target_dir_path:
            new_file_action = menu.addAction(QIcon.fromTheme("document-new", QIcon()), "New File...")
            new_file_action.triggered.connect(lambda: self.create_new_file_requested.emit(target_dir_path))

            new_folder_action = menu.addAction(QIcon.fromTheme("folder-new", QIcon()), "New Folder...")
            new_folder_action.triggered.connect(lambda: self.create_new_folder_requested.emit(target_dir_path))
            menu.addSeparator()

        if index.isValid():  # Actions for a selected item
            open_action = menu.addAction(QIcon.fromTheme("document-open", QIcon()), "Open")
            open_action.triggered.connect(lambda: self._handle_item_double_clicked(index))  # Re-use double click logic

            if not self.model.isDir(index):  # Only for files
                # Add more file-specific actions if needed
                pass

            menu.addSeparator()
            delete_action = menu.addAction(QIcon.fromTheme("edit-delete", QIcon()), "Delete")
            delete_action.triggered.connect(lambda: self._confirm_and_delete_item(file_path))

        refresh_action = menu.addAction(QIcon.fromTheme("view-refresh", QIcon()), "Refresh")
        refresh_action.triggered.connect(self._refresh_view)

        if menu.actions():
            menu.exec(self.tree_view.viewport().mapToGlobal(position))

    def _confirm_and_delete_item(self, path_to_delete: str) -> None:
        if not path_to_delete: return
        item_name = os.path.basename(path_to_delete)
        is_dir = os.path.isdir(path_to_delete)
        item_type = "directory" if is_dir else "file"

        reply = QMessageBox.question(self, f"Confirm Delete",
                                     f"Are you sure you want to delete the {item_type} '{item_name}'?\nThis action cannot be undone.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_item_requested.emit(path_to_delete)
            # View will be refreshed by orchestrator/file_manager if delete is successful

    @pyqtSlot()
    def _refresh_view(self) -> None:
        if self.model and self._current_project_root:
            self.model.setRootPath("")  # Force refresh by temporarily unsetting
            self.model.setRootPath(self._current_project_root)
            self.tree_view.setRootIndex(self.model.index(self._current_project_root))
            logger.info(f"ProjectExplorerPane refreshed for path: {self._current_project_root}")
        elif self.model:  # No project root, refresh default view
            current_root = self.model.rootPath()
            self.model.setRootPath("")
            self.model.setRootPath(current_root if current_root else QDir.rootPath())
            self.tree_view.setRootIndex(self.model.index(current_root if current_root else QDir.rootPath()))
            logger.info(f"ProjectExplorerPane refreshed for default path: {current_root}")

        self.refresh_explorer_requested.emit()

    def set_item_filter(self, filters: List[str]) -> None:
        if self.model:
            self.model.setNameFilters(filters)
            self.model.setNameFilterDisables(False)  # True hides, False grays out

    def clear_filter(self) -> None:
        if self.model:
            self.model.setNameFilters([])