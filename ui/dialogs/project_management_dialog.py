# ui/dialogs/project_management_dialog.py
import logging
import os
from typing import Optional, List, Dict, Tuple

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QFileDialog, QMessageBox,
    QDialogButtonBox, QGroupBox, QFormLayout, QCheckBox, QWidget
)
from PyQt6.QtCore import Qt, pyqtSlot, QSize, pyqtSignal
from PyQt6.QtGui import QIcon

from utils import constants
from core.project_manager import ProjectManager, Project # For type hinting and methods
from core.app_settings import AppSettings # For consistency if needed

logger = logging.getLogger(constants.APP_NAME)

class ProjectManagementDialog(QDialog):
    project_action_completed = pyqtSignal(str) # Emits active project ID after action

    _PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole + 10

    def __init__(self, project_manager: ProjectManager, settings: AppSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project_manager = project_manager
        self.settings = settings # Though might not be directly used, good for consistency

        self.setWindowTitle("Manage Projects")
        self.setMinimumSize(600, 450)
        self.setObjectName("ProjectManagementDialog")

        self._existing_projects_list: Optional[QListWidget] = None
        self._project_name_edit: Optional[QLineEdit] = None
        self._project_path_edit: Optional[QLineEdit] = None
        self._browse_button: Optional[QPushButton] = None
        self._add_create_button: Optional[QPushButton] = None
        self._open_selected_button: Optional[QPushButton] = None
        self._remove_selected_button: Optional[QPushButton] = None
        # self._delete_on_disk_checkbox: Optional[QCheckBox] = None # Future: for remove action

        self._init_ui()
        self._connect_signals()
        self._load_existing_projects()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # Section 1: Existing Projects
        existing_group = QGroupBox("Existing Projects")
        existing_layout = QVBoxLayout(existing_group)

        self._existing_projects_list = QListWidget()
        self._existing_projects_list.setObjectName("ExistingProjectsList")
        self._existing_projects_list.setAlternatingRowColors(True)
        existing_layout.addWidget(self._existing_projects_list)

        existing_buttons_layout = QHBoxLayout()
        self._open_selected_button = QPushButton("Open Selected")
        self._remove_selected_button = QPushButton("Remove Selected")
        existing_buttons_layout.addWidget(self._open_selected_button)
        existing_buttons_layout.addWidget(self._remove_selected_button)
        existing_buttons_layout.addStretch(1)
        existing_layout.addLayout(existing_buttons_layout)
        main_layout.addWidget(existing_group)

        # Section 2: Add or Create New Project
        new_project_group = QGroupBox("Add Existing or Create New Project")
        new_project_form_layout = QFormLayout(new_project_group)

        self._project_name_edit = QLineEdit()
        self._project_name_edit.setPlaceholderText("Project Name (optional, defaults to folder name)")
        new_project_form_layout.addRow("Project Name:", self._project_name_edit)

        path_layout = QHBoxLayout()
        self._project_path_edit = QLineEdit()
        self._project_path_edit.setPlaceholderText("Select or enter project directory path")
        self._browse_button = QPushButton("Browse...")
        path_layout.addWidget(self._project_path_edit, 1)
        path_layout.addWidget(self._browse_button)
        new_project_form_layout.addRow("Project Path:", path_layout)

        self._add_create_button = QPushButton("Add / Create Project")
        new_project_form_layout.addRow(self._add_create_button)
        main_layout.addWidget(new_project_group)

        # Dialog Buttons (Done)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        main_layout.addWidget(self.button_box)

        self.setLayout(main_layout)

    def _connect_signals(self):
        if self._existing_projects_list:
            self._existing_projects_list.itemDoubleClicked.connect(self._handle_open_selected_project)
        if self._open_selected_button:
            self._open_selected_button.clicked.connect(self._handle_open_selected_project)
        if self._remove_selected_button:
            self._remove_selected_button.clicked.connect(self._handle_remove_selected_project)
        if self._browse_button:
            self._browse_button.clicked.connect(self._handle_browse_path)
        if self._add_create_button:
            self._add_create_button.clicked.connect(self._handle_add_create_project)
        if self.button_box:
            self.button_box.rejected.connect(self.reject) # Close button

    def _load_existing_projects(self):
        if not self._existing_projects_list: return
        self._existing_projects_list.clear()
        projects = self.project_manager.get_all_managed_projects() # Assumes this returns List[Project]
        active_project_id = self.project_manager.get_active_project_id()

        for proj in projects:
            item_text = f"{proj.name} ({proj.path})"
            item = QListWidgetItem(item_text)
            item.setData(self._PROJECT_ID_ROLE, proj.id)
            if proj.id == active_project_id:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setIcon(QIcon.fromTheme("folder-open", QIcon(os.path.join(constants.ASSETS_DIR, "folder_open_icon.svg")))) # Example
            else:
                item.setIcon(QIcon.fromTheme("folder", QIcon(os.path.join(constants.ASSETS_DIR, "folder_icon.svg"))))
            self._existing_projects_list.addItem(item)

    @pyqtSlot()
    def _handle_browse_path(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Project Directory",
            self._project_path_edit.text() or os.path.expanduser("~")
        )
        if directory and self._project_path_edit:
            self._project_path_edit.setText(directory)
            if not self._project_name_edit.text(): # Auto-fill name if empty
                self._project_name_edit.setText(os.path.basename(directory))

    @pyqtSlot()
    def _handle_add_create_project(self):
        if not self._project_path_edit or not self._project_name_edit: return

        path = self._project_path_edit.text().strip()
        name = self._project_name_edit.text().strip() or None # None if empty, PM handles default

        if not path:
            QMessageBox.warning(self, "Input Error", "Project path cannot be empty.")
            return

        new_project = self.project_manager.create_or_add_project(path, name)
        if new_project:
            QMessageBox.information(self, "Success", f"Project '{new_project.name}' added/created and activated.")
            self._load_existing_projects() # Refresh list
            self._project_name_edit.clear()
            self._project_path_edit.clear()
            self.project_action_completed.emit(new_project.id)
            # Optionally close dialog: self.accept()
        else:
            # Error message should come from ProjectManager if name/path collision or create error
            QMessageBox.critical(self, "Error",
                                 self.project_manager.get_last_error() or "Failed to add or create project. Check logs.") # Assuming PM has get_last_error()

    @pyqtSlot()
    def _handle_open_selected_project(self):
        selected_items = self._existing_projects_list.selectedItems() if self._existing_projects_list else []
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a project to open.")
            return
        item = selected_items[0]
        project_id = item.data(self._PROJECT_ID_ROLE)
        if project_id:
            self.project_manager.set_active_project_id(project_id)
            self._load_existing_projects() # Refresh to show bold active project
            self.project_action_completed.emit(project_id)
            self.accept() # Close dialog on successful open

    @pyqtSlot()
    def _handle_remove_selected_project(self):
        selected_items = self._existing_projects_list.selectedItems() if self._existing_projects_list else []
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a project to remove.")
            return

        item = selected_items[0]
        project_id = item.data(self._PROJECT_ID_ROLE)
        project_to_remove = self.project_manager.get_project_by_id(project_id)

        if not project_to_remove:
            QMessageBox.critical(self, "Error", "Project not found for removal.")
            return

        reply = QMessageBox.question(self, "Confirm Remove",
                                     f"Are you sure you want to remove '{project_to_remove.name}' from the managed projects list?\n(This does not delete files on disk by default).",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # TODO: Add checkbox for "Delete project files from disk" if desired later
            # delete_on_disk = self._delete_on_disk_checkbox.isChecked() if self._delete_on_disk_checkbox else False
            delete_on_disk = False # For now, just remove from list

            if self.project_manager.remove_project_from_list(project_id, delete_on_disk=delete_on_disk):
                QMessageBox.information(self, "Success", f"Project '{project_to_remove.name}' removed from list.")
                self._load_existing_projects() # Refresh list
                current_active_id = self.project_manager.get_active_project_id()
                self.project_action_completed.emit(current_active_id if current_active_id else "")
            else:
                QMessageBox.critical(self, "Error", "Failed to remove project.")

    def accept(self):
        # Called if "Open Selected" is successful, or could be connected to an "OK" button if added
        super().accept()

    def reject(self):
        # Called by Close button
        super().reject()