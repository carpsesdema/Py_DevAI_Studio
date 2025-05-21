# core/upload_coordinator.py
import asyncio
import logging
import os
from typing import List, Optional, Callable, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal

try:
    from .models import ChatMessage, SYSTEM_ROLE, ERROR_ROLE
    from services.upload_service import UploadService
    from .project_context_manager import ProjectContextManager
    from utils import constants

    # Conditional import for ProjectSummaryCoordinator for type hinting
    if TYPE_CHECKING:
        from .project_summary_coordinator import ProjectSummaryCoordinator
except ImportError as e:
    logging.critical(f"UploadCoordinator: Failed to import critical dependencies: {e}")
    ChatMessage = type("ChatMessage", (object,), {})  # type: ignore
    UploadService = type("UploadService", (object,), {})  # type: ignore
    ProjectContextManager = type("ProjectContextManager", (object,), {})  # type: ignore
    constants = type("constants", (object,), {"GLOBAL_COLLECTION_ID": "global_collection"})  # type: ignore
    SYSTEM_ROLE, ERROR_ROLE = "system", "error"  # type: ignore
    if TYPE_CHECKING:
        ProjectSummaryCoordinator = type("ProjectSummaryCoordinator", (object,), {})  # type: ignore

logger = logging.getLogger(__name__)


class UploadCoordinator(QObject):
    upload_started = pyqtSignal(bool, str)
    upload_summary_received = pyqtSignal(ChatMessage)
    upload_error = pyqtSignal(str)
    busy_state_changed = pyqtSignal(bool)

    def __init__(self,
                 upload_service: UploadService,
                 project_context_manager: ProjectContextManager,
                 project_summary_coordinator: Optional['ProjectSummaryCoordinator'],
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        if not upload_service:
            raise ValueError("UploadCoordinator requires a valid UploadService instance.")
        if not project_context_manager:
            raise ValueError("UploadCoordinator requires a valid ProjectContextManager instance.")

        self._upload_service = upload_service
        self._project_context_manager = project_context_manager
        self._project_summary_coordinator = project_summary_coordinator
        self._current_upload_task: Optional[asyncio.Task] = None
        self._is_busy: bool = False

        if self._project_summary_coordinator:
            logger.info("UploadCoordinator initialized with ProjectSummaryCoordinator (for manual summaries).")
        else:
            logger.warning(
                "UploadCoordinator initialized WITHOUT ProjectSummaryCoordinator. Manual summary command will not function.")
        logger.info("UploadCoordinator initialized.")

    def _set_busy(self, busy: bool):
        if self._is_busy != busy:
            self._is_busy = busy
            self.busy_state_changed.emit(self._is_busy)
        logger.debug(f"UploadCoordinator busy state set to: {self._is_busy}")

    async def _internal_process_upload(
            self,
            upload_func: Callable[[], Optional[ChatMessage]],
            operation_description: str,
            target_collection_id: Optional[str] = None,
            num_items_for_upload: int = 0
    ):
        logger.info(f"UploadCoordinator: Starting async task for: {operation_description}")
        summary_message: Optional[ChatMessage] = None
        try:
            summary_message = await asyncio.to_thread(upload_func)
        except asyncio.CancelledError:
            logger.info(f"Upload task '{operation_description}' cancelled by request.")
            summary_message = ChatMessage(role=SYSTEM_ROLE, parts=["[Upload cancelled by user.]"],
                                          metadata={"is_cancellation_summary": True,
                                                    "collection_id": target_collection_id or "unknown"})
        except Exception as e:
            logger.exception(f"Error during upload task '{operation_description}': {e}")
            self.upload_error.emit(f"Failed during {operation_description}: {e}")
            summary_message = ChatMessage(role=ERROR_ROLE, parts=[f"Upload Error for {operation_description}: {e}"],
                                          metadata={"is_error_summary": True,
                                                    "collection_id": target_collection_id or "unknown"})
        finally:
            if self._current_upload_task is asyncio.current_task():
                self._current_upload_task = None
            self._set_busy(False)
            if summary_message:
                self.upload_summary_received.emit(summary_message)
            logger.info(f"UploadCoordinator: Async task for '{operation_description}' finished.")

    def _initiate_upload(self,
                         upload_callable: Callable[[], Optional[ChatMessage]],
                         description: str,
                         is_global: bool,
                         item_info: str,
                         target_collection_id_for_summary: Optional[str] = None,
                         num_items_for_upload: int = 0
                         ):
        if self._is_busy:
            logger.warning("UploadCoordinator is already busy. Ignoring new upload request.")
            self.upload_error.emit("Upload processor busy. Please wait.")
            return

        self._set_busy(True)
        self.upload_started.emit(is_global, item_info)

        self._current_upload_task = asyncio.create_task(
            self._internal_process_upload(
                upload_callable,
                description,
                target_collection_id=target_collection_id_for_summary,
                num_items_for_upload=num_items_for_upload
            )
        )

    def upload_files_to_current_project(self, file_paths: List[str]):
        if not file_paths: return
        active_project_id = self._project_context_manager.get_active_project_id() or constants.GLOBAL_COLLECTION_ID
        logger.info(f"UploadCoordinator: Request to upload {len(file_paths)} files to project '{active_project_id}'.")
        upload_callable = lambda: self._upload_service.process_files_for_context(file_paths,
                                                                                 collection_id=active_project_id)
        description = f"uploading {len(file_paths)} files to '{active_project_id}'"
        self._initiate_upload(
            upload_callable,
            description,
            is_global=(active_project_id == constants.GLOBAL_COLLECTION_ID),
            item_info=f"{len(file_paths)} file(s)",
            target_collection_id_for_summary=active_project_id,
            num_items_for_upload=len(file_paths)
        )

    def upload_directory_to_current_project(self, dir_path: str):
        if not dir_path: return
        active_project_id = self._project_context_manager.get_active_project_id() or constants.GLOBAL_COLLECTION_ID
        dir_name = os.path.basename(dir_path)
        logger.info(f"UploadCoordinator: Request to upload directory '{dir_name}' to project '{active_project_id}'.")
        upload_callable = lambda: self._upload_service.process_directory_for_context(dir_path,
                                                                                     collection_id=active_project_id)
        description = f"uploading directory '{dir_name}' to '{active_project_id}'"
        self._initiate_upload(
            upload_callable,
            description,
            is_global=(active_project_id == constants.GLOBAL_COLLECTION_ID),
            item_info=f"directory '{dir_name}'",
            target_collection_id_for_summary=active_project_id,
            num_items_for_upload=1  # Represents one directory operation
        )

    def upload_files_to_global(self, file_paths: List[str]):
        if not file_paths: return
        logger.info(f"UploadCoordinator: Request to upload {len(file_paths)} files to GLOBAL context.")
        upload_callable = lambda: self._upload_service.process_files_for_context(file_paths,
                                                                                 collection_id=constants.GLOBAL_COLLECTION_ID)
        description = f"uploading {len(file_paths)} files to GLOBAL"
        self._initiate_upload(
            upload_callable,
            description,
            is_global=True,
            item_info=f"{len(file_paths)} file(s)",
            target_collection_id_for_summary=constants.GLOBAL_COLLECTION_ID,
            num_items_for_upload=len(file_paths)
        )

    def upload_directory_to_global(self, dir_path: str):
        if not dir_path: return
        dir_name = os.path.basename(dir_path)
        logger.info(f"UploadCoordinator: Request to upload directory '{dir_name}' to GLOBAL context.")
        upload_callable = lambda: self._upload_service.process_directory_for_context(dir_path,
                                                                                     collection_id=constants.GLOBAL_COLLECTION_ID)
        description = f"uploading directory '{dir_name}' to GLOBAL"
        self._initiate_upload(
            upload_callable,
            description,
            is_global=True,
            item_info=f"directory '{dir_name}'",
            target_collection_id_for_summary=constants.GLOBAL_COLLECTION_ID,
            num_items_for_upload=1
        )

    # --- NEW METHOD for RAG Resynchronization ---
    def resync_file_in_rag(self, project_id: str, file_path: str):
        """
        Re-synchronizes a single file in the RAG by removing its old chunks
        and re-processing the new content. This is non-blocking and uses the
        same async upload mechanism.

        Args:
            project_id: The ID of the project/collection.
            file_path: The absolute path to the file to be re-synced.
        """
        if self._is_busy:
            logger.warning(
                f"UploadCoordinator busy. RAG resync for '{os.path.basename(file_path)}' in project '{project_id}' queued/ignored.")
            # Optionally, queue this or emit an error/status update.
            # For now, just log and return if busy to prevent concurrent _internal_process_upload issues.
            self.upload_error.emit(f"Cannot resync '{os.path.basename(file_path)}' now, processor is busy.")
            return

        if not project_id or not file_path:
            logger.error("Cannot resync RAG: Invalid project_id or file_path.")
            self.upload_error.emit("Invalid parameters for RAG resync.")
            return

        if not os.path.exists(file_path):
            logger.error(f"Cannot resync RAG: File '{file_path}' does not exist.")
            self.upload_error.emit(f"File for RAG resync not found: {os.path.basename(file_path)}")
            return

        logger.info(f"UploadCoordinator: Initiating RAG resync for file '{file_path}' in project '{project_id}'.")

        # Define the callable for the internal upload process
        def _resync_operation():
            logger.info(f"[Resync Task] Removing old chunks for '{file_path}' from '{project_id}'.")
            # Access VectorDBService via UploadService (assuming UploadService has a getter or direct access)
            vdb_service = getattr(self._upload_service, '_vector_db_service', None)
            if not vdb_service:
                logger.error(
                    "[Resync Task] VectorDBService not accessible via UploadService. Cannot remove old chunks.")
                return ChatMessage(role=ERROR_ROLE, parts=[
                    f"[Error: RAG resync for {os.path.basename(file_path)} failed (DB service missing)."],
                                   metadata={"collection_id": project_id})

            remove_success = vdb_service.remove_document_chunks_by_source(project_id, file_path)
            if not remove_success:
                logger.warning(
                    f"[Resync Task] Failed to remove all old chunks for '{file_path}' from '{project_id}'. Re-adding may result in duplicates or stale data.")
                # Continue to re-add, but log the warning.

            logger.info(f"[Resync Task] Re-processing and adding new content for '{file_path}' to '{project_id}'.")
            # process_files_for_context will return a ChatMessage summary
            return self._upload_service.process_files_for_context([file_path], collection_id=project_id)

        # Use the existing _initiate_upload mechanism
        description = f"resyncing file '{os.path.basename(file_path)}' in RAG for project '{project_id}'"
        self._initiate_upload(
            upload_callable=_resync_operation,
            description=description,
            is_global=(project_id == constants.GLOBAL_COLLECTION_ID),
            item_info=f"file '{os.path.basename(file_path)}' (resync)",
            target_collection_id_for_summary=project_id,
            num_items_for_upload=1  # Single file operation
        )
        # The upload_summary_received signal will be emitted by _internal_process_upload
        # once _resync_operation (which calls process_files_for_context) completes.

    # --- END NEW METHOD ---

    def cancel_current_upload(self):
        if self._current_upload_task and not self._current_upload_task.done():
            logger.info("UploadCoordinator: Cancelling ongoing upload task...")
            self._current_upload_task.cancel()
            logger.debug("Cancellation requested for upload task.")
        else:
            logger.debug("UploadCoordinator: No active upload task to cancel.")
            if self._is_busy: self._set_busy(False)  # Ensure busy state is reset if task was already done

    def is_busy(self) -> bool:
        return self._is_busy