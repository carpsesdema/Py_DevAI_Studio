# core/modification_coordinator.py
import logging
import ast
import re
import os
import asyncio
import uuid

from typing import List, Optional, Dict, Any, Tuple

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer

# --- MODIFIED: Ensure FileHandlerService is imported ---
from services.file_handler_service import FileHandlerService
# --- END MODIFIED ---

from .modification_handler import ModificationHandler
from .backend_coordinator import BackendCoordinator
from .project_context_manager import ProjectContextManager
from .rag_handler import RagHandler
from .models import ChatMessage, USER_ROLE, SYSTEM_ROLE, ERROR_ROLE
from utils import constants

try:
    from services.llm_communication_logger import LlmCommunicationLogger

    MC_LLM_COMM_LOGGER_AVAILABLE = True
except ImportError:
    LlmCommunicationLogger = None
    MC_LLM_COMM_LOGGER_AVAILABLE = False
    logging.error("ModificationCoordinator: Failed to import LlmCommunicationLogger.")

logger = logging.getLogger(__name__)

PLANNER_BACKEND_ID = getattr(constants, "PLANNER_BACKEND_ID", "gemini_planner")
GENERATOR_BACKEND_ID = getattr(constants, "GENERATOR_BACKEND_ID", "ollama_generator")
RAG_SNIPPET_COUNT_FOR_CODER = 2
RAG_MAX_SNIPPET_LENGTH = 500  # Characters, not lines

MAX_CONCURRENT_GENERATORS = 3


class ModPhase:
    IDLE = "IDLE"
    AWAITING_PLAN_AND_ALL_CODER_INSTRUCTIONS = "AWAITING_PLAN_AND_ALL_CODER_INSTRUCTIONS"
    GENERATING_CODE_CONCURRENTLY = "GENERATING_CODE_CONCURRENTLY"
    ALL_FILES_GENERATED_AWAITING_USER_ACTION = "ALL_FILES_GENERATED_AWAITING_USER_ACTION"


