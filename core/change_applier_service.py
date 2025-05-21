# core/change_applier_service.py
import logging
import os
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

# Assuming these services are importable
try:
    from services.file_handler_service import FileHandlerService
    from core.upload_coordinator import UploadCoordinator # To trigger RAG resync
    # from core.project_context_manager import ProjectContextManager # Might need for resolving paths if not fully done by MC
except ImportError as e:
    logging.critical(f"ChangeApplierService: Failed to import dependencies: {e}")
    FileHandlerService = type("FileHandlerService", (object,), {})
    UploadCoordinator = type("UploadCoordinator", (object,), {})
    # ProjectContextManager = type("ProjectContextManager", (object,), {})

logger = logging.getLogger(__name__)

class ChangeApplierService(QObject):
    """
    Handles the application of AI-generated file changes:
    1. Writes the new content to the local file system.
    2. Triggers RAG resynchronization for the updated file.
    """
    file_applied_successfully = pyqtSignal(str, str)  # project_id, absolute_file_path
    file_application_failed = pyqtSignal(str, str, str) # project_id, relative_file_path, error_message
    rag_sync_initiated = pyqtSignal(str, str) # project_id, absolute_file_path
    rag_sync_failed = pyqtSignal(str, str, str) # project_id, absolute_file_path, error_message (currently UC doesn't emit this directly for resync)

    def __init__(self,
                 file_handler_service: FileHandlerService,
                 upload_coordinator: UploadCoordinator,
                 # project_context_manager: ProjectContextManager, # Optional, if path resolution needs more context here
                 parent: Optional[QObject] = None):
        super().__init__(parent)

        if not file_handler_service or not upload_coordinator: # or not project_context_manager:
            err = "ChangeApplierService requires FileHandlerService and UploadCoordinator."
            logger.critical(err)
            raise ValueError(err)

        self._file_handler = file_handler_service
        self._upload_coordinator = upload_coordinator
        # self._pcm = project_context_manager
        logger.info("ChangeApplierService initialized.")

    def apply_file_change(self,
                          project_id: str,
                          relative_file_path: str, # Path as known by ModificationCoordinator (e.g., relative to focus_prefix)
                          new_content: str,
                          focus_prefix: Optional[str]): # The focus_prefix MC was using
        """
        Applies the new content to the specified file and triggers RAG resync.

        Args:
            project_id: The ID of the current AvA project.
            relative_file_path: The relative path of the file to be modified/created.
            new_content: The new content to write to the file.
            focus_prefix: The base path (project root or focus directory) against which
                          the relative_file_path should be resolved.
        """
        logger.info(f"CAS: Attempting to apply changes to '{relative_file_path}' in project '{project_id}' with focus_prefix '{focus_prefix}'.")

        if not project_id or not relative_file_path:
            logger.error("CAS: Missing project_id or relative_file_path.")
            self.file_application_failed.emit(project_id or "unknown", relative_file_path or "unknown", "Missing project or file identifier.")
            return

        # 1. Resolve the absolute file path
        # This logic mirrors what ModificationCoordinator._read_original_file_content does for path resolution
        absolute_file_path: Optional[str] = None
        norm_relative_path = os.path.normpath(relative_file_path)

        if focus_prefix and os.path.isdir(focus_prefix):
            absolute_file_path = os.path.abspath(os.path.join(focus_prefix, norm_relative_path))
            logger.debug(f"CAS: Resolved path using focus_prefix: '{absolute_file_path}'")
        elif os.path.isabs(norm_relative_path):
            absolute_file_path = norm_relative_path
            logger.debug(f"CAS: Using relative_file_path as absolute: '{absolute_file_path}'")
        else:
            # This case should ideally be rare if focus_prefix is always provided for modifications.
            # If not, we might need to fetch project root from PCM or error.
            err_msg = f"Cannot determine absolute path for '{relative_file_path}'. Focus prefix missing or invalid."
            logger.error(f"CAS: {err_msg}")
            self.file_application_failed.emit(project_id, relative_file_path, err_msg)
            return

        if not absolute_file_path: # Should be caught above, but defensive check
            self.file_application_failed.emit(project_id, relative_file_path, "Failed to resolve absolute file path.")
            return

        # 2. Write the file using FileHandlerService
        write_success, write_error = self._file_handler.write_file_content(absolute_file_path, new_content)

        if not write_success:
            err_msg = f"Failed to write file '{os.path.basename(absolute_file_path)}': {write_error}"
            logger.error(f"CAS: {err_msg}")
            self.file_application_failed.emit(project_id, relative_file_path, err_msg)
            return

        logger.info(f"CAS: Successfully wrote file '{absolute_file_path}'.")
        self.file_applied_successfully.emit(project_id, absolute_file_path)

        # 3. Trigger RAG resynchronization via UploadCoordinator
        # Ensure UploadCoordinator is not busy before calling.
        # If it is busy, this becomes a bit more complex (queueing, user notification).
        # For now, let's assume we can call it. UC already has a busy check.
        if self._upload_coordinator.is_busy():
            warn_msg = f"RAG resync for '{os.path.basename(absolute_file_path)}' delayed: UploadCoordinator is busy."
            logger.warning(f"CAS: {warn_msg}")
            # We might want to emit a specific signal here or queue it.
            # For now, the file is saved, but RAG isn't immediately updated.
            # This could lead to stale RAG if user immediately queries about the change.
            # A simple approach is to just inform the user via a status update.
            self.rag_sync_failed.emit(project_id, absolute_file_path, "UploadCoordinator busy, RAG sync deferred/failed.") # Improvise a signal
        else:
            logger.info(f"CAS: Requesting RAG resync for '{absolute_file_path}' in project '{project_id}'.")
            self._upload_coordinator.resync_file_in_rag(project_id, absolute_file_path)
            self.rag_sync_initiated.emit(project_id, absolute_file_path)
            # Note: UploadCoordinator will emit its own signals about the upload/resync process.
            # This service just signals that it *initiated* the RAG sync.