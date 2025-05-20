# core/code_generation_coordinator.py
import logging
import asyncio
import os
import json  # For type hinting, though it receives parsed dict
import uuid  # For generating unique request IDs
from enum import Enum, auto
from typing import Optional, Dict, Any, List, Tuple

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from utils import constants
from core.llm_manager import LLMManager
from core.file_manager import FileManager
from core.app_settings import AppSettings
from services.code_processing_service import CodeProcessingService
from core.project_manager import ProjectManager

logger = logging.getLogger(constants.APP_NAME)


class GenerationPhase(Enum):
    IDLE = auto()
    PARSING_INSTRUCTIONS = auto()
    GENERATING_FILES = auto()
    # VALIDATING_FILES is now part of the GENERATING_FILES loop for each file
    REFINING_FILES = auto()  # Indicates a specific file is undergoing refinement
    AWAITING_USER_APPROVAL = auto()
    WRITING_FILES = auto()
    COMPLETED = auto()  # Sequence finished, all files attempted
    ERROR = auto()  # A sequence-level error occurred


class FileGenerationStatus(Enum):
    PENDING = auto()
    GENERATING = auto()  # Initial generation attempt
    VALIDATING = auto()  # AST/Ruff check
    REFINING = auto()  # LLM called again to fix errors
    COMPLETED_OK = auto()  # Validated and (if applicable) refined successfully
    FAILED_SYNTAX = auto()
    FAILED_LINTING = auto()  # Syntax OK, but Ruff found issues (might still be usable)
    FAILED_GENERATION = auto()  # LLM error during generation/refinement
    FAILED_MAX_REFINEMENTS = auto()


class FileGenerationState:
    def __init__(self, file_path: str, instructions: str, action: str):
        self.file_path = file_path
        self.instructions = instructions
        self.action = action
        self.generated_content: Optional[str] = None  # Raw from LLM
        self.validated_content: Optional[str] = None  # After AST/Ruff, this is what gets saved
        self.status: FileGenerationStatus = FileGenerationStatus.PENDING
        self.error_message: Optional[str] = None
        self.ast_error: Optional[str] = None
        self.ruff_error: Optional[str] = None
        self.refinement_attempts: int = 0
        self.current_request_id: Optional[str] = None  # Tracks the current LLMManager request ID for this file

    def __repr__(self):
        return f"<FileGenerationState {self.file_path} Status: {self.status.name}>"


class CodeGenerationCoordinator(QObject):
    file_code_generated = pyqtSignal(str, str, bool)
    generation_progress_updated = pyqtSignal(str, int, int)
    generation_sequence_complete = pyqtSignal(str, bool)
    generation_error_occurred = pyqtSignal(str)
    all_files_written_to_disk = pyqtSignal(list)
    file_write_error = pyqtSignal(str, str)

    MAX_REFINEMENT_ATTEMPTS = 1  # Max refinement attempts per file

    def __init__(self,
                 llm_manager: LLMManager,
                 file_manager: FileManager,
                 settings: AppSettings,
                 code_processor: CodeProcessingService,
                 project_manager: ProjectManager,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self.llm_manager = llm_manager
        self.file_manager = file_manager
        self.settings = settings
        self.code_processor = code_processor
        self.project_manager = project_manager

        self._is_active: bool = False
        self._current_overall_phase: GenerationPhase = GenerationPhase.IDLE
        self._current_instructions_json: Optional[Dict[str, Any]] = None
        self._file_states: List[FileGenerationState] = []
        self._current_file_processing_idx: int = -1  # Index in self._file_states
        self._original_request_id: Optional[str] = None
        self._active_llm_request_to_file_map: Dict[str, str] = {}  # Maps LLM request_id to file_path

        self._connect_signals()
        logger.info("CodeGenerationCoordinator initialized with CodeProcessingService and ProjectManager.")

    def _connect_signals(self):
        self.llm_manager.coding_instructions_generated.connect(self.start_generation_sequence)
        self.llm_manager.instruction_generation_failed.connect(self._handle_instruction_generation_failure)
        self.llm_manager.coding_llm_response_received.connect(self._handle_coding_llm_response)

    @property
    def is_active(self) -> bool:
        return self._is_active

    @pyqtSlot(dict, str)
    def start_generation_sequence(self, instructions_json: Dict[str, Any], original_request_id: str):
        if self._is_active:
            logger.warning("CodeGenerationCoordinator is already active. Ignoring new instruction set.")
            self.generation_error_occurred.emit("Coordinator busy with another generation task.")
            return

        logger.info(f"CodeGenerationCoordinator: Starting generation sequence for request_id: {original_request_id}")
        self._is_active = True
        self._current_overall_phase = GenerationPhase.PARSING_INSTRUCTIONS
        self._current_instructions_json = instructions_json
        self._file_states = []
        self._current_file_processing_idx = -1
        self._original_request_id = original_request_id
        self._active_llm_request_to_file_map.clear()
        self.generation_progress_updated.emit("Parsing instructions...", 0, 0)

        try:
            project_goal = self._current_instructions_json.get("project_goal", "N/A")
            files_data = self._current_instructions_json.get("files", [])
            if not isinstance(files_data, list): raise ValueError("'files' key must be a list.")

            for file_entry in files_data:
                if not isinstance(file_entry, dict): continue
                file_path = file_entry.get("file_path")
                action = file_entry.get("action", "create_or_modify")
                instructions = file_entry.get("instructions")
                if not file_path or not instructions: continue
                # Ensure file_path is relative
                if os.path.isabs(file_path):
                    active_project = self.project_manager.get_active_project()
                    if active_project and active_project.path and file_path.startswith(active_project.path):
                        file_path = os.path.relpath(file_path, active_project.path)
                self._file_states.append(FileGenerationState(file_path, instructions, action))

            if not self._file_states:
                self.generation_sequence_complete.emit("No valid files found in instructions to generate.", False)
                self._reset_state();
                return

            logger.info(f"Parsed {len(self._file_states)} files for generation. Project Goal: {project_goal}")
            self.generation_progress_updated.emit(f"Parsed {len(self._file_states)} files. Goal: {project_goal}", 0,
                                                  len(self._file_states))
            self._current_overall_phase = GenerationPhase.GENERATING_FILES
            self._process_next_file_in_sequence()
        except Exception as e:
            logger.exception("Error parsing coding instructions JSON:");
            self.generation_error_occurred.emit(f"Error parsing instructions: {e}");
            self._reset_state()

    def _process_next_file_in_sequence(self):
        if not self._is_active: return
        if self._current_overall_phase not in [GenerationPhase.GENERATING_FILES, GenerationPhase.REFINING_FILES]:
            logger.debug(f"Process next file called in unexpected phase: {self._current_overall_phase}. No action.")
            return

        # Find next PENDING file or a file that FAILED_SYNTAX and needs refinement
        next_file_to_process_idx = -1
        for i in range(len(self._file_states)):
            if self._file_states[i].status == FileGenerationStatus.PENDING:
                next_file_to_process_idx = i
                break
            # If a file failed syntax and can be refined, it might be re-queued implicitly by its error handler
            # This loop is primarily for initial generation.

        if next_file_to_process_idx == -1:  # No more PENDING files
            # Check if all files are in a terminal state (COMPLETED_OK, FAILED_*)
            all_terminal = all(f_state.status not in [FileGenerationStatus.PENDING, FileGenerationStatus.GENERATING,
                                                      FileGenerationStatus.VALIDATING, FileGenerationStatus.REFINING]
                               for f_state in self._file_states)
            if all_terminal:
                logger.info("All files processed or failed. Moving to user approval.")
                self._current_overall_phase = GenerationPhase.AWAITING_USER_APPROVAL
                successful_files = sum(
                    1 for f_state in self._file_states if f_state.status == FileGenerationStatus.COMPLETED_OK)
                total_files = len(self._file_states)
                self.generation_progress_updated.emit(
                    f"All {total_files} files generated/attempted. {successful_files} successful. Awaiting user approval.",
                    total_files, total_files)
            else:
                logger.info("No more PENDING files, but some files are still being processed/refined. Waiting.")
            return

        self._current_file_processing_idx = next_file_to_process_idx
        current_file_state = self._file_states[self._current_file_processing_idx]
        current_file_state.status = FileGenerationStatus.GENERATING
        current_file_state.current_request_id = f"coder_{current_file_state.file_path.replace(os.sep, '_').replace('.', '_')}_{uuid.uuid4().hex[:4]}"
        self._active_llm_request_to_file_map[current_file_state.current_request_id] = current_file_state.file_path

        self.generation_progress_updated.emit(
            f"Generating code for: {current_file_state.file_path} ({self._current_file_processing_idx + 1}/{len(self._file_states)})",
            self._current_file_processing_idx, len(self._file_states))
        existing_code: Optional[str] = None
        active_project = self.project_manager.get_active_project()
        if current_file_state.action != "create" and active_project and active_project.path:
            content_tuple = self.file_manager.read_file(current_file_state.file_path)
            if content_tuple[0] is not None:
                existing_code = content_tuple[0]
            elif current_file_state.action == "modify":
                current_file_state.action = "create"

        asyncio.create_task(self.llm_manager.generate_code_with_coding_llm(
            instructions_for_file=current_file_state.instructions,
            target_file_path=current_file_state.file_path,
            project_id=active_project.id if active_project else None,
            existing_code=existing_code,
            request_id=current_file_state.current_request_id
        ))

    @pyqtSlot(str, str, bool)
    def _handle_coding_llm_response(self, request_id_from_llm: str, content: str, is_error: bool):
        if not self._is_active: return

        target_file_path = self._active_llm_request_to_file_map.get(request_id_from_llm)
        if not target_file_path:
            logger.warning(
                f"Received CodingLLM response for unknown/stale request_id: {request_id_from_llm}. Ignoring.")
            return

        found_state: Optional[FileGenerationState] = None
        for state_idx, state in enumerate(self._file_states):
            if state.file_path == target_file_path and state.current_request_id == request_id_from_llm:
                found_state = state
                self._current_file_processing_idx = state_idx  # Ensure current index matches the responding file
                break

        if not found_state:
            logger.warning(
                f"Could not find FileGenerationState for response (ReqID: {request_id_from_llm}, Path: {target_file_path}).")
            self._process_next_file_in_sequence_after_handling_current()
            return

        # Clear processed request ID
        if found_state.current_request_id in self._active_llm_request_to_file_map:
            del self._active_llm_request_to_file_map[found_state.current_request_id]
        found_state.current_request_id = None

        if is_error:
            found_state.status = FileGenerationStatus.FAILED_GENERATION
            found_state.error_message = content
            logger.error(f"CodingLLM failed for {found_state.file_path}: {content}")
            self.file_code_generated.emit(found_state.file_path, content, True)
            self._process_next_file_in_sequence_after_handling_current()
            return

        found_state.generated_content = content
        found_state.status = FileGenerationStatus.VALIDATING
        self.generation_progress_updated.emit(f"Validating: {found_state.file_path}",
                                              self._file_states.index(found_state), len(self._file_states))
        logger.info(f"CodingLLM generated code for {found_state.file_path}. Starting validation.")
        asyncio.create_task(self._validate_and_process_file_content(found_state))

    async def _validate_and_process_file_content(self, file_state: FileGenerationState):
        if file_state.generated_content is None:
            file_state.status = FileGenerationStatus.FAILED_GENERATION
            file_state.error_message = "No content from LLM for validation."
            self.file_code_generated.emit(file_state.file_path, file_state.error_message, True)
            self._process_next_file_in_sequence_after_handling_current();
            return

        is_valid_syntax, ast_error_msg = await self.code_processor.validate_python_syntax(file_state.generated_content,
                                                                                          file_state.file_path)
        file_state.ast_error = ast_error_msg

        if not is_valid_syntax:
            file_state.error_message = ast_error_msg
            if file_state.refinement_attempts < self.MAX_REFINEMENT_ATTEMPTS:
                file_state.refinement_attempts += 1
                file_state.status = FileGenerationStatus.REFINING
                self._current_overall_phase = GenerationPhase.REFINING_FILES  # Update overall phase
                idx = self._file_states.index(file_state)
                self.generation_progress_updated.emit(
                    f"Syntax error in {file_state.file_path}. Refining ({file_state.refinement_attempts}/{self.MAX_REFINEMENT_ATTEMPTS})...",
                    idx, len(self._file_states))
                await self._request_code_refinement(file_state)
                # After refinement request is sent, _handle_coding_llm_response will take over for this file.
                # We don't call _process_next_file_in_sequence_after_handling_current here.
                return
            else:
                file_state.status = FileGenerationStatus.FAILED_MAX_REFINEMENTS
                logger.error(
                    f"Syntax validation failed for {file_state.file_path} after {file_state.refinement_attempts} attempts: {ast_error_msg}")
                self.file_code_generated.emit(file_state.file_path,
                                              f"Syntax Error (Unfixable):\n{ast_error_msg}\n\n---Original Content---\n{file_state.generated_content}",
                                              True)
                self._process_next_file_in_sequence_after_handling_current();
                return

        idx = self._file_states.index(file_state)
        self.generation_progress_updated.emit(f"Formatting/Linting: {file_state.file_path}", idx,
                                              len(self._file_states))
        formatted_code, ruff_error_msg = await self.code_processor.format_and_lint_code(file_state.generated_content,
                                                                                        file_state.file_path)
        file_state.ruff_error = ruff_error_msg
        file_state.validated_content = formatted_code

        if ruff_error_msg:
            file_state.status = FileGenerationStatus.FAILED_LINTING
            file_state.error_message = (file_state.error_message or "") + f"; Ruff: {ruff_error_msg}"
            logger.warning(f"Ruff processing issues for {file_state.file_path}: {ruff_error_msg}.")
            self.file_code_generated.emit(file_state.file_path,
                                          f"Ruff Issues:\n{ruff_error_msg}\n\n---Validated Code (Pre-Ruff issues)---\n{file_state.validated_content}",
                                          True)
        else:
            file_state.status = FileGenerationStatus.COMPLETED_OK
            logger.info(f"File {file_state.file_path} validated and processed successfully.")
            self.file_code_generated.emit(file_state.file_path, file_state.validated_content, False)

        # Regardless of Ruff outcome (if syntax was OK), move to next file processing.
        self._process_next_file_in_sequence_after_handling_current()

    async def _request_code_refinement(self, file_state: FileGenerationState):
        logger.info(f"Requesting code refinement for {file_state.file_path}, attempt {file_state.refinement_attempts}.")
        # _current_overall_phase is already REFINING_FILES if we got here through AST error path

        refinement_prompt = (
            f"The Python code previously generated for the file '{file_state.file_path}' has a syntax error.\n"
            f"Original Instructions for this file:\n---\n{file_state.instructions}\n---\n"
            f"Error Details:\n{file_state.ast_error}\n\n"
            f"Erroneous Code Snippet (or full if short):\n```python\n{file_state.generated_content[:1000] if file_state.generated_content else ''}...\n```\n\n"
            f"Please regenerate the COMPLETE and CORRECTED raw Python code for '{file_state.file_path}', ensuring it is syntactically valid and adheres to the original instructions. Output ONLY the raw code."
        )

        file_state.current_request_id = f"coder_refine_{file_state.file_path.replace(os.sep, '_').replace('.', '_')}_{uuid.uuid4().hex[:4]}"
        self._active_llm_request_to_file_map[file_state.current_request_id] = file_state.file_path
        file_state.status = FileGenerationStatus.GENERATING  # Set back to GENERATING for this refinement attempt

        active_project = self.project_manager.get_active_project()
        await self.llm_manager.generate_code_with_coding_llm(
            instructions_for_file=refinement_prompt,
            target_file_path=file_state.file_path,
            project_id=active_project.id if active_project else None,
            existing_code=None,
            request_id=file_state.current_request_id
        )

    def _process_next_file_in_sequence_after_handling_current(self):
        """
        Called after a file's generation/validation/refinement attempt cycle is complete
        (either successfully or with failure).
        """
        if self._current_overall_phase == GenerationPhase.REFINING_FILES:
            # If we were refining, it means this file's attempt is done.
            # Switch back to GENERATING_FILES to pick up the next file in the main sequence.
            self._current_overall_phase = GenerationPhase.GENERATING_FILES

        if self._current_overall_phase == GenerationPhase.GENERATING_FILES:
            self._process_next_file_in_sequence()
        # If in AWAITING_USER_APPROVAL or COMPLETED, the main loop is done.

    @pyqtSlot(dict)
    def handle_files_approved_for_saving(self, approved_files_content_map: Dict[str, str]):
        # ... (file saving logic remains the same as previous version) ...
        if not self._is_active or self._current_overall_phase != GenerationPhase.AWAITING_USER_APPROVAL:
            logger.warning("Received file approval when not awaiting or not active. Ignoring.")
            if self._is_active: self.generation_error_occurred.emit("File approval received at an unexpected time.")
            return

        logger.info(f"User approved {len(approved_files_content_map)} files for saving.")
        self._current_overall_phase = GenerationPhase.WRITING_FILES
        # Update progress based on how many files from the original plan are being approved
        # This count might be different from len(self._file_states) if some failed generation
        num_to_write = len(approved_files_content_map)
        self.generation_progress_updated.emit(f"Saving {num_to_write} approved files...",
                                              len(self._file_states),
                                              len(self._file_states))  # Show total files planned

        active_project = self.project_manager.get_active_project()
        if not active_project or not active_project.path:
            self.generation_error_occurred.emit("Cannot save files: No active project path defined.");
            self._current_overall_phase = GenerationPhase.ERROR;
            return

        successfully_written_paths: List[str] = []
        for relative_file_path, content in approved_files_content_map.items():
            # Ensure the path from UI (which is the key in approved_files_content_map)
            # is correctly interpreted as relative by FileManager.
            # Our FileGenerationState.file_path should already be relative.
            logger.debug(f"Attempting to write file: '{relative_file_path}' within project '{active_project.name}'")
            success, error = self.file_manager.write_file(relative_file_path, content, overwrite=True)
            if success:
                full_path = os.path.join(active_project.path, relative_file_path)
                successfully_written_paths.append(full_path)
                logger.info(f"Successfully wrote file: {full_path}")
            else:
                logger.error(f"Failed to write file '{relative_file_path}': {error}")
                self.file_write_error.emit(relative_file_path, error or "Unknown write error")

        if successfully_written_paths:
            self.all_files_written_to_disk.emit(successfully_written_paths)
            final_msg = f"Successfully wrote {len(successfully_written_paths)} files to project '{active_project.name}'."
            if len(successfully_written_paths) < num_to_write:
                final_msg += f" ({num_to_write - len(successfully_written_paths)} files failed to write)."
            self.generation_sequence_complete.emit(final_msg, True)
        else:
            self.generation_sequence_complete.emit(
                "No files were successfully written to disk (all approved files failed).", False)
        self._reset_state()

    @pyqtSlot(str, str)
    def _handle_instruction_generation_failure(self, error_message: str, request_id: str):
        if self._original_request_id == request_id:
            logger.error(f"Instruction generation failed for request {request_id}: {error_message}")
            self.generation_error_occurred.emit(f"Failed to generate coding instructions: {error_message}")
            self._reset_state()

    def cancel_sequence(self):
        if not self._is_active: return
        logger.info("CodeGenerationCoordinator: Cancelling current generation sequence.")
        # TODO: Cancel in-flight LLM requests for _active_llm_request_to_file_map
        self.generation_sequence_complete.emit("Generation cancelled by user.", False)
        self._reset_state()

    def _reset_state(self):
        logger.info("CodeGenerationCoordinator: Resetting state.")
        self._is_active = False
        self._current_overall_phase = GenerationPhase.IDLE
        self._current_instructions_json = None
        self._file_states = []
        self._current_file_processing_idx = -1
        self._original_request_id = None
        self._active_llm_request_to_file_map.clear()