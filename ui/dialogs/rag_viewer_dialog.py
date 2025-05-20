# ui/dialogs/rag_viewer_dialog.py
import asyncio
import logging
import os
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QLabel, QFileDialog, QMessageBox, QDialogButtonBox,
    QHeaderView, QProgressDialog, QWidget, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QIcon

from utils import constants
from core.orchestrator import AppOrchestrator
from services.rag_service import RAGService # For type hinting

logger = logging.getLogger(constants.APP_NAME)

class RAGViewerDialog(QDialog):
    _COLLECTION_ID_ROLE = Qt.ItemDataRole.UserRole + 1
    _METADATA_SOURCE_ROLE = Qt.ItemDataRole.UserRole + 2

    def __init__(self, orchestrator: AppOrchestrator, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.rag_service: Optional[RAGService] = orchestrator.get_rag_service()

        self.setWindowTitle("RAG Collection Viewer")
        self.setMinimumSize(800, 600)
        self.setObjectName("RAGViewerDialog")

        self._collections_combo: Optional[QComboBox] = None
        self._collection_info_label: Optional[QLabel] = None
        self._documents_tree: Optional[QTreeWidget] = None

        self._add_file_button: Optional[QPushButton] = None
        self._add_folder_button: Optional[QPushButton] = None
        self._clear_collection_button: Optional[QPushButton] = None
        self._delete_collection_button: Optional[QPushButton] = None
        self._refresh_button: Optional[QPushButton] = None
        self._close_button: Optional[QPushButton] = None

        self._init_ui()
        self._connect_signals()
        self._populate_collections_combo()
        self._update_ui_for_selected_collection()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # Top: Collection Selection and Info
        top_layout = QHBoxLayout()
        self._collections_combo = QComboBox()
        self._collections_combo.setMinimumWidth(250)
        self._collections_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_layout.addWidget(QLabel("Select RAG Collection:"))
        top_layout.addWidget(self._collections_combo, 1)

        self._refresh_button = QPushButton()
        self._refresh_button.setIcon(QIcon.fromTheme("view-refresh", QIcon(os.path.join(constants.ASSETS_DIR, "refresh_icon.svg"))))
        self._refresh_button.setToolTip("Refresh collections list and view")
        top_layout.addWidget(self._refresh_button)
        main_layout.addLayout(top_layout)

        self._collection_info_label = QLabel("Collection Info: N/A")
        self._collection_info_label.setWordWrap(True)
        main_layout.addWidget(self._collection_info_label)

        # Middle: Documents Tree
        self._documents_tree = QTreeWidget()
        self._documents_tree.setObjectName("RAGDocumentsTree")
        self._documents_tree.setColumnCount(3) # Filename, Chunks, Entities
        self._documents_tree.setHeaderLabels(["Source Document", "Chunks", "Code Entities"])
        self._documents_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._documents_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self._documents_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self._documents_tree.setColumnWidth(1, 80)
        self._documents_tree.setColumnWidth(2, 150)
        main_layout.addWidget(self._documents_tree, 1)

        # Bottom: Action Buttons
        action_buttons_layout = QHBoxLayout()
        self._add_file_button = QPushButton("Add File(s)")
        self._add_folder_button = QPushButton("Add Folder")
        self._clear_collection_button = QPushButton("Clear Collection")
        self._delete_collection_button = QPushButton("Delete Collection")

        action_buttons_layout.addWidget(self._add_file_button)
        action_buttons_layout.addWidget(self._add_folder_button)
        action_buttons_layout.addStretch(1)
        action_buttons_layout.addWidget(self._clear_collection_button)
        action_buttons_layout.addWidget(self._delete_collection_button)
        main_layout.addLayout(action_buttons_layout)

        # Dialog Buttons (Close)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._close_button = self.button_box.button(QDialogButtonBox.StandardButton.Close)
        main_layout.addWidget(self.button_box)

        self.setLayout(main_layout)

    def _connect_signals(self):
        if self._collections_combo:
            self._collections_combo.currentIndexChanged.connect(self._on_collection_selected)
        if self._refresh_button:
            self._refresh_button.clicked.connect(self._refresh_all_views)
        if self._add_file_button:
            self._add_file_button.clicked.connect(self._handle_add_files)
        if self._add_folder_button:
            self._add_folder_button.clicked.connect(self._handle_add_folder)
        if self._clear_collection_button:
            self._clear_collection_button.clicked.connect(self._handle_clear_collection)
        if self._delete_collection_button:
            self._delete_collection_button.clicked.connect(self._handle_delete_collection)
        if self.button_box:
            self.button_box.rejected.connect(self.reject) # Close button

    def _populate_collections_combo(self):
        if not self.rag_service or not self._collections_combo:
            return

        self._collections_combo.blockSignals(True)
        self._collections_combo.clear()
        collections = self.rag_service.get_displayable_collections()

        active_project = self.orchestrator.get_project_manager().get_active_project()
        active_project_coll_id = None
        if active_project:
            active_project_coll_id = self.rag_service._get_project_rag_collection_id(active_project.id)

        selected_index = -1
        for i, coll_info in enumerate(collections):
            self._collections_combo.addItem(coll_info["name"], coll_info["raw_id"])
            if active_project_coll_id and coll_info["raw_id"] == active_project_coll_id:
                selected_index = i
            elif not active_project_coll_id and coll_info["raw_id"] == constants.GLOBAL_RAG_COLLECTION_ID and selected_index == -1:
                selected_index = i # Default to global if no active project match

        if selected_index != -1:
            self._collections_combo.setCurrentIndex(selected_index)
        elif self._collections_combo.count() > 0:
            self._collections_combo.setCurrentIndex(0)

        self._collections_combo.blockSignals(False)
        self._on_collection_selected(self._collections_combo.currentIndex()) # Trigger update for initially selected

    def _get_selected_collection_id(self) -> Optional[str]:
        if self._collections_combo and self._collections_combo.currentIndex() >= 0:
            return self._collections_combo.currentData()
        return None

    @pyqtSlot(int)
    def _on_collection_selected(self, index: int):
        self._update_ui_for_selected_collection()

    def _update_ui_for_selected_collection(self):
        if not self.rag_service or not self._documents_tree or not self._collection_info_label:
            return

        collection_id = self._get_selected_collection_id()
        self._documents_tree.clear()

        is_global_collection = (collection_id == constants.GLOBAL_RAG_COLLECTION_ID)
        # Delete and Clear buttons should be disabled for global, or enabled if other collection.
        if self._delete_collection_button:
            self._delete_collection_button.setEnabled(not is_global_collection and collection_id is not None)
        if self._clear_collection_button:
            self._clear_collection_button.setEnabled(collection_id is not None)
        if self._add_file_button:
            self._add_file_button.setEnabled(collection_id is not None)
        if self._add_folder_button:
            self._add_folder_button.setEnabled(collection_id is not None)


        if not collection_id:
            self._collection_info_label.setText("No RAG collection selected.")
            return

        coll_size = self.rag_service.vector_db_service.get_collection_size(collection_id)
        self._collection_info_label.setText(f"Collection: {self._collections_combo.currentText()} ({collection_id})\n"
                                            f"Total Chunks/Embeddings: {coll_size}")

        all_metadata = self.rag_service.vector_db_service.get_all_metadata(collection_id)
        if not all_metadata:
            self._documents_tree.addTopLevelItem(QTreeWidgetItem(["No documents found in this collection."]))
            return

        # Group chunks by source document
        docs_summary: Dict[str, Dict[str, Any]] = {}
        for meta_item in all_metadata:
            source_path = meta_item.get("source", "Unknown Source")
            if source_path not in docs_summary:
                docs_summary[source_path] = {"chunk_count": 0, "entities": set()}
            docs_summary[source_path]["chunk_count"] += 1
            entities_in_chunk = meta_item.get("code_entities", [])
            if isinstance(entities_in_chunk, list):
                docs_summary[source_path]["entities"].update(entities_in_chunk)

        for source_path, summary in sorted(docs_summary.items()):
            display_name = os.path.basename(source_path)
            item = QTreeWidgetItem([
                display_name,
                str(summary["chunk_count"]),
                ", ".join(sorted(list(summary["entities"])))[:100] # Display first 100 chars of entities
            ])
            item.setToolTip(0, source_path) # Full path as tooltip
            item.setData(0, self._METADATA_SOURCE_ROLE, source_path)
            self._documents_tree.addTopLevelItem(item)

    @pyqtSlot()
    def _refresh_all_views(self):
        self._populate_collections_combo() # This will also trigger _update_ui_for_selected_collection

    def _derive_semantic_project_id(self, rag_collection_id: Optional[str]) -> Optional[str]:
        if not rag_collection_id:
            return None
        if rag_collection_id == constants.GLOBAL_RAG_COLLECTION_ID:
            return constants.GLOBAL_RAG_COLLECTION_ID # Explicitly global for RAG service
        if rag_collection_id.startswith("project_") and rag_collection_id.endswith("_rag"):
            return rag_collection_id[len("project_"):-len("_rag")] # The project UUID
        logger.warning(f"Could not derive semantic project ID from RAG collection ID: {rag_collection_id}")
        return None # Or handle as an error / default to global


    async def _process_files_for_rag(self, file_paths: List[str], semantic_project_id: Optional[str]):
        if not self.rag_service or not file_paths:
            return

        progress_dialog = QProgressDialog("Processing files for RAG...", "Cancel", 0, len(file_paths), self)
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setMinimumDuration(1000) # Only show if takes > 1 sec
        progress_dialog.setValue(0)
        QApplication.processEvents()

        success_count = 0
        failure_count = 0
        error_msgs: List[str] = []

        for i, file_path in enumerate(file_paths):
            if progress_dialog.wasCanceled():
                logger.info("RAG file processing cancelled by user.")
                break
            progress_dialog.setLabelText(f"Processing: {os.path.basename(file_path)} ({i+1}/{len(file_paths)})")

            added, msg = await self.rag_service.add_file_to_rag(file_path, project_id=semantic_project_id)
            if added:
                success_count += 1
            else:
                failure_count += 1
                error_msgs.append(f"{os.path.basename(file_path)}: {msg}")
            progress_dialog.setValue(i + 1)
            QApplication.processEvents() # Keep UI responsive

        progress_dialog.close()

        summary_message = f"RAG Processing Complete for '{self._collections_combo.currentText()}'.\n"
        summary_message += f"Successfully added: {success_count} file(s).\n"
        if failure_count > 0:
            summary_message += f"Failed to add: {failure_count} file(s).\n"
            summary_message += "Errors:\n" + "\n".join(f"- {e}" for e in error_msgs[:5]) # Show first 5 errors
            if len(error_msgs) > 5: summary_message += f"\n...and {len(error_msgs)-5} more errors (see log)."
            QMessageBox.warning(self, "RAG Processing Issues", summary_message)
        else:
            QMessageBox.information(self, "RAG Processing Complete", summary_message)

        self._update_ui_for_selected_collection() # Refresh view

    async def _process_folder_for_rag(self, folder_path: str, semantic_project_id: Optional[str]):
        if not self.rag_service or not folder_path:
            return

        self.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        info_msg_box = QMessageBox(QMessageBox.Icon.Information, "Processing Folder",
                                   f"Processing folder '{os.path.basename(folder_path)}' for RAG collection '{self._collections_combo.currentText()}'. This may take some time...",
                                   QMessageBox.StandardButton.NoButton, self)
        info_msg_box.setWindowModality(Qt.WindowModality.WindowModal)
        info_msg_box.show()
        QApplication.processEvents()

        try:
            success_count, failure_count, error_msgs = await self.rag_service.add_folder_to_rag(folder_path, project_id=semantic_project_id)
        finally:
            info_msg_box.close()
            QApplication.restoreOverrideCursor()
            self.setEnabled(True)


        summary_message = f"RAG Folder Processing Complete for '{self._collections_combo.currentText()}'.\n"
        summary_message += f"Successfully added: {success_count} file(s) from folder.\n"
        if failure_count > 0:
            summary_message += f"Failed/Skipped: {failure_count} file(s).\n"
            if error_msgs:
                summary_message += "Errors/Reasons:\n" + "\n".join(f"- {e}" for e in error_msgs[:5])
                if len(error_msgs) > 5: summary_message += f"\n...and {len(error_msgs)-5} more (see log)."
            QMessageBox.warning(self, "RAG Folder Processing Issues", summary_message)
        else:
            QMessageBox.information(self, "RAG Folder Processing Complete", summary_message)

        self._update_ui_for_selected_collection()


    @pyqtSlot()
    def _handle_add_files(self):
        rag_collection_id = self._get_selected_collection_id() # This is the RAG store ID
        if not rag_collection_id:
            QMessageBox.warning(self, "No Collection", "Please select a RAG collection first.")
            return

        semantic_project_id = self._derive_semantic_project_id(rag_collection_id)
        # If semantic_project_id is None here and it's not the global collection,
        # it implies an issue with collection ID format or an orphaned RAG store.
        # RAGService.add_file_to_rag will default to active project or global if semantic_project_id is None.

        file_dialog = QFileDialog(self, "Select Files to Add to RAG")
        allowed_ext_str = " ".join(f"*{ext}" for ext in constants.ALLOWED_TEXT_EXTENSIONS if ext not in ['.pdf', '.docx'])
        pdf_ext_str = "*.pdf"
        docx_ext_str = "*.docx"
        filter_str = f"Supported Text Files ({allowed_ext_str});;PDF Documents ({pdf_ext_str});;Word Documents ({docx_ext_str});;All Files (*)"

        file_dialog.setNameFilter(filter_str)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)

        if file_dialog.exec():
            file_paths = file_dialog.selectedFiles()
            if file_paths:
                asyncio.create_task(self._process_files_for_rag(file_paths, semantic_project_id))

    @pyqtSlot()
    def _handle_add_folder(self):
        rag_collection_id = self._get_selected_collection_id() # This is the RAG store ID
        if not rag_collection_id:
            QMessageBox.warning(self, "No Collection", "Please select a RAG collection first.")
            return

        semantic_project_id = self._derive_semantic_project_id(rag_collection_id)

        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder to Add to RAG")
        if folder_path:
            asyncio.create_task(self._process_folder_for_rag(folder_path, semantic_project_id))


    @pyqtSlot()
    def _handle_clear_collection(self):
        collection_id = self._get_selected_collection_id()
        if not collection_id:
            QMessageBox.warning(self, "No Collection", "Please select a RAG collection to clear.")
            return

        reply = QMessageBox.question(self, "Confirm Clear",
                                     f"Are you sure you want to clear all content from the RAG collection '{self._collections_combo.currentText()}'?\nThis action cannot be undone.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.rag_service and self.rag_service.clear_rag_collection(collection_id):
                QMessageBox.information(self, "Success", f"Collection '{self._collections_combo.currentText()}' cleared.")
                self._update_ui_for_selected_collection()
            else:
                QMessageBox.critical(self, "Error", f"Failed to clear collection '{self._collections_combo.currentText()}'.")

    @pyqtSlot()
    def _handle_delete_collection(self):
        collection_id = self._get_selected_collection_id()
        if not collection_id:
            QMessageBox.warning(self, "No Collection", "Please select a RAG collection to delete.")
            return

        if collection_id == constants.GLOBAL_RAG_COLLECTION_ID:
            QMessageBox.warning(self, "Action Not Allowed", "The Global RAG collection cannot be deleted.")
            return

        reply = QMessageBox.question(self, "Confirm Delete",
                                     f"Are you sure you want to delete the RAG collection '{self._collections_combo.currentText()}'?\nThis action cannot be undone and will remove its data from disk.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.rag_service and self.rag_service.delete_rag_collection(collection_id):
                QMessageBox.information(self, "Success", f"Collection '{self._collections_combo.currentText()}' deleted.")
                self._populate_collections_combo() # Refresh list and selection
            else:
                QMessageBox.critical(self, "Error", f"Failed to delete collection '{self._collections_combo.currentText()}'.")

    def accept(self): # Override if needed, e.g. for Apply button
        super().accept()

    def reject(self):
        super().reject()