class ModificationCoordinator(QObject):
    request_llm_call = pyqtSignal(str, list)
    file_ready_for_display = pyqtSignal(str, str)
    modification_sequence_complete = pyqtSignal(str, str, dict)
    modification_error = pyqtSignal(str)
    status_update = pyqtSignal(str)
    code_generation_started = pyqtSignal()

    MAX_LINES_BEFORE_SPLIT = 400
    # --- NEW: Max file size to send full content to Planner LLM ---
    MAX_FILE_SIZE_FOR_FULL_PLANNER_CONTEXT_KB = 50  # Kilobytes

    def __init__(self,
                 modification_handler: ModificationHandler,
                 backend_coordinator: BackendCoordinator,
                 project_context_manager: ProjectContextManager,
                 rag_handler: RagHandler,
                 llm_comm_logger: Optional[LlmCommunicationLogger] = None,
                 parent: Optional[QObject] = None):
        super().__init__(parent)

        if not all([modification_handler, backend_coordinator, project_context_manager, rag_handler]):
            logger.critical("MC Init: Missing critical dependencies (incl. RagHandler).")
            raise ValueError(
                "ModificationCoordinator requires valid handler, backend_coord, project_manager, and rag_handler.")

        self._handler = modification_handler
        self._backend_coordinator = backend_coordinator
        self._project_context_manager = project_context_manager
        self._rag_handler = rag_handler
        self._llm_comm_logger = llm_comm_logger
        # --- NEW: Instantiate FileHandlerService ---
        self._file_handler_service = FileHandlerService()
        # --- END NEW ---

        if self._llm_comm_logger:
            logger.info("ModificationCoordinator initialized with LlmCommunicationLogger.")
        else:
            logger.warning(
                "ModificationCoordinator initialized WITHOUT LlmCommunicationLogger. Terminal logging will be limited.")

        self._is_active: bool = False
        self._is_awaiting_llm: bool = False
        self._current_phase: str = ModPhase.IDLE
        self._original_query: Optional[str] = None
        self._original_query_at_start: Optional[str] = None
        self._original_context_from_rag: Optional[str] = None
        self._original_focus_prefix: Optional[str] = None

        self._full_planner_output_text: Optional[str] = None
        self._coder_instructions_map: Dict[str, str] = {}
        self._generated_file_data: Dict[str, Tuple[Optional[str], Optional[str]]] = {}  # content, error_msg
        self._planned_files_list: List[str] = []  # List of relative file paths
        self._active_code_generation_tasks: Dict[str, asyncio.Task] = {}

        # --- NEW: Store for original file contents ---
        self._original_file_contents: Dict[str, Optional[str]] = {}  # {relative_path: content_or_none_if_not_found}
        # --- END NEW ---
        # --- NEW: Store for identified target files from user query ---
        self._identified_target_files_from_query: List[str] = []
        # --- END NEW ---
        # --- NEW: Flag to distinguish bootstrap from modification ---
        self._is_modification_of_existing: bool = False
        # --- END NEW ---

        self._connect_handler_signals()

    def _connect_handler_signals(self):
        if self._handler:
            try:
                self._handler.modification_parsing_error.connect(self._handle_mh_parsing_error)
            except Exception as e:
                logger.exception(f"Error connecting ModificationHandler signals in MC: {e}")

    def _reset_state(self):
        self._is_active = False
        self._is_awaiting_llm = False
        self._current_phase = ModPhase.IDLE
        self._original_query = None
        self._original_query_at_start = None
        self._original_context_from_rag = None
        self._original_focus_prefix = None

        self._full_planner_output_text = None
        self._coder_instructions_map = {}
        self._generated_file_data = {}
        self._planned_files_list = []

        # --- NEW: Reset new state variables ---
        self._original_file_contents = {}
        self._identified_target_files_from_query = []
        self._is_modification_of_existing = False
        # --- END NEW ---

        for task_key, task in list(self._active_code_generation_tasks.items()):
            if task and not task.done():
                task.cancel()
        self._active_code_generation_tasks = {}

        if self._handler:
            self._handler.cancel_modification()

    def is_active(self) -> bool:
        return self._is_active

    def is_awaiting_llm_response(self) -> bool:
        return self._is_active and self._is_awaiting_llm

    # --- MODIFIED: This is now primarily for bootstrapping new projects ---
    def start_sequence_for_bootstrap(self, query: str, context_from_rag: str, focus_prefix: str):
        """Starts a sequence to bootstrap a NEW application."""
        if self._is_active:
            logger.info("MC: Sequence already active, resetting and starting new bootstrap.")
            if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Process]",
                                                                        "Previous sequence reset. Starting new bootstrap sequence.")
            self._reset_state()

        self._is_active = True
        if self._handler: # MC activates MH
            self._handler.activate_sequence()
        self.code_generation_started.emit()
        if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Process]", "Bootstrap sequence started.")

        self._original_query = query
        self._original_query_at_start = query
        self._original_context_from_rag = context_from_rag
        self._original_focus_prefix = focus_prefix  # Usually empty for bootstrap but can be set
        self._is_awaiting_llm = False
        self._is_modification_of_existing = False  # Mark as bootstrap
        self._identified_target_files_from_query = []  # No pre-identified files for bootstrap
        self._original_file_contents = {}  # No original files for bootstrap

        self._request_plan_and_coder_instructions()

    # --- NEW: Method to start modification of existing files ---
    def start_sequence_for_modification(self,
                                        query: str,
                                        identified_target_files: List[str],
                                        context_from_rag: str,
                                        focus_prefix: str):
        """Starts a sequence to MODIFY EXISTING files."""
        if self._is_active:
            logger.info("MC: Sequence already active, resetting and starting new modification.")
            if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Process]",
                                                                        "Previous sequence reset. Starting new modification sequence.")
            self._reset_state()

        self._is_active = True
        if self._handler: # MC activates MH
            self._handler.activate_sequence()
        self.code_generation_started.emit()
        if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Process]",
                                                                    "Modification sequence for existing files started.")

        self._original_query = query
        self._original_query_at_start = query
        self._original_context_from_rag = context_from_rag
        self._original_focus_prefix = focus_prefix
        self._is_awaiting_llm = False
        self._is_modification_of_existing = True  # Mark as modification
        self._identified_target_files_from_query = identified_target_files
        self._original_file_contents = {}  # Reset for this sequence

        # Fetch original content for identified files
        if self._identified_target_files_from_query:
            self.status_update.emit(
                f"[System: Reading content for {len(self._identified_target_files_from_query)} specified file(s)...]")
            for rel_path in self._identified_target_files_from_query:
                content = self._read_original_file_content(rel_path)  # This method handles path resolution
                self._original_file_contents[rel_path] = content  # Store content or None
                if content is None:
                    logger.warning(f"MC: Could not read original content for target file: {rel_path}")
                    if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Warning]",
                                                                                f"Original content for '{rel_path}' not found/readable. Planner will be informed.")
                else:
                    logger.info(
                        f"MC: Successfully read original content for target file: {rel_path} (Length: {len(content)})")

        # If no files were identified by UIP, the planner might still identify them.
        # The planner prompt will need to be robust to this.

        self._request_plan_and_coder_instructions()

    # --- END NEW ---

    # --- RENAMED from _request_initial_plan_and_all_coder_instructions ---
    # --- MODIFIED: This method now handles both bootstrap and modification based on _is_modification_of_existing ---
    def _request_plan_and_coder_instructions(self):
        """
        Requests the plan (FILES_TO_MODIFY list) and per-file Coder AI instructions
        from the Planner LLM. Adapts prompt based on whether it's a bootstrap or modification.
        """
        prompt_text_parts = [
            "You are an expert AI system planner. Your task is to prepare a plan and detailed instructions for a separate Coder AI "
        ]
        if self._is_modification_of_existing:
            prompt_text_parts.append("to MODIFY existing files or create new ones as part of a modification request.\n")
        else:  # Bootstrap
            prompt_text_parts.append("to IMPLEMENT a user's request for a NEW application or script(s).\n")

        prompt_text_parts.append(
            "Your response MUST be structured exactly as follows, with NO conversational text outside of this structure.\n\n")

        if self._current_phase == ModPhase.ALL_FILES_GENERATED_AWAITING_USER_ACTION and self._original_query != self._original_query_at_start:
            # This is a refinement pass
            prompt_text_parts.append(
                f"This is a REFINEMENT. Original Goal: \"{self._original_query_at_start}\". User Feedback: \"{self._original_query}\". "
                f"Re-evaluate ALL files and Coder AI instructions based on this feedback. Ensure generated file paths are relative to any specified project root.\n\n"
            )
        else:  # Initial request (bootstrap or modification)
            prompt_text_parts.append(f"USER REQUEST: \"{self._original_query_at_start}\"\n\n")

        prompt_text_parts.extend([
            f"ASSOCIATED PROJECT CONTEXT (from RAG, if any):\n{self._original_context_from_rag or 'N/A'}\n\n",
            f"PROJECT ROOT FOCUS (base path for relative file paths, if provided by user or inferred from project):\n{self._original_focus_prefix or 'N/A'}\n\n",
        ])

        # --- NEW: Add info about identified target files and their original content for MODIFICATION ---
        if self._is_modification_of_existing:
            if self._identified_target_files_from_query:
                prompt_text_parts.append(
                    f"USER-IDENTIFIED TARGET FILES (and their original content if found/small enough):\n"
                )
                for rel_path in self._identified_target_files_from_query:
                    content = self._original_file_contents.get(rel_path)
                    prompt_text_parts.append(f"- File: `{rel_path}`\n")
                    if content is not None:
                        content_kb = len(content.encode('utf-8')) / 1024
                        if content_kb <= self.MAX_FILE_SIZE_FOR_FULL_PLANNER_CONTEXT_KB:
                            prompt_text_parts.append(
                                f"  Original Content:\n  ```python_original_for_planner\n{content}\n  ```\n")
                        else:
                            prompt_text_parts.append(
                                f"  Original Content: (Too large to include fully - {content_kb:.1f}KB. Use RAG context or summarize if needed for your plan.)\n")
                    else:
                        prompt_text_parts.append(
                            f"  Original Content: (Not found or could not be read. If your plan involves this file, assume it might need to be created or verify its existence based on other context.)\n")
                prompt_text_parts.append("\n")
            else:
                prompt_text_parts.append(
                    "USER-IDENTIFIED TARGET FILES: None explicitly mentioned in the query. You may need to identify target files based on the request and context.\n\n")
        # --- END NEW ---

        prompt_text_parts.extend([
            "**CRITICAL OUTPUT STRUCTURE:**\n\n",
            "**PART 1: FILES_TO_MODIFY**\n"
            "FILES_TO_MODIFY: ['path/to/file1.ext', 'path/to/file2.ext', ...]\n"
            "(This line MUST start EXACTLY with 'FILES_TO_MODIFY: ' followed by a Python-style list of relative file paths. Use forward slashes. If no files, use []. This MUST be the first part of your response after any initial preamble like 'USER REQUEST: ...')\n\n",
            "**PART 2: PER_FILE_CODER_INSTRUCTIONS**\n"
            "For EACH file listed in FILES_TO_MODIFY, provide a section formatted EXACTLY like this:\n\n"
            "--- CODER_INSTRUCTIONS_START: path/to/filename.ext ---\n"
            "File Purpose: [Briefly describe the file's role and purpose.]\n"
        ])

        # --- NEW: Adapt "Is New File" instruction based on context ---
        if self._is_modification_of_existing:
            prompt_text_parts.append(
                "Is New File: [State 'Yes' if this file needs to be newly created as part of the modification. State 'No' if you are instructing the Coder AI to UPDATE an existing file (even if original content was not found/provided, assume it's an update if the plan intends to modify a conceptually existing file).]\n"
            )
        else:  # Bootstrap
            prompt_text_parts.append(
                "Is New File: [State 'Yes' as this is for a new project/script. All files will be new.]\n"
            )
        # --- END NEW ---

        prompt_text_parts.extend([
            "Key Requirements:\n"
            "- [Detailed natural language instruction 1 for the Coder AI for THIS file. Describe WHAT to do, not HOW to code it. E.g., 'Create a function `my_func` that takes `arg1` (string) and `arg2` (int) and returns their concatenation.']\n"
            "- [Detailed natural language instruction 2 for the Coder AI for THIS file.]\n"
            "- ... more instructions ...\n"
            "Imports Needed: [Suggest imports, e.g., 'import os', 'from .utils import helper_func'.]\n"
            "Interactions: [Describe how this file interacts with other planned files, if applicable.]\n"
            "RAG Context Request: [Optional: Include `[RAG_EXAMPLES_REQUESTED_FOR_THIS_FILE]` if RAG snippets would be helpful for the Coder AI for THIS file.]\n"
            "IMPORTANT CODER OUTPUT FORMAT: Your response for this file (`path/to/filename.ext`) MUST be ONLY ONE single standard Markdown fenced code block, starting with ```python path/to/filename.ext\\n and ending with ```. ABSOLUTELY NO other text, explanations, or conversational fluff anywhere in your response.\n"
            "--- CODER_INSTRUCTIONS_END: path/to/filename.ext ---\n\n"
            "(Repeat the above ---START--- to ---END--- block for EACH file in the FILES_TO_MODIFY list.)\n\n",
            "**Overall Production Quality Standards for Coder AI (You do not need to repeat this, it's a global instruction for the Coder AI that will be passed on):**\n"
            "All generated Python code must adhere to PEP 8 (max line length 99 characters), include type hints (PEP 484), comprehensive docstrings (PEP 257), and inline comments for complex logic. Code must be modular, functional, and correct.\n\n",
            "Provide your complete structured response now."
        ])
        prompt_text = "".join(prompt_text_parts)

        self._full_planner_output_text = None
        self._coder_instructions_map = {}

        history_for_llm = [ChatMessage(role=USER_ROLE, parts=[prompt_text])]
        self._is_awaiting_llm = True
        self._current_phase = ModPhase.AWAITING_PLAN_AND_ALL_CODER_INSTRUCTIONS

        status_msg_for_ui = "[System: Asking Planner AI to create modification plan and coder instructions...]"
        self.status_update.emit(status_msg_for_ui)

        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[System]", "Sending request to Planner AI...")
            if len(prompt_text) < 2000:  # Increased limit for more context
                self._llm_comm_logger.log_message("[Planner AI Req Full Prompt]", prompt_text)
            else:
                self._llm_comm_logger.log_message("[Planner AI Req Summary]",
                                                  f"Prompt length: {len(prompt_text)}, starts with: '{prompt_text[:200]}...'")

        self.request_llm_call.emit(PLANNER_BACKEND_ID, history_for_llm)

    # --- END RENAMED/MODIFIED ---

    def _extract_text_between_markers(self, text: str, start_marker: str, end_marker: str) -> Optional[str]:
        # ... (remains the same)
        try:
            start_idx_find = text.find(start_marker)
            if start_idx_find == -1:
                raise ValueError(f"Start marker '{start_marker}' not found (exact).")

            start_idx = start_idx_find + len(start_marker)
            end_idx_find = text.find(end_marker, start_idx)
            if end_idx_find == -1:
                raise ValueError(f"End marker '{end_marker}' not found after start marker '{start_marker}'.")

            return text[start_idx:end_idx_find].strip()
        except ValueError as ve:
            return None
        except Exception as e:
            return None

    def _handle_plan_response(self, planner_response_text: str):
        # ... (logic to parse FILES_TO_MODIFY and CODER_INSTRUCTIONS remains largely the same) ...
        # Key change: If a file from _original_file_contents is NOT in the Planner's FILES_TO_MODIFY list,
        # we might log a warning or note that the Planner chose not to modify it.
        self._is_awaiting_llm = False
        self._full_planner_output_text = planner_response_text.strip()

        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[Planner AI Res]",
                                              f"Received plan. Length: {len(self._full_planner_output_text)}. Parsing...")
            if len(self._full_planner_output_text) < 2000:
                self._llm_comm_logger.log_message("[Planner AI Res Full]", self._full_planner_output_text)

        parsed_files_list, error_msg_parse_files = self._parse_files_to_modify_list(self._full_planner_output_text)
        if error_msg_parse_files or parsed_files_list is None:
            err_msg_ui = f"Failed to parse FILES_TO_MODIFY list from Planner AI: {error_msg_parse_files}. Response preview: '{planner_response_text[:300] if planner_response_text else '[EMPTY RESPONSE]'}...'"
            self.modification_error.emit(err_msg_ui)
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[System Error]",
                                                  f"Failed to parse FILES_TO_MODIFY list: {error_msg_parse_files}")
            self._handle_sequence_end("error_plan_parsing", err_msg_ui, {})
            return

        self._planned_files_list = parsed_files_list
        if not self._planned_files_list:
            self.status_update.emit("[System: Planner AI indicates no file modifications are needed.]")
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[Planner AI]", "Plan indicates no files need modification.")
            self._handle_sequence_end("completed_no_files_in_plan", "Planner found no files to modify.", {})
            return

        # --- NEW: Log if planner ignored user-identified files ---
        if self._is_modification_of_existing and self._identified_target_files_from_query:
            user_files_set = set(self._identified_target_files_from_query)
            planner_files_set = set(self._planned_files_list)
            ignored_by_planner = user_files_set - planner_files_set
            if ignored_by_planner:
                msg = f"Planner AI did not include the following user-identified files in its plan: {', '.join(ignored_by_planner)}"
                logger.warning(f"MC: {msg}")
                self.status_update.emit(f"[System Warning: {msg}]")
                if self._llm_comm_logger: self._llm_comm_logger.log_message("[Planner AI Warning]", msg)
        # --- END NEW ---

        files_str_display = ", ".join([f"`{f}`" for f in self._planned_files_list])
        self.status_update.emit(f"[System: Planner AI will process: {files_str_display}]")
        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[Planner AI]", f"Planned files: {files_str_display}")

        self._coder_instructions_map = {}
        all_instructions_extracted = True
        current_search_pos = 0

        for filename_in_list in self._planned_files_list:
            normalized_filename_for_marker = filename_in_list.replace("\\", "/")
            start_marker = f"--- CODER_INSTRUCTIONS_START: {normalized_filename_for_marker} ---"
            end_marker = f"--- CODER_INSTRUCTIONS_END: {normalized_filename_for_marker} ---"
            instruction_text = None
            try:
                start_idx_find = self._full_planner_output_text.find(start_marker, current_search_pos)
                if start_idx_find == -1:
                    logger.warning(
                        f"Could not find start marker '{start_marker}' for '{filename_in_list}' after position {current_search_pos}.")
                    pass
                else:
                    start_idx_content = start_idx_find + len(start_marker)
                    end_idx_find = self._full_planner_output_text.find(end_marker, start_idx_content)
                    if end_idx_find == -1:
                        logger.warning(
                            f"Could not find end marker '{end_marker}' for '{filename_in_list}' after start marker.")
                        pass
                    else:
                        instruction_text = self._full_planner_output_text[start_idx_content:end_idx_find].strip()
                        current_search_pos = end_idx_find + len(end_marker)
            except Exception as e_extract:
                logger.error(f"Error during marker extraction for {filename_in_list}: {e_extract}")
                pass

            if instruction_text:
                self._coder_instructions_map[filename_in_list] = instruction_text
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[Planner AI]",
                                                      f"Extracted coder instructions for: {filename_in_list} (Length: {len(instruction_text)})")
            else:
                err_instr_msg = f"[Error: Planner failed to provide Coder AI instructions for {filename_in_list} using exact markers. Please check Planner AI output formatting.]"
                self._coder_instructions_map[filename_in_list] = err_instr_msg
                all_instructions_extracted = False
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Error]",
                                                      f"Failed to extract coder instructions for: {filename_in_list}. Markers might be missing/malformed.")

        if not all_instructions_extracted or len(self._coder_instructions_map) != len(self._planned_files_list):
            if all(val.startswith("[Error:") for val in self._coder_instructions_map.values()):
                self.modification_error.emit(
                    "Planner AI failed to provide valid instructions for ANY of the planned files. Cannot proceed. Check LLM Log for Planner output.")
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Error]",
                                                      "Planner AI failed to provide valid instructions for ANY planned files. Sequence cannot proceed.")
                self._handle_sequence_end("error_no_valid_coder_instructions",
                                          "No valid Coder AI instructions received.", {})
                return
            else:
                self.modification_error.emit(
                    "Planner AI failed to provide instructions for some planned files (check LLM Log). Those files may be skipped or incomplete.")
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Warning]",
                                                      "Planner AI failed to provide instructions for SOME planned files. Proceeding with available ones.")

        self._generated_file_data = {}
        if not any(val and not val.startswith("[Error:") for val in self._coder_instructions_map.values()):
            self.modification_error.emit(
                "Planner AI did not provide any valid Coder AI instructions for any file. Check LLM Log.")
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[System Error]",
                                                  "No valid Coder AI instructions found for any file after parsing. Sequence cannot proceed.")
            self._handle_sequence_end("error_no_valid_coder_instructions_after_check",
                                      "No valid Coder AI instructions for any file.", {})
            return

        self._current_phase = ModPhase.GENERATING_CODE_CONCURRENTLY
        QTimer.singleShot(0, lambda: asyncio.create_task(self._process_all_files_concurrently()))

    async def _get_rag_snippets_for_coder(self, filename: str, coder_instruction_for_file: str) -> str:
        # ... (remains the same)
        if "[RAG_EXAMPLES_REQUESTED_FOR_THIS_FILE]" not in coder_instruction_for_file:
            return ""

        if not self._rag_handler:
            logger.warning(f"RAG examples requested for {filename}, but RagHandler is not available.")
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[System Warning]",
                                                  f"RAG examples requested for {filename}, but RagHandler unavailable.")
            return ""

        active_project_id = self._project_context_manager.get_active_project_id() if self._project_context_manager else None
        if not active_project_id:
            logger.warning(f"RAG examples requested for {filename}, but no active project ID.")
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[System Warning]",
                                                  f"RAG examples requested for {filename}, but no active project ID.")
            return ""

        query_for_rag = f"Relevant code examples for implementing: {filename}. Key aspects: {coder_instruction_for_file[:200]}"

        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[RAG Query]",
                                              f"Fetching examples for {filename}. Query: '{query_for_rag[:100]}...'")

        try:
            focus_paths_for_rag = [
                os.path.join(self._original_focus_prefix, filename)] if self._original_focus_prefix else [filename]

            context_str, _ = self._rag_handler.get_formatted_context(
                query=query_for_rag,
                query_entities=self._rag_handler.extract_code_entities(coder_instruction_for_file),
                project_id=active_project_id,
                focus_paths=focus_paths_for_rag,
                is_modification_request=True
            )

            if not context_str or context_str.startswith("[Error retrieving RAG context]"):
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[RAG Result]",
                                                      f"No relevant examples found or error for {filename}.")
                return ""

            snippets = []
            # Adjusted regex to be more flexible with snippet headers
            code_block_pattern = re.compile(
                r"--- Snippet \d+ from `(.*?)`(?:.*?Collection:.*?)?.*?---\s*```(?:python|.*?)\s*(.*?)\s*```",
                re.DOTALL | re.IGNORECASE)
            matches = code_block_pattern.finditer(context_str)

            extracted_count = 0
            for match in matches:
                if extracted_count >= RAG_SNIPPET_COUNT_FOR_CODER:
                    break
                original_path = match.group(1)
                code_content = match.group(2).strip()
                if len(code_content) > RAG_MAX_SNIPPET_LENGTH:  # Check against character length
                    # Find a good place to truncate (e.g., nearest newline before limit)
                    # This is a simple truncation, could be smarter
                    truncate_at = code_content.rfind('\n', 0, RAG_MAX_SNIPPET_LENGTH)
                    if truncate_at == -1 or truncate_at < RAG_MAX_SNIPPET_LENGTH // 2:  # if no newline or too early
                        truncate_at = RAG_MAX_SNIPPET_LENGTH
                    code_content = code_content[:truncate_at] + "\n# ... (snippet truncated due to length) ..."

                snippets.append(f"Example from `{original_path}`:\n```python\n{code_content}\n```\n")
                extracted_count += 1

            if snippets:
                result_str = "\n--- RELEVANT CODE EXAMPLES FROM KNOWLEDGE BASE ---\n" + "\n".join(
                    snippets) + "--- END OF RELEVANT CODE EXAMPLES ---\n\n"
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[RAG Result]", f"Found {len(snippets)} examples for {filename}.")
                return result_str
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[RAG Result]",
                                                  f"No usable snippets extracted for {filename}, though context was retrieved.")
            return ""
        except Exception as e:
            logger.exception(f"Error getting RAG snippets for {filename}: {e}")
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[RAG Error]", f"Error fetching examples for {filename}: {e}")
            return ""

    # --- MODIFIED: _execute_single_code_generation_task ---
    async def _execute_single_code_generation_task(self, filename: str) -> Tuple[str, Optional[str], Optional[str]]:
        coder_instruction_for_file = self._coder_instructions_map.get(filename)
        if not coder_instruction_for_file or coder_instruction_for_file.startswith("[Error:"):
            return filename, None, coder_instruction_for_file or "Missing Coder AI instructions."

        rag_examples_str = await self._get_rag_snippets_for_coder(filename, coder_instruction_for_file)
        coder_instruction_for_file = coder_instruction_for_file.replace("[RAG_EXAMPLES_REQUESTED_FOR_THIS_FILE]",
                                                                        "").strip()

        # --- NEW: Get original content for this specific file ---
        # Use the relative filename as the key, as stored during start_sequence_for_modification
        original_file_content = self._original_file_contents.get(filename)
        # --- END NEW ---

        final_coder_prompt_parts = [
            f"You are an expert Python Coder AI. Your task is to generate or update the file `{filename}` based "
            f"on the following detailed instructions. Pay EXTREMELY close attention to all requirements, "
            f"especially the **CRITICAL OUTPUT FORMAT REMINDER** contained within the instructions for this file.\n\n"
        ]
        if rag_examples_str:
            final_coder_prompt_parts.append(rag_examples_str)

        # --- MODIFIED: Determine if it's a new file based on Planner instructions AND original content ---
        # The Planner's "Is New File: Yes/No" is a strong hint.
        # If Planner says "No" (update), but we couldn't find original content, Coder should still try to update conceptually or create if truly missing.
        # If Planner says "Yes" (new), but we *did* find original content (e.g. user mistake or plan change), Coder should be told to overwrite or treat as new.

        is_new_file_from_planner_instr = "is new file: yes" in coder_instruction_for_file.lower()

        if self._is_modification_of_existing:  # This task is part of modifying an existing project
            if original_file_content is not None:  # We found original content for this specific file
                if is_new_file_from_planner_instr:
                    # Planner wants a new file, but we found one. This is a conflict.
                    # For now, let's trust the planner's "new file" instruction but inform the Coder.
                    logger.warning(
                        f"Planner indicated '{filename}' as new, but original content was found. Instructing Coder to treat as new/overwrite.")
                    if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Warning]",
                                                                                f"Planner marked '{filename}' as new, but it exists. Coder will treat as new/overwrite.")
                    final_coder_prompt_parts.append(
                        f"The file `{filename}` is to be treated as NEW or an OVERWRITE, even if existing content was found locally. "
                        f"Create it from scratch based on the instructions below.\n\n"
                    )
                else:  # Planner says "No" (update) AND we have original content. This is the standard update case.
                    final_coder_prompt_parts.append(
                        f"The file `{filename}` **EXISTS**. Its current content is:\n"
                        f"```python_original_for_coder\n{original_file_content}\n```\n\n"
                        f"You MUST use this original content as the foundation and apply the necessary modifications "
                        f"as detailed in the instructions below. Preserve all unchanged original code.\n\n"
                    )
            else:  # Original content not found for this specific file during a modification sequence
                if is_new_file_from_planner_instr:  # Planner wants a new file, and we didn't find one. Good.
                    final_coder_prompt_parts.append(
                        f"The file `{filename}` is NEW (Is New File: Yes). Create it from scratch based on the instructions below.\n\n"
                    )
                else:  # Planner said "No" (update), but we didn't find original content.
                    # Instruct Coder to create it as if it were new, but based on update instructions.
                    logger.info(
                        f"File '{filename}' planned as update, but no original content found. Coder will treat as new based on update instructions.")
                    if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Info]",
                                                                                f"File '{filename}' planned as update, but no original content. Coder to create based on update instructions.")
                    final_coder_prompt_parts.append(
                        f"The file `{filename}` was planned as an UPDATE (Is New File: No), but no original content was found. "
                        f"Therefore, create this file as if it were new, following the instructions below which describe the desired state.\n\n"
                    )
        else:  # This is a bootstrap sequence (all files are new)
            final_coder_prompt_parts.append(
                f"The file `{filename}` is NEW (Is New File: Yes, part of a new project bootstrap). Create it from scratch based on the instructions below.\n\n"
            )
        # --- END MODIFIED ---

        final_coder_prompt_parts.extend([
            "--- DETAILED INSTRUCTIONS FOR THIS FILE (from Planner AI) ---\n",
            coder_instruction_for_file,
            "\n--- END OF DETAILED INSTRUCTIONS ---\n\n",
            f"Proceed to generate the complete, production-quality Python code for `{filename}` now, strictly adhering to all instructions and the output format reminder."
        ])

        final_coder_instruction = "".join(final_coder_prompt_parts)
        history_for_llm = [ChatMessage(role=USER_ROLE, parts=[final_coder_instruction])]
        coder_options = {"temperature": 0.2}

        request_id = f"mc_coder_{filename.replace('/', '_').replace('.', '_')}_{uuid.uuid4().hex[:8]}"
        request_metadata = {"purpose": f"mc_request_code_generation_{filename}", "mc_internal_id": request_id,
                            "backend_id_for_mc": GENERATOR_BACKEND_ID}

        response_future = asyncio.Future()
        temp_on_response_slot = None
        temp_on_error_slot = None

        def on_response(resp_request_id, completed_message, usage_stats):
            nonlocal temp_on_response_slot, temp_on_error_slot
            if resp_request_id == request_id:
                if not response_future.done():
                    response_future.set_result(completed_message.text.strip())
                try:
                    if temp_on_response_slot: self._backend_coordinator.response_completed.disconnect(
                        temp_on_response_slot)
                    if temp_on_error_slot: self._backend_coordinator.response_error.disconnect(temp_on_error_slot)
                except TypeError:
                    pass  # Slot not connected
                temp_on_response_slot = temp_on_error_slot = None

        def on_error(err_request_id, error_message_str):
            nonlocal temp_on_response_slot, temp_on_error_slot
            if err_request_id == request_id:
                if not response_future.done():
                    response_future.set_exception(RuntimeError(f"Coder AI error for {filename}: {error_message_str}"))
                try:
                    if temp_on_response_slot: self._backend_coordinator.response_completed.disconnect(
                        temp_on_response_slot)
                    if temp_on_error_slot: self._backend_coordinator.response_error.disconnect(temp_on_error_slot)
                except TypeError:
                    pass  # Slot not connected
                temp_on_response_slot = temp_on_error_slot = None

        temp_on_response_slot = on_response
        temp_on_error_slot = on_error

        try:
            self._backend_coordinator.response_completed.connect(temp_on_response_slot)
            self._backend_coordinator.response_error.connect(temp_on_error_slot)
        except Exception as e_conn:
            logger.error(f"MC: Internal error setting up Coder AI request for {filename}: {e_conn}")
            if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Error]",
                                                                        f"Internal error connecting Coder AI response handlers for {filename}: {e_conn}")
            return filename, None, f"Internal error setting up Coder AI request: {e_conn}"

        if self._llm_comm_logger:
            log_coder_prompt = final_coder_instruction
            if len(log_coder_prompt) > 2000:  # Truncate very long prompts for logging
                log_coder_prompt = log_coder_prompt[:1000] + "\n... (prompt truncated in log) ...\n" + log_coder_prompt[
                                                                                                       -1000:]
            self._llm_comm_logger.log_message("[Code LLM Req]",
                                              f"Sending instructions to Coder AI for: {filename}\n{log_coder_prompt}")

        self.status_update.emit(f"[System: Coder AI processing `{filename}`...]")

        self._backend_coordinator.request_response_stream(
            target_backend_id=GENERATOR_BACKEND_ID,
            request_id=request_id,
            history_to_send=history_for_llm,
            is_modification_response_expected=True,
            options=coder_options,
            request_metadata=request_metadata
        )

        try:
            timeout_seconds = 900.0
            generated_code_text = await asyncio.wait_for(response_future, timeout=timeout_seconds)
            if self._llm_comm_logger:
                # Log raw output for debugging Coder AI formatting issues
                self._llm_comm_logger.log_message("[Code LLM Raw Output]",
                                                  f"'{generated_code_text}'")
                self._llm_comm_logger.log_message("[Code LLM Res]",
                                                  f"Code received from Coder AI for: {filename} (Length: {len(generated_code_text)})")
            return filename, generated_code_text, None
        except asyncio.TimeoutError:
            if not response_future.done(): response_future.cancel()
            err_msg = "Coder AI request timed out."
            if self._llm_comm_logger: self._llm_comm_logger.log_message("[Code LLM Error]",
                                                                        f"Timeout for {filename}: {err_msg}")
            return filename, None, err_msg
        except RuntimeError as e:
            if self._llm_comm_logger: self._llm_comm_logger.log_message("[Code LLM Error]",
                                                                        f"Error for {filename}: {e}")
            return filename, None, str(e)
        except asyncio.CancelledError:
            err_msg = "Coder AI task cancelled."
            if self._llm_comm_logger: self._llm_comm_logger.log_message("[Code LLM Error]",
                                                                        f"Task cancelled for {filename}: {err_msg}")
            return filename, None, err_msg
        except Exception as e_task:
            err_msg = f"Unexpected error: {e_task}"
            if self._llm_comm_logger: self._llm_comm_logger.log_message("[Code LLM Error]",
                                                                        f"Unexpected error for {filename}: {err_msg}")
            logger.exception(f"MC: Unexpected error in _execute_single_code_generation_task for {filename}:")
            return filename, None, err_msg
        finally:
            try:
                if temp_on_response_slot: self._backend_coordinator.response_completed.disconnect(temp_on_response_slot)
                if temp_on_error_slot: self._backend_coordinator.response_error.disconnect(temp_on_error_slot)
            except TypeError:
                pass  # Slot not connected

    # --- END MODIFIED ---

    async def _process_all_files_concurrently(self):
        # ... (remains largely the same, but it now relies on the more detailed Coder prompts from above) ...
        self.status_update.emit(
            f"[System: Coder AI is now generating code for {len(self._planned_files_list)} files concurrently...]")
        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[System Process]",
                                              f"Starting concurrent code generation for {len(self._planned_files_list)} files.")

        tasks_to_run = []
        for filename_to_process in self._planned_files_list:
            if filename_to_process in self._coder_instructions_map and \
                    not self._coder_instructions_map[filename_to_process].startswith("[Error:"):
                task = asyncio.create_task(self._execute_single_code_generation_task(filename_to_process))
                tasks_to_run.append(task)
                self._active_code_generation_tasks[filename_to_process] = task
            else:
                self._generated_file_data[filename_to_process] = (None,
                                                                  self._coder_instructions_map.get(filename_to_process,
                                                                                                   "Instructions unavailable."))
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Warning]",
                                                      f"Skipping code generation for {filename_to_process} due to missing/error in instructions.")

        if not tasks_to_run:
            self.status_update.emit(
                "[System: No files could be prepared for code generation due to instruction errors.]")
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[System Error]",
                                                  "No files could be prepared for concurrent code generation.")
            if any(self._generated_file_data.values()):
                self._current_phase = ModPhase.ALL_FILES_GENERATED_AWAITING_USER_ACTION
                self.status_update.emit(
                    f"[System: All {len(self._planned_files_list)} files processed. Check logs for errors. "
                    "Review in Code Viewer. Provide overall feedback or type 'accept'.]"
                )
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Process]",
                                                      "All planned files processed (some with pre-existing instruction errors). Awaiting user action.")
            else:
                self._handle_sequence_end("error_no_files_to_process_concurrently", "No files to process.", {})
            return

        results = await asyncio.gather(*tasks_to_run, return_exceptions=True)
        self._active_code_generation_tasks.clear()

        files_successfully_generated_count = 0
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                logger.info("MC: A code generation task was cancelled during concurrent processing.")
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Info]", "A code generation task was cancelled.")
                continue

            if isinstance(result, Exception):
                self.status_update.emit(f"[System Error: Exception during code generation: {str(result)[:100]}...]")
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Error]",
                                                      f"Unhandled exception in gather: {str(result)[:100]}...")
                logger.error(f"MC: Gather returned an unexpected exception: {result}", exc_info=result)
                continue

            if not isinstance(result, tuple) or len(result) != 3:
                logger.error(f"MC: Unexpected result format from generation task: {result}")
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Error]",
                                                      f"Unexpected result format from generation task: {type(result)}")
                continue

            filename, generated_content, error_msg = result
            self._generated_file_data[filename] = (generated_content, error_msg)

            if error_msg:
                self.status_update.emit(f"[System Error: Coder AI failed for `{filename}`: {error_msg}]")
            elif generated_content is not None:
                if self._handler.process_llm_code_generation_response(generated_content, filename):
                    parsed_filename_content_tuple = self._handler.get_last_emitted_filename_and_content()
                    if parsed_filename_content_tuple and parsed_filename_content_tuple[0] == filename:
                        actual_filename, actual_content = parsed_filename_content_tuple

                        # --- MODIFIED: Check against original content if modifying ---
                        original_content_for_compare = self._original_file_contents.get(
                            actual_filename) if self._is_modification_of_existing else None
                        is_new_file = not self._is_modification_of_existing or (
                                    self._is_modification_of_existing and original_content_for_compare is None)
                        # --- END MODIFIED ---

                        if not is_new_file and actual_content.strip() == (original_content_for_compare or "").strip():
                            no_change_msg = f"[System: No effective changes applied by Coder AI to `{actual_filename}`.]"
                            self.status_update.emit(no_change_msg)
                            if self._llm_comm_logger: self._llm_comm_logger.log_message("[Code LLM Info]",
                                                                                        f"No effective changes for {actual_filename}.")
                        elif is_new_file and not actual_content.strip():
                            no_content_new_msg = f"[System: No content generated by Coder AI for new file `{actual_filename}`.]"
                            self.status_update.emit(no_content_new_msg)
                            if self._llm_comm_logger: self._llm_comm_logger.log_message("[Code LLM Info]",
                                                                                        f"No content generated for new file {actual_filename}.")
                        else:
                            files_successfully_generated_count += 1
                            lines = actual_content.splitlines()
                            if len(lines) > self.MAX_LINES_BEFORE_SPLIT:
                                split_point = len(lines) // 2
                                part1_content = "\n".join(lines[:split_point])
                                part2_content = "\n".join(lines[split_point:])
                                self.file_ready_for_display.emit(actual_filename + " (Part 1/2)", part1_content)
                                self.file_ready_for_display.emit(actual_filename + " (Part 2/2)", part2_content)
                            else:
                                self.file_ready_for_display.emit(actual_filename, actual_content)
                            self.status_update.emit(f"[System: Code for `{actual_filename}` generated/updated.]")
                            # Store the successfully parsed and potentially modified content
                            self._generated_file_data[filename] = (actual_content, None)
                    else:
                        mismatch_err = f"Filename mismatch after MH parsing for '{filename}'. Expected '{filename}', got '{parsed_filename_content_tuple[0] if parsed_filename_content_tuple else 'None'}'."
                        self.status_update.emit(f"[System Warning: Output issue for `{filename}`.]")
                        if self._llm_comm_logger: self._llm_comm_logger.log_message("[System Warning]", mismatch_err)
                        self._generated_file_data[filename] = (generated_content,
                                                               mismatch_err)  # Store raw generated content with error
                else:
                    parsing_error_msg = f"Coder AI output format error for `{filename}`."
                    self.status_update.emit(f"[System Error: {parsing_error_msg}]")
                    if self._llm_comm_logger: self._llm_comm_logger.log_message("[Code LLM Error]", parsing_error_msg)
                    self._generated_file_data[filename] = (generated_content,
                                                           parsing_error_msg)  # Store raw generated content with error
            else:
                no_content_msg = f"Coder AI returned no content for `{filename}`."
                self.status_update.emit(f"[System: {no_content_msg}]")
                if self._llm_comm_logger: self._llm_comm_logger.log_message("[Code LLM Info]", no_content_msg)
                self._generated_file_data[filename] = (None, no_content_msg)

        num_errors = sum(1 for _, err in self._generated_file_data.values() if err)
        planned_count = len(self._planned_files_list)
        final_status_msg = ""
        if files_successfully_generated_count == planned_count and num_errors == 0:
            final_status_msg = f"[System: All {planned_count} files generated/updated successfully! Review in Code Viewer. Provide overall feedback or type 'accept'.]"
        elif files_successfully_generated_count > 0:
            final_status_msg = (
                f"[System: {files_successfully_generated_count}/{planned_count} files generated/updated. "
                f"{num_errors} file(s) had issues. Review in Code Viewer and logs. Provide overall feedback or type 'accept'.]")
        else:
            final_status_msg = (f"[System: All {planned_count} planned files encountered issues during generation. "
                                f"Check logs. Review in Code Viewer. Provide overall feedback or type 'accept'.]")

        self.status_update.emit(final_status_msg)
        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[System Process]",
                                              f"Concurrent code generation finished. Success: {files_successfully_generated_count}/{planned_count}, Errors: {num_errors}. Awaiting user action.")

        self._current_phase = ModPhase.ALL_FILES_GENERATED_AWAITING_USER_ACTION
        self._is_awaiting_llm = False

    # --- MODIFIED: _read_original_file_content ---
    def _read_original_file_content(self, relative_filename: str) -> Optional[str]:
        """
        Reads content of a file, resolving its path using focus_prefix or treating as absolute.
        Uses FileHandlerService.
        """
        if not self._file_handler_service:
            logger.error("MC: FileHandlerService not available to read original file content.")
            return None

        content: Optional[str] = None
        full_path: Optional[str] = None
        norm_relative_filename = os.path.normpath(relative_filename)  # Normalize for current OS

        # Try resolving with focus_prefix first
        if self._original_focus_prefix and os.path.isdir(self._original_focus_prefix):
            potential_path = os.path.join(self._original_focus_prefix, norm_relative_filename)
            if os.path.exists(potential_path) and os.path.isfile(potential_path):
                full_path = os.path.abspath(potential_path)
                logger.debug(f"MC: Resolved '{relative_filename}' to '{full_path}' using focus_prefix.")

        # If not found with focus_prefix, check if norm_relative_filename is already absolute
        if not full_path and os.path.isabs(norm_relative_filename):
            if os.path.exists(norm_relative_filename) and os.path.isfile(norm_relative_filename):
                full_path = norm_relative_filename  # It's already an absolute path
                logger.debug(f"MC: Using '{relative_filename}' as an absolute path: '{full_path}'.")

        # If still not resolved, it might be a path relative to CWD or unfindable without more info
        if not full_path:
            # For now, we won't try CWD to avoid ambiguity. If focus_prefix is not set or helpful,
            # and the path isn't absolute, we treat it as "not found for now".
            # Later, a "project root" from ProjectContextManager could be another fallback.
            logger.warning(
                f"MC: Could not resolve path for '{relative_filename}'. Focus prefix: '{self._original_focus_prefix}'. File assumed not found or path is ambiguous.")
            return None

        if full_path:
            try:
                file_content, file_type, error_msg = self._file_handler_service.read_file_content(full_path)
                if file_type == "text" and file_content is not None:
                    content = file_content
                elif error_msg:
                    logger.warning(f"MC: Error reading file '{full_path}' via FileHandlerService: {error_msg}")
                elif file_type != "text":
                    logger.warning(
                        f"MC: File '{full_path}' is not a text file (type: {file_type}). Cannot use content for modification.")
            except Exception as e:
                logger.error(f"MC: Exception reading original file {full_path} via FileHandlerService: {e}")
                content = None
        return content

    # --- END MODIFIED ---

    def process_llm_response(self, backend_id: str, response_message: ChatMessage):
        # ... (remains the same)
        if not self._is_active or not self._is_awaiting_llm:
            return
        response_text = response_message.text.strip()
        try:
            if self._current_phase == ModPhase.AWAITING_PLAN_AND_ALL_CODER_INSTRUCTIONS and backend_id == PLANNER_BACKEND_ID:
                self._handle_plan_response(response_text)
            else:
                self._is_awaiting_llm = False
                err_msg = f"Unexpected LLM response from '{backend_id}' for phase {self._current_phase}."
                self.modification_error.emit(err_msg)
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[System Error]",
                                                      f"Unexpected LLM response. Backend: {backend_id}, Phase: {self._current_phase}.")
                self._handle_sequence_end("error_unexpected_response_phase", err_msg, {})
        except Exception as e:
            self._is_awaiting_llm = False
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[System Error]",
                                                  f"Error processing LLM response from {backend_id}: {e}")
            logger.exception(f"MC: Error processing LLM response from {backend_id}:")
            self._handle_sequence_end("error_processing_llm_response", f"Error processing {backend_id} response: {e}",
                                      {})

    def process_llm_error(self, backend_id: str, error_message: str):
        # ... (remains the same)
        if not self._is_active or not self._is_awaiting_llm:
            return

        self._is_awaiting_llm = False
        phase_at_error = self._current_phase

        if self._llm_comm_logger:
            self._llm_comm_logger.log_message(f"[{backend_id} Error]",
                                              f"LLM call failed during phase '{phase_at_error}': {error_message}")

        if phase_at_error == ModPhase.AWAITING_PLAN_AND_ALL_CODER_INSTRUCTIONS and backend_id == PLANNER_BACKEND_ID:
            err_msg_ui = f"Planner AI Error: {error_message}. Cannot proceed with modification."
            self.modification_error.emit(err_msg_ui)
            self._handle_sequence_end("error_planner_ai_failed", err_msg_ui, {})
        else:
            err_msg_ui = f"Unexpected LLM Error from '{backend_id}' during phase '{phase_at_error}': {error_message}"
            self.modification_error.emit(err_msg_ui)
            self._handle_sequence_end("error_unexpected_llm_error_phase", err_msg_ui, {})

    def process_user_input(self, user_command: str):
        # ... (remains the same, but the refinement logic will now re-trigger the adapted planner)
        if not self._is_active: return

        if self._is_awaiting_llm or self._current_phase == ModPhase.GENERATING_CODE_CONCURRENTLY:
            self.status_update.emit("[System: Please wait for the current AI processing to complete.]")
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[User Action]", f"Input '{user_command[:30]}...' ignored, AI busy.")
            return

        command_lower = user_command.lower().strip()

        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[User Input]", f"Received command: '{user_command}'")

        if command_lower in ["cancel", "stop", "abort"]:
            if self._llm_comm_logger: self._llm_comm_logger.log_message("[User Action]", "Cancellation requested.")
            self._handle_sequence_end("cancelled_by_user", "User cancelled the modification process.", {})
            return

        if self._current_phase == ModPhase.ALL_FILES_GENERATED_AWAITING_USER_ACTION:
            if command_lower in ["accept", "done", "looks good", "ok", "okay", "proceed", "complete", "finalize"]:
                if self._llm_comm_logger: self._llm_comm_logger.log_message("[User Action]",
                                                                            "All generated files accepted.")
                self._handle_sequence_end("completed_by_user_acceptance", "User accepted all generated files.",
                                          self._generated_file_data)
            else:  # Refinement request
                self.status_update.emit(
                    f"[System: Received overall feedback: \"{user_command[:50]}...\". Requesting full re-plan...]")
                if self._llm_comm_logger:
                    self._llm_comm_logger.log_message("[User Feedback]",
                                                      f"Overall feedback for refinement: \"{user_command[:100]}...\"")
                self._original_query = f"The initial request was: '{self._original_query_at_start}'. Based on the generated files, the user now provides this overall feedback for refinement: '{user_command}'"
                # Reset relevant state for a new planning phase
                self._is_awaiting_llm = False
                self._planned_files_list = []
                self._coder_instructions_map = {}
                # Keep _original_file_contents as they might be needed for the re-plan.
                # Keep _is_modification_of_existing as True.
                # Keep _identified_target_files_from_query as is, planner can re-evaluate.
                self._generated_file_data = {}  # Clear previously generated data

                self._request_plan_and_coder_instructions()  # Re-trigger planning
        else:
            self.status_update.emit(
                f"[System: Currently processing. Please wait until all files are generated to provide overall feedback or type 'cancel'.]")
            if self._llm_comm_logger:
                self._llm_comm_logger.log_message("[User Action]",
                                                  f"Input '{user_command[:30]}...' ignored, awaiting current phase completion.")

    @pyqtSlot(str)
    def _handle_mh_parsing_error(self, error_message: str):
        # ... (remains the same)
        if not self._is_active: return

        filename_match = re.search(r"for '([^']*)'", error_message)
        filename_affected = filename_match.group(1) if filename_match else "unknown file"
        self.status_update.emit(
            f"[System Error: Coder AI output for `{filename_affected}` was not in the expected format. This file may be incomplete or incorrect.]")

        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[Code LLM Error]",
                                              f"Output parsing error for '{filename_affected}': Response not in expected Markdown format.")

        if filename_affected in self._generated_file_data:
            existing_content, _ = self._generated_file_data[filename_affected]
            self._generated_file_data[filename_affected] = (existing_content, error_message)
        else:
            self._generated_file_data[filename_affected] = (None, error_message)

    def _parse_files_to_modify_list(self, response_text: str) -> Tuple[Optional[List[str]], Optional[str]]:
        # ... (remains the same)
        marker = "FILES_TO_MODIFY:"
        try:
            marker_pos = response_text.find(marker)
            if marker_pos == -1:
                match_marker_re = re.search(r"FILES_TO_MODIFY\s*:", response_text, re.IGNORECASE)
                if not match_marker_re:
                    return None, f"Marker '{marker}' (case-sensitive or insensitive) not found in Planner response."
                list_str_start = match_marker_re.end()
            else:
                list_str_start = marker_pos + len(marker)

        except ValueError:  # Should not be reached if find() is used
            return None, f"Marker '{marker}' not found in Planner response (ValueError)."

        potential_list_str = response_text[list_str_start:].strip()
        first_line_of_potential_list = potential_list_str.split('\n', 1)[0].strip()
        list_str_for_eval = None

        # Try to match a Python list literal on the first line after the marker
        list_match_bracket = re.match(r"(\[.*?\])", first_line_of_potential_list)

        if list_match_bracket:
            list_str_for_eval = list_match_bracket.group(1)
        else:
            # If not on the first line, try to find a potentially multi-line list
            # This regex is basic and might need refinement for complex cases
            multiline_list_match = re.search(r"\[\s*(?:(?:'.*?'|\".*?\")\s*,\s*)*\s*(?:'.*?'|\".*?\")?\s*\]",
                                             potential_list_str, re.DOTALL)
            if multiline_list_match:
                list_str_for_eval = multiline_list_match.group(0)
            else:
                return None, "FILES_TO_MODIFY list not found or not correctly formatted with brackets starting on the first line or as a recognizable Python list after the marker."
        try:
            # Remove "python" prefix if it exists (sometimes LLMs add it)
            if list_str_for_eval.lower().startswith("python"):
                list_str_for_eval = re.sub(r"^[Pp][Yy][Tt][Hh][Oo][Nn]\s*", "", list_str_for_eval)

            parsed_list = ast.literal_eval(list_str_for_eval)
            if not isinstance(parsed_list, list):
                return None, "Parsed data for FILES_TO_MODIFY is not a list."
            # Clean up paths: strip quotes, normalize slashes
            cleaned_list = [str(f).strip().replace("\\", "/") for f in parsed_list if isinstance(f, (str, int,
                                                                                                     float))]  # Allow numbers/floats if LLM makes mistake, convert to str
            return [f_item for f_item in cleaned_list if f_item], None  # Filter out empty strings after stripping
        except (ValueError, SyntaxError, TypeError) as e:
            return None, f"Error parsing FILES_TO_MODIFY list string '{list_str_for_eval}': {e}"

    def cancel_sequence(self, reason: str = "cancelled_externally"):
        # ... (remains the same)
        if not self._is_active: return
        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[System Process]", f"Sequence cancelled. Reason: {reason}")
        self._handle_sequence_end(reason, f"Sequence cancelled: {reason}", {})

    def _handle_sequence_end(self, reason: str, details: Optional[str] = None,
                             generated_files_data: Optional[Dict[str, Tuple[Optional[str], Optional[str]]]] = None):
        # ... (remains the same)
        if not self._is_active and reason != "error_processing_llm_response":  # Allow error from non-active if LLM was pending
            return

        log_message = f"MC: Ending sequence. Reason: {reason}."
        if details: log_message += f" Details: {details}"
        logger.info(log_message)

        effective_generated_files = generated_files_data if generated_files_data is not None else {}

        if self._llm_comm_logger:
            self._llm_comm_logger.log_message("[System Process]",
                                              f"Modification sequence ended. Reason: {reason}. Details: {details or 'N/A'}")

        for filename, task in list(self._active_code_generation_tasks.items()):
            if task and not task.done():
                logger.debug(f"MC: Cancelling active code gen task for {filename} during sequence end.")
                task.cancel()
        self._active_code_generation_tasks.clear()

        original_query_summary = self._original_query_at_start[:75] + '...' if self._original_query_at_start and len(
            self._original_query_at_start) > 75 else self._original_query_at_start or "User's request"

        self.modification_sequence_complete.emit(reason, original_query_summary, effective_generated_files)
        self._reset_state()