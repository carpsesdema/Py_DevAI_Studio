# core/user_input_processor.py
import logging
import os
import re  # Ensure re is imported
from typing import List, Optional, Dict, Any, Tuple, Union, NamedTuple, TYPE_CHECKING

from core.models import ChatMessage, USER_ROLE

if TYPE_CHECKING:
    from core.rag_handler import RagHandler
    from core.modification_handler import ModificationHandler

logger = logging.getLogger(__name__)


class ProcessResult(NamedTuple):
    action_type: str
    prompt_or_history: Union[str, List[ChatMessage], str]  # Existing field
    original_query: Optional[str] = None
    original_context: Optional[str] = None
    original_focus_prefix: Optional[str] = None
    # --- NEW FIELDS FOR MODIFICATION ---
    identified_target_files: Optional[List[str]] = None  # List of filenames parsed from query
    # current_project_id is already passed into process method, so MC will get it from there.
    # --- END NEW FIELDS ---


class UserInputProcessor:
    _NEXT_COMMANDS = {"next", "ok", "okay", "continue", "yes", "proceed", "go", "next file"}
    _STRONG_MODIFICATION_KEYWORDS = {
        "refactor", "restructure", "reorganize my project", "overhaul",
        "implement feature across", "integrate throughout", "update all instances of",
        "modify file", "change file", "edit file"  # More explicit file ops
    }
    _GENERAL_MODIFICATION_KEYWORDS = {
        "change", "update", "modify", "apply", "implement", "add", "fix", "remove",
        "create", "generate files for", "edit", "adjust", "correct", "make changes to"
    }
    # Keywords that, if combined with filenames, strongly suggest modification
    _FILENAME_CONTEXT_MODIFICATION_KEYWORDS = {
        "in file", "to file", "for file", "within file",
        "in the file", "to the file", "for the file", "within the file",
        "on file", "on the file"
    }

    _PROJECT_SUMMARY_KEYWORDS = {
        "summarize project", "project summary", "summarise project", "project overview",
        "overview of project", "tell me about this project", "what's in this project",
        "explain this project", "summarize rag", "rag summary", "summarise rag",
        "ava summarize", "ava project summary", "ava project overview"
    }

    # Regex to find potential filenames (can be refined)
    # Looks for words with common code extensions, or words with dots and slashes.
    # Allows for paths like ./src/file.py or just file.py or even src/file.py
    _FILENAME_REGEX = re.compile(
        r"([\w\-\./\\]+\.(?:py|js|ts|java|c|cpp|h|cs|go|rb|php|html|css|scss|json|xml|yaml|yml|md|txt|ini|cfg|sh|bat|ps1|config|settings|env|dockerfile|gitignore|ipynb|rst|toml|lock|ini|cfg|conf|test|spec))\b"
    )

    def __init__(self, rag_handler: Optional['RagHandler'], modification_handler: Optional['ModificationHandler']):
        self._rag_handler = rag_handler
        self._modification_handler = modification_handler
        logger.info("UserInputProcessor initialized.")
        if not self._rag_handler: logger.warning("UserInputProcessor: RagHandler not provided.")
        if not self._modification_handler: logger.warning("UserInputProcessor: ModificationHandler not provided.")

    def _extract_target_files(self, query: str) -> List[str]:
        """Extracts potential filenames from the query."""
        normalized_query = query.replace("\\", "/")

        # Find all potential matches
        found_files_with_context = self._FILENAME_REGEX.finditer(normalized_query)

        extracted_files = []
        for match in found_files_with_context:
            filename = match.group(1).strip("'\"")  # Get the filename and strip quotes

            # Check if this "filename" might actually be part of a URL or similar unwanted context
            # This is a heuristic and might need refinement
            preceding_char_index = match.start(1) - 1
            if preceding_char_index >= 0:
                pre_char = normalized_query[preceding_char_index]
                # Avoid if it looks like part of a URL scheme or common web prefix
                if pre_char in [':', '/'] and "http" in normalized_query[max(0,
                                                                             preceding_char_index - 10):preceding_char_index + 1].lower():
                    logger.debug(f"UIP: Skipping potential file '{filename}' as it looks like part of a URL.")
                    continue

            extracted_files.append(filename)

        unique_files = sorted(list(set(extracted_files)))
        if unique_files:
            logger.info(f"UIP: Extracted potential target files: {unique_files} from query: '{query[:50]}...'")
        return unique_files

    def process(self,
                user_query_text: str,
                image_data: List[Dict[str, Any]],
                is_modification_active: bool,
                current_project_id: Optional[str],
                focus_paths: Optional[List[str]],
                rag_available: bool,
                rag_initialized: bool) -> ProcessResult:
        logger.debug(
            f"UIP processing. Mod Active: {is_modification_active}, Query: '{user_query_text[:50]}...', Focus: {focus_paths}, Proj: {current_project_id}")
        query_lower = user_query_text.lower().strip()

        # 1. Handle Project Summary Request (remains the same)
        if any(keyword in query_lower for keyword in self._PROJECT_SUMMARY_KEYWORDS):
            is_direct_summary_command = False
            for kw in self._PROJECT_SUMMARY_KEYWORDS:
                if query_lower == kw or \
                        query_lower.startswith(kw + " ") or \
                        query_lower.startswith(kw + ",") or \
                        query_lower.startswith(kw + "."):
                    is_direct_summary_command = True
                    break
            if is_direct_summary_command:
                logger.info(
                    f"Project summary request detected for project: '{current_project_id}'. Query: '{user_query_text}'")
                return ProcessResult(
                    action_type="REQUEST_PROJECT_SUMMARY",
                    prompt_or_history=current_project_id or "",  # Pass project_id as payload
                    original_query=user_query_text  # Keep original query for display
                )

        # 2. Handle Input During Active Modification (remains the same)
        if is_modification_active and self._modification_handler:
            logger.debug("UIP: Processing input during active modification sequence.")
            is_next_command = user_query_text.lower() in self._NEXT_COMMANDS
            if is_next_command:
                return ProcessResult(action_type="NEXT_MODIFICATION",
                                     prompt_or_history=user_query_text)
            else:  # Any other input is considered refinement feedback
                return ProcessResult(action_type="REFINE_MODIFICATION",
                                     prompt_or_history=user_query_text)

        # 3. Detect "Modify Existing Project" Intent (NEW/ENHANCED LOGIC)
        identified_files_from_query = self._extract_target_files(user_query_text)

        is_strong_modify_intent = any(kw in query_lower for kw in self._STRONG_MODIFICATION_KEYWORDS)
        is_general_modify_intent = any(kw in query_lower for kw in self._GENERAL_MODIFICATION_KEYWORDS)
        mentions_filename_context = any(kw in query_lower for kw in self._FILENAME_CONTEXT_MODIFICATION_KEYWORDS)

        attempt_modify_existing = False
        if self._modification_handler:  # Ensure handler is available for any modification
            if is_strong_modify_intent:
                attempt_modify_existing = True
            elif is_general_modify_intent and (identified_files_from_query or focus_paths or mentions_filename_context):
                # If general keywords are used, we need more context like filenames or focus
                attempt_modify_existing = True

        if attempt_modify_existing:
            logger.info(f"UIP: Potential 'Modify Existing' intent detected for query: '{user_query_text[:50]}...'")

            rag_context_str_for_mod, determined_focus_prefix = self._get_rag_and_focus(
                query=user_query_text, is_modification=True,  # Signal that this is for a modification context
                current_project_id=current_project_id, focus_paths=focus_paths,
                rag_available=rag_available, rag_initialized=rag_initialized
            )
            logger.info(
                f"UIP: For 'Modify Existing', RAG context length: {len(rag_context_str_for_mod)}, Focus Prefix: '{determined_focus_prefix}'")

            return ProcessResult(
                action_type="START_MODIFICATION_EXISTING",  # New action type
                prompt_or_history=[],  # No direct prompt for LLM from here; MC will build it
                original_query=user_query_text,
                original_context=rag_context_str_for_mod,
                original_focus_prefix=determined_focus_prefix,
                identified_target_files=identified_files_from_query  # Pass the files found
            )

        # 4. Detect "Bootstrap New Project" (START_MODIFICATION - original multi-file creation)
        # This should come AFTER "Modify Existing" to avoid misinterpreting "create file x.py"
        # as bootstrapping if it's part of a modification request.
        # We can make the "bootstrap" keywords more specific.
        bootstrap_keywords = {"bootstrap", "create new app", "new project:", "generate new project", "scaffold"}
        is_bootstrap_request = any(kw in query_lower for kw in bootstrap_keywords)

        if is_bootstrap_request and self._modification_handler:  # and not identified_files_from_query (optional: to be very sure it's not about existing files)
            logger.info("UIP: Potential 'Bootstrap New Project' intent detected.")
            rag_context_str_for_bootstrap, determined_focus_prefix_bootstrap = self._get_rag_and_focus(
                query=user_query_text, is_modification=True,  # Bootstrap is a type of modification sequence
                current_project_id=current_project_id, focus_paths=focus_paths,
                # Focus paths might be relevant for style/libs
                rag_available=rag_available, rag_initialized=rag_initialized
            )
            return ProcessResult(
                action_type="START_MODIFICATION",  # Existing action type for bootstrapping
                prompt_or_history=[],
                original_query=user_query_text,
                original_context=rag_context_str_for_bootstrap,
                original_focus_prefix=determined_focus_prefix_bootstrap
            )

        # 5. Default to Normal Chat
        logger.info("UIP: Processing as normal chat message.")
        rag_context_str_for_chat, determined_focus_prefix_chat = self._get_rag_and_focus(
            query=user_query_text, is_modification=False,  # Not a modification context for RAG
            current_project_id=current_project_id, focus_paths=focus_paths,
            rag_available=rag_available, rag_initialized=rag_initialized
        )
        final_text_for_llm = self._prepare_normal_chat_prompt(user_query_text, rag_context_str_for_chat,
                                                              determined_focus_prefix_chat)
        final_parts = [final_text_for_llm] + (image_data or [])
        message_for_backend = ChatMessage(role=USER_ROLE, parts=final_parts)
        return ProcessResult(action_type="NORMAL_CHAT", prompt_or_history=[message_for_backend])

    def _get_rag_and_focus(self, query: str, is_modification: bool, current_project_id: Optional[str],
                           focus_paths: Optional[List[str]], rag_available: bool, rag_initialized: bool) -> Tuple[
        str, str]:
        rag_context_str = ""
        determined_focus_prefix = ""
        if not self._rag_handler:
            logger.warning("UIP: RagHandler not available, cannot perform RAG or determine focus prefix from paths.")
            if focus_paths:
                logger.info("UIP: RagHandler missing, but attempting to derive focus_prefix from focus_paths.")
                if len(focus_paths) == 1 and os.path.isfile(focus_paths[0]):
                    determined_focus_prefix = os.path.dirname(os.path.abspath(focus_paths[0]))
                elif len(focus_paths) > 0:
                    try:
                        abs_paths = [os.path.abspath(p) for p in focus_paths]
                        common = os.path.commonpath(abs_paths)
                        if os.path.isdir(common):
                            determined_focus_prefix = common
                        elif os.path.isfile(common):
                            determined_focus_prefix = os.path.dirname(common)
                        else:
                            first_path_dir = os.path.dirname(abs_paths[0])
                            if os.path.isdir(first_path_dir): determined_focus_prefix = first_path_dir
                    except ValueError:
                        first_path_dir = os.path.dirname(os.path.abspath(focus_paths[0]))
                        if os.path.isdir(first_path_dir): determined_focus_prefix = first_path_dir
                if determined_focus_prefix: logger.info(
                    f"UIP: (No RAG) Determined focus_prefix: '{determined_focus_prefix}'")
            return rag_context_str, determined_focus_prefix

        should_rag = False
        if is_modification:  # For modification, RAG is almost always useful if available
            should_rag = rag_available and rag_initialized
            logger.debug(
                f"UIP: RAG for modification: available={rag_available}, initialized={rag_initialized} => should_rag={should_rag}")
        else:  # For normal chat, use the keyword-based check
            should_rag = self._rag_handler.should_perform_rag(query, rag_available, rag_initialized)
            logger.debug(f"UIP: RAG for normal chat: should_perform_rag result => {should_rag}")

        if should_rag:
            query_entities = self._rag_handler.extract_code_entities(query)
            rag_context_str, queried_collections = self._rag_handler.get_formatted_context(
                query=query, query_entities=query_entities, project_id=current_project_id,
                focus_paths=focus_paths, is_modification_request=is_modification
            )
        else:
            logger.debug("UIP: RAG not performed for this query based on checks.")

        if focus_paths:
            num_focused = len(focus_paths)
            if num_focused == 1 and os.path.isfile(focus_paths[0]):
                determined_focus_prefix = os.path.dirname(os.path.abspath(focus_paths[0]))
            elif num_focused > 0:
                abs_paths = [os.path.abspath(p) for p in focus_paths]
                try:
                    common = os.path.commonpath(abs_paths)
                    if os.path.isdir(common):
                        determined_focus_prefix = common
                    elif os.path.isfile(common):
                        determined_focus_prefix = os.path.dirname(common)
                    else:
                        first_path_dir = os.path.dirname(abs_paths[0])
                        if os.path.isdir(first_path_dir):
                            determined_focus_prefix = first_path_dir
                        else:
                            determined_focus_prefix = os.getcwd(); logger.warning(
                                f"UIP: Could not determine common dir for focus_paths: {focus_paths}. Defaulting focus_prefix to CWD.")
                except ValueError:  # Handles different drives on Windows for commonpath
                    first_path_dir = os.path.dirname(abs_paths[0])
                    if os.path.isdir(first_path_dir):
                        determined_focus_prefix = first_path_dir; logger.warning(
                            f"UIP: ValueError finding commonpath for {focus_paths}. Using dir of first path.")
                    else:
                        determined_focus_prefix = os.getcwd(); logger.warning(
                            f"UIP: Could not determine common dir for {focus_paths}. Defaulting focus_prefix to CWD.")
            if determined_focus_prefix:
                logger.info(
                    f"UIP: Determined focus_prefix: '{determined_focus_prefix}' from {num_focused} focus_paths.")
            else:
                logger.warning(f"UIP: Could not determine focus_prefix from focus_paths: {focus_paths}.")
        return rag_context_str, determined_focus_prefix

    def _prepare_normal_chat_prompt(self, user_query: str, rag_context: str, focus_prefix_from_paths: str) -> str:
        focus_display_prefix = ""
        if focus_prefix_from_paths:
            try:
                base_name = os.path.basename(focus_prefix_from_paths)
                if not base_name and len(focus_prefix_from_paths) > 1: base_name = focus_prefix_from_paths
                focus_display_prefix = f"[Focusing on files within or related to directory: `{base_name or focus_prefix_from_paths}`]\n\n"
            except Exception:
                focus_display_prefix = f"[Focusing on files within or related to directory: `{focus_prefix_from_paths}`]\n\n"

        if rag_context or focus_display_prefix:
            prompt_template = (
                "{focus_display}" "User Query: {query}\n\n" "{context_section}" "Based on the above query and context (if provided), please respond.")
            context_section = f"Relevant Context:\n{rag_context}\n\n" if rag_context else ""
            final_prompt = prompt_template.format(focus_display=focus_display_prefix, query=user_query,
                                                  context_section=context_section)
            return final_prompt
        else:
            return user_